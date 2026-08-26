from regops.impact import ImpactAnalyzer
from regops.models import (
    AgentManifest,
    DataClassification,
    Environment,
    ImpactStatus,
    RiskSeverity,
)
from regops.registry import InMemoryAgentRegistry, build_local_agent_registry
from regops.regulations import SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
from regops.tools import FakeToolRegistry


def impact_by_agent(report, agent_id):
    return next(
        impact for impact in report.agent_impacts if impact.agent_id == agent_id
    )


def test_financial_requirement_finds_only_refund_agent_affected():
    report = ImpactAnalyzer(
        build_local_agent_registry(), FakeToolRegistry()
    ).analyze(SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT)

    refund = impact_by_agent(report, "refund-agent")
    support = impact_by_agent(report, "support-agent")
    sales = impact_by_agent(report, "sales-agent")

    assert report.analyzed_agent_count == 3
    assert report.affected_agents == ("refund-agent@1.0.0",)
    assert set(report.not_affected_agents) == {
        "sales-agent@1.0.0",
        "support-agent@1.0.0",
    }
    assert report.needs_review_agents == ()
    assert refund.status == ImpactStatus.AFFECTED
    assert refund.severity == RiskSeverity.HIGH
    assert support.status == ImpactStatus.NOT_AFFECTED
    assert sales.status == ImpactStatus.NOT_AFFECTED
    assert "cannot access BANK_ACCOUNT" in support.reasons[0]
    assert "cannot access BANK_ACCOUNT" in sales.reasons[0]


def test_gmail_path_is_risky_but_stripe_is_not_a_prohibited_path():
    report = ImpactAnalyzer(
        build_local_agent_registry(), FakeToolRegistry()
    ).analyze(SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT)
    refund = impact_by_agent(report, "refund-agent")

    assert refund.risky_tools == ("gmail.send",)
    assert [path.tool_name for path in refund.capability_paths] == ["gmail.send"]
    gmail_path = refund.capability_paths[0]
    assert gmail_path.data_classification == DataClassification.BANK_ACCOUNT
    assert gmail_path.destination_type.value == "EMAIL_PROVIDER"
    assert "stripe.refund" not in refund.risky_tools
    assert any(
        "stripe.refund" in reason and "evaluated at runtime" in reason
        for reason in refund.reasons
    )


def test_analyzer_derives_impact_without_hard_coded_agent_names():
    registry = InMemoryAgentRegistry()
    registry.register_agent(
        AgentManifest(
            agent_id="payments-processor-47",
            name="ArbitraryPaymentsWorker",
            version="7.2",
            allowed_tools=frozenset({"gmail.send"}),
            data_access=frozenset({DataClassification.BANK_ACCOUNT}),
            owner="payments-team",
            environment=Environment.STAGING,
        )
    )

    report = ImpactAnalyzer(registry, FakeToolRegistry()).analyze(
        SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
    )

    assert report.agent_impacts[0].status == ImpactStatus.AFFECTED
    assert report.agent_impacts[0].capability_paths[0].agent_id == (
        "payments-processor-47"
    )


def test_unknown_tool_metadata_requires_review_instead_of_assuming_safe():
    registry = InMemoryAgentRegistry()
    registry.register_agent(
        AgentManifest(
            agent_id="unknown-tool-agent",
            name="UnknownToolAgent",
            version="1.0",
            allowed_tools=frozenset({"unregistered.transmit"}),
            data_access=frozenset({DataClassification.BANK_ACCOUNT}),
            owner="risk-team",
            environment=Environment.DEVELOPMENT,
        )
    )

    report = ImpactAnalyzer(registry, FakeToolRegistry()).analyze(
        SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
    )
    impact = report.agent_impacts[0]

    assert impact.status == ImpactStatus.NEEDS_REVIEW
    assert impact.severity == RiskSeverity.MEDIUM
    assert "unavailable or incomplete" in impact.reasons[-1]


def test_allowed_destination_still_needs_runtime_purpose_review():
    registry = InMemoryAgentRegistry()
    registry.register_agent(
        AgentManifest(
            agent_id="refund-only-agent",
            name="RefundOnlyAgent",
            version="1.0",
            allowed_tools=frozenset({"stripe.refund"}),
            data_access=frozenset({DataClassification.BANK_ACCOUNT}),
            owner="payments-team",
            environment=Environment.PRODUCTION,
        )
    )

    impact = ImpactAnalyzer(registry, FakeToolRegistry()).analyze(
        SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
    ).agent_impacts[0]

    assert impact.status == ImpactStatus.NEEDS_REVIEW
    assert impact.capability_paths == ()
    assert impact.risky_tools == ()
    assert "invocation purpose" in impact.reasons[-1]
