import pytest

from regops import (
    AgentManifest,
    AgentNotFoundError,
    FakeToolRegistry,
    InMemoryAgentRegistry,
    InvocationMetadata,
    PolicyRegistry,
    RuntimeGateway,
    build_local_agent_registry,
)
from regops.models import DataClassification, Environment, Purpose


def test_all_enterprise_agents_are_registered_and_retrievable():
    registry = build_local_agent_registry()

    manifests = registry.list_agents()

    assert {manifest.agent_id for manifest in manifests} == {
        "refund-agent",
        "support-agent",
        "sales-agent",
    }
    assert registry.get_agent("refund-agent", "1.0.0").name == "RefundAgent"
    assert registry.get_agent("support-agent").allowed_tools == frozenset(
        {"customer_db.read", "gmail.send"}
    )
    assert registry.get_agent("sales-agent").allowed_tools == frozenset(
        {"gmail.send"}
    )


def test_new_version_becomes_latest_without_overwriting_previous_version():
    registry = build_local_agent_registry()
    original = registry.get_agent("refund-agent", "1.0.0")
    updated = original.model_copy(
        update={"version": "1.1.0", "allowed_tools": frozenset({"stripe.refund"})}
    )

    registry.register_version(updated)

    assert registry.get_latest_agent("refund-agent") == updated
    assert registry.get_agent("refund-agent") == updated
    assert registry.get_agent("refund-agent", "1.0.0") == original
    assert len(registry.list_agents()) == 4


def test_gateway_uses_registered_manifest_permissions():
    registry = InMemoryAgentRegistry()
    registry.register_agent(
        AgentManifest(
            agent_id="restricted-agent",
            name="CallerClaimsDoNotMatter",
            version="1.0.0",
            allowed_tools=frozenset({"gmail.send"}),
            data_access=frozenset({DataClassification.CUSTOMER_RECORD}),
            owner="security-team",
            environment=Environment.PRODUCTION,
        )
    )
    tools = FakeToolRegistry()
    gateway = RuntimeGateway(PolicyRegistry(), tools, registry)

    with pytest.raises(PermissionError):
        gateway.invoke(
            "restricted-agent",
            "1.0.0",
            "stripe.refund",
            {"amount_cents": 5000},
            InvocationMetadata(
                data_classifications=frozenset({DataClassification.BANK_ACCOUNT}),
                purpose=Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
            ),
        )

    assert tools.resolve("stripe.refund").executions == []


def test_unregistered_agent_cannot_invoke_tool():
    registry = build_local_agent_registry()
    tools = FakeToolRegistry()
    gateway = RuntimeGateway(PolicyRegistry(), tools, registry)

    with pytest.raises(AgentNotFoundError):
        gateway.invoke(
            "unknown-agent",
            "1.0.0",
            "gmail.send",
            {"body": "hello"},
            InvocationMetadata(
                data_classifications=frozenset(),
                purpose=Purpose.CUSTOMER_SUPPORT,
            ),
        )

    assert tools.resolve("gmail.send").executions == []


def test_registered_agent_cannot_use_tool_absent_from_manifest():
    registry = build_local_agent_registry()
    tools = FakeToolRegistry()
    gateway = RuntimeGateway(PolicyRegistry(), tools, registry)

    with pytest.raises(PermissionError):
        gateway.invoke(
            "sales-agent",
            "1.0.0",
            "customer_db.read",
            {"customer_id": "demo-customer"},
            InvocationMetadata(
                data_classifications=frozenset({DataClassification.CUSTOMER_RECORD}),
                purpose=Purpose.CUSTOMER_SUPPORT,
            ),
        )

    assert tools.resolve("customer_db.read").executions == []
