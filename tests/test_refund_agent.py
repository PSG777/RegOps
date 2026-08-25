import pytest

from regops import (
    LEGITIMATE_REFUND_REQUEST,
    UNSAFE_EMAIL_REQUEST,
    FakeToolRegistry,
    PolicyRegistry,
    RefundAgent,
    RuntimeGateway,
    build_local_agent_registry,
    financial_policy_v1,
)
from regops.models import DataClassification, Decision, ExecutionStatus, Purpose


@pytest.fixture
def demo_runtime():
    policies = PolicyRegistry()
    tools = FakeToolRegistry()
    agents = build_local_agent_registry()
    gateway = RuntimeGateway(policies, tools, agents)
    return RefundAgent(gateway), policies, tools, gateway


def activate_financial_policy(policies):
    policies.register(financial_policy_v1())
    policies.activate("FIN-POL-v1")


def test_same_unsafe_workflow_is_allowed_before_and_denied_after_policy(demo_runtime):
    agent, policies, tools, _ = demo_runtime

    before = agent.run(UNSAFE_EMAIL_REQUEST)
    assert before.action.decision.decision == Decision.ALLOW
    assert before.audit_events[-1].context.data_classifications == frozenset(
        {DataClassification.BANK_ACCOUNT}
    )
    assert before.audit_events[-1].context.purpose == Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL
    assert before.audit_events[-1].execution_status == ExecutionStatus.SUCCEEDED
    assert len(tools.resolve("gmail.send").executions) == 1

    activate_financial_policy(policies)
    after = agent.run(UNSAFE_EMAIL_REQUEST)

    assert after.request == before.request
    assert after.action.decision.decision == Decision.DENY
    assert after.action.decision.policy_id == "FIN-POL-v1"
    assert after.audit_events[-1].execution_status == ExecutionStatus.NOT_ATTEMPTED
    assert after.audit_events[-1].tool_executed is False
    assert len(tools.resolve("gmail.send").executions) == 1


def test_legitimate_refund_remains_allowed_with_policy_and_is_audited(demo_runtime):
    agent, policies, tools, _ = demo_runtime
    activate_financial_policy(policies)

    result = agent.run(LEGITIMATE_REFUND_REQUEST)

    assert result.action.decision.decision == Decision.ALLOW
    assert result.action.output["status"] == "succeeded"
    assert len(tools.resolve("stripe.refund").executions) == 1
    assert [event.context.tool_name for event in result.audit_events] == [
        "customer_db.read",
        "stripe.refund",
    ]
    assert all(event.decision.decision == Decision.ALLOW for event in result.audit_events)
    assert result.audit_events[-1].context.purpose == Purpose.AUTHORIZED_FINANCIAL_TRANSACTION
    assert result.audit_events[-1].execution_status == ExecutionStatus.SUCCEEDED


def test_denied_workflow_records_read_and_denial_audit_events(demo_runtime):
    agent, policies, _, gateway = demo_runtime
    activate_financial_policy(policies)

    result = agent.run(UNSAFE_EMAIL_REQUEST)

    assert result.audit_events == tuple(gateway.audit_events)
    assert [event.context.tool_name for event in result.audit_events] == [
        "customer_db.read",
        "gmail.send",
    ]
    assert result.audit_events[0].decision.decision == Decision.ALLOW
    assert result.audit_events[1].decision.decision == Decision.DENY
