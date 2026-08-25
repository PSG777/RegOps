import pytest
from pydantic import ValidationError

from regops import (
    FakeToolRegistry,
    InvocationMetadata,
    PolicyEngine,
    PolicyRegistry,
    RefundAgent,
    RuntimeGateway,
    build_local_agent_registry,
    financial_policy_v1,
)
from regops.models import (
    ActionType,
    DataClassification,
    Decision,
    DestinationType,
    ExecutionStatus,
    Purpose,
)
from regops.tools import FakeTool, ToolMetadata


@pytest.fixture
def runtime():
    policies = PolicyRegistry()
    tools = FakeToolRegistry()
    agents = build_local_agent_registry()
    gateway = RuntimeGateway(policies, tools, agents, PolicyEngine())
    return RefundAgent(gateway), policies, tools, gateway


def invocation(*classifications, purpose=Purpose.CUSTOMER_SUPPORT):
    return InvocationMetadata(
        data_classifications=frozenset(classifications),
        purpose=purpose,
    )


def activate_financial_policy(policies):
    policies.register(financial_policy_v1())
    policies.activate("FIN-POL-v1")


def test_bank_account_can_be_sent_by_gmail_without_active_policy(runtime):
    agent, _, tools, gateway = runtime

    result = agent.propose_tool_call(
        "gmail.send",
        {"to": "customer@example.com", "body": "Account: ****6789"},
        invocation(DataClassification.BANK_ACCOUNT),
    )

    assert result.decision.decision == Decision.ALLOW
    assert len(tools.resolve("gmail.send").executions) == 1
    assert gateway.audit_events[-1].execution_status == ExecutionStatus.SUCCEEDED
    assert not hasattr(gateway.audit_events[-1].context, "arguments")


def test_active_policy_denies_bank_account_sent_by_gmail(runtime):
    agent, policies, tools, gateway = runtime
    activate_financial_policy(policies)

    result = agent.propose_tool_call(
        "gmail.send",
        {"to": "customer@example.com", "body": "Account: ****6789"},
        invocation(DataClassification.BANK_ACCOUNT),
    )

    assert result.decision.decision == Decision.DENY
    assert result.decision.policy_id == "FIN-POL-v1"
    assert tools.resolve("gmail.send").executions == []
    assert gateway.audit_events[-1].execution_status == ExecutionStatus.NOT_ATTEMPTED


def test_non_sensitive_refund_confirmation_through_gmail_is_allowed(runtime):
    agent, policies, tools, gateway = runtime
    activate_financial_policy(policies)

    result = agent.propose_tool_call(
        "gmail.send",
        {"to": "customer@example.com", "body": "Your refund is confirmed."},
        invocation(),
    )

    assert result.decision.decision == Decision.ALLOW
    assert len(tools.resolve("gmail.send").executions) == 1
    assert gateway.audit_events[-1].context.data_classifications == frozenset()


def test_bank_account_to_stripe_for_authorized_transaction_is_allowed(runtime):
    agent, policies, tools, gateway = runtime
    activate_financial_policy(policies)

    result = agent.propose_tool_call(
        "stripe.refund",
        {"customer_id": "cus_123", "amount_cents": 2500},
        invocation(
            DataClassification.BANK_ACCOUNT,
            purpose=Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
        ),
    )

    assert result.decision.decision == Decision.ALLOW
    assert result.output["status"] == "succeeded"
    event = gateway.audit_events[-1]
    assert event.context.destination_type == DestinationType.APPROVED_PAYMENT_PROCESSOR
    assert event.execution_status == ExecutionStatus.SUCCEEDED


def test_caller_cannot_override_gmail_destination(runtime):
    agent, policies, _, gateway = runtime
    activate_financial_policy(policies)

    with pytest.raises(ValidationError):
        InvocationMetadata.model_validate(
            {
                "data_classifications": ["BANK_ACCOUNT"],
                "purpose": "AUTHORIZED_FINANCIAL_TRANSACTION",
                "destination_type": "APPROVED_PAYMENT_PROCESSOR",
            }
        )

    result = agent.propose_tool_call(
        "gmail.send",
        {"body": "Account: ****6789"},
        invocation(
            DataClassification.BANK_ACCOUNT,
            purpose=Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
        ),
    )
    assert result.decision.decision == Decision.DENY
    assert gateway.audit_events[-1].context.destination_type == DestinationType.EMAIL_PROVIDER


def test_failed_allowed_tool_execution_is_audited_and_reraised(runtime):
    agent, _, tools, gateway = runtime
    failure = RuntimeError("sensitive provider response")
    tools.register(
        FakeTool(
            name="gmail.send",
            metadata=ToolMetadata(
                action_type=ActionType.TRANSMIT,
                destination_type=DestinationType.EMAIL_PROVIDER,
            ),
            result_factory=lambda _: (_ for _ in ()).throw(failure),
        )
    )

    with pytest.raises(RuntimeError) as raised:
        agent.propose_tool_call(
            "gmail.send",
            {"body": "not retained"},
            invocation(),
        )

    assert raised.value is failure
    event = gateway.audit_events[-1]
    assert event.decision.decision == Decision.ALLOW
    assert event.tool_executed is True
    assert event.execution_status == ExecutionStatus.FAILED
    assert event.error_type == "RuntimeError"
    assert "sensitive provider response" not in event.model_dump_json()
