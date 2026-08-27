import pytest
from pydantic import ValidationError

from regops.models import (
    ActionType,
    CandidatePolicy,
    ComplianceCoverageSummary,
    ComplianceScenarioIssue,
    ComplianceTestCase,
    ComplianceTestSuite,
    DataClassification,
    Decision,
    DestinationType,
    HistoricalAction,
    PolicyEffect,
    PolicyEvaluationStatus,
    PolicyStatus,
    Purpose,
    SimulationMode,
    TestCaseStatus as CaseStatus,
    TestCategory as Category,
    TestExecutionStatus as ResultStatus,
)
from regops.policy import PolicyRegistry
from regops.policy_generation import candidate_to_runtime_policy
from regops.registry import build_local_agent_registry
from regops.replay import HistoricalReplayEngine, synthetic_historical_actions
from regops.simulation import (
    PolicyEvaluator,
    PolicyScorer,
    SimulationHarness,
    SimulationScores,
)
from regops.tools import FakeTool, FakeToolRegistry, ToolMetadata


def validated_candidate() -> CandidatePolicy:
    return CandidatePolicy(
        policy_id="FIN-POL-001",
        version=1,
        requirement_id="FIN-REQ-001",
        regulation_id="FIN-REG-001",
        description="Restrict financial account transmissions.",
        effect=PolicyEffect.DENY,
        protected_classification=DataClassification.BANK_ACCOUNT,
        governed_action=ActionType.TRANSMIT,
        allowed_destination=DestinationType.APPROVED_PAYMENT_PROCESSOR,
        required_purpose=Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
        status=PolicyStatus.VALIDATED,
        affected_agent_ids=("refund-agent",),
    )


def make_test_case(
    test_id: str,
    category: Category,
    tool_name: str,
    classifications: set[DataClassification],
    purpose: Purpose,
    expected: Decision,
    *,
    status: CaseStatus = CaseStatus.READY,
) -> ComplianceTestCase:
    return ComplianceTestCase(
        test_id=test_id,
        requirement_id="FIN-REQ-001",
        policy_id="FIN-POL-001",
        category=category,
        agent_id="refund-agent",
        agent_version="1.0.0",
        scenario=f"Scenario for {test_id}",
        tool_name=tool_name,
        data_classifications=frozenset(classifications),
        purpose=purpose,
        expected_decision=expected,
        expected_reason="Derived from the validated candidate.",
        tags=("offline",),
        status=status,
    )


def compliance_suite(*, include_review: bool = True) -> ComplianceTestSuite:
    cases = (
        make_test_case(
            "TEST-001",
            Category.PROHIBITED,
            "gmail.send",
            {DataClassification.BANK_ACCOUNT},
            Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL,
            Decision.DENY,
        ),
        make_test_case(
            "TEST-002",
            Category.LEGITIMATE,
            "stripe.refund",
            {DataClassification.BANK_ACCOUNT},
            Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
            Decision.ALLOW,
        ),
        make_test_case(
            "TEST-003",
            Category.ADVERSARIAL,
            "gmail.send",
            {DataClassification.BANK_ACCOUNT},
            Purpose.CUSTOMER_SUPPORT,
            Decision.DENY,
        ),
        make_test_case(
            "TEST-004",
            Category.EDGE_CASE,
            "gmail.send",
            {DataClassification.CUSTOMER_RECORD},
            Purpose.CUSTOMER_SUPPORT,
            Decision.ALLOW,
        ),
    )
    review = (
        ComplianceScenarioIssue(
            source_index=4,
            status=CaseStatus.NEEDS_REVIEW,
            category=Category.EDGE_CASE,
            agent_id="refund-agent",
            tool_name="unknown.send",
            scenario="Unknown tool proposal",
            reason="Trusted tool metadata is unavailable.",
        ),
    ) if include_review else ()
    return ComplianceTestSuite(
        suite_id="SUITE-FIN-POL-001-v1",
        requirement_id="FIN-REQ-001",
        policy_id="FIN-POL-001",
        candidate_policy_version=1,
        affected_agent_ids=("refund-agent",),
        test_cases=cases,
        needs_review=review,
        rejected=(),
        coverage=ComplianceCoverageSummary(
            total_test_count=4,
            prohibited_count=1,
            legitimate_count=1,
            adversarial_count=1,
            edge_case_count=1,
            affected_agents_covered=("refund-agent",),
            risky_tools_covered=("gmail.send",),
            known_destinations_covered=(
                DestinationType.APPROVED_PAYMENT_PROCESSOR,
                DestinationType.EMAIL_PROVIDER,
            ),
        ),
    )


def result_by_id(run, test_id):
    return next(item for item in run.individual_results if item.test_id == test_id)


@pytest.fixture
def evaluated():
    registry = PolicyRegistry()
    evaluator = PolicyEvaluator(build_local_agent_registry(), registry)
    candidate = validated_candidate()
    report = evaluator.evaluate(
        candidate, compliance_suite(), synthetic_historical_actions()
    )
    return report, evaluator, registry, candidate


def test_baseline_and_candidate_compare_identical_ready_inputs(evaluated):
    report, _, _, _ = evaluated
    baseline = report.baseline_run
    candidate = report.candidate_run

    assert [item.test_id for item in baseline.individual_results] == [
        item.test_id for item in candidate.individual_results
    ]
    assert baseline.total_ready_tests == candidate.total_ready_tests == 4
    assert baseline.needs_review_tests == candidate.needs_review_tests == 1


def test_unsafe_gmail_is_allowed_at_baseline_and_denied_by_candidate(evaluated):
    report, _, _, _ = evaluated
    baseline = result_by_id(report.baseline_run, "TEST-001")
    candidate = result_by_id(report.candidate_run, "TEST-001")

    assert baseline.actual_decision == Decision.ALLOW
    assert baseline.execution_status == ResultStatus.FAILED
    assert baseline.tool_executed is True
    assert candidate.actual_decision == Decision.DENY
    assert candidate.execution_status == ResultStatus.PASSED
    assert candidate.tool_executed is False
    assert candidate.policy_id_used == "FIN-POL-001"


def test_legitimate_refund_remains_allowed(evaluated):
    report, _, _, _ = evaluated
    refund = result_by_id(report.candidate_run, "TEST-002")

    assert refund.actual_decision == Decision.ALLOW
    assert refund.execution_status == ResultStatus.PASSED
    assert refund.tool_executed is True


def test_fake_tool_state_is_isolated_between_runs(evaluated):
    _, evaluator, _, _ = evaluated
    sandboxes = evaluator.simulation.last_tool_registries
    baseline_tools = sandboxes[SimulationMode.BASELINE]
    candidate_tools = sandboxes[SimulationMode.CANDIDATE]

    assert baseline_tools is not candidate_tools
    assert len(baseline_tools.resolve("gmail.send").executions) == 3
    assert len(candidate_tools.resolve("gmail.send").executions) == 1
    assert len(baseline_tools.resolve("stripe.refund").executions) == 1
    assert len(candidate_tools.resolve("stripe.refund").executions) == 1


def test_needs_review_case_is_not_executed_as_a_trusted_simulation():
    suite = compliance_suite(include_review=False)
    review_case = make_test_case(
        "TEST-REVIEW",
        Category.EDGE_CASE,
        "gmail.send",
        {DataClassification.CUSTOMER_RECORD},
        Purpose.CUSTOMER_SUPPORT,
        Decision.ALLOW,
        status=CaseStatus.NEEDS_REVIEW,
    )
    suite = suite.model_copy(
        update={"test_cases": (*suite.test_cases, review_case)}
    )
    harness = SimulationHarness(
        build_local_agent_registry(), PolicyRegistry()
    )

    run = harness.run(suite, validated_candidate(), SimulationMode.BASELINE)

    assert run.total_ready_tests == 4
    assert run.needs_review_tests == 1
    assert "TEST-REVIEW" not in {item.test_id for item in run.individual_results}
    assert len(
        harness.last_tool_registries[SimulationMode.BASELINE]
        .resolve("gmail.send")
        .executions
    ) == 3


def test_scores_and_critical_violations_are_deterministic(evaluated):
    report, _, _, _ = evaluated

    assert report.compliance_score_before == 0.0
    assert report.compliance_score_after == 1.0
    assert report.utility_score_before == report.utility_score_after == 1.0
    assert report.adversarial_score_before == 0.0
    assert report.adversarial_score_after == 1.0
    assert report.overall_correctness_before == 0.5
    assert report.overall_correctness_after == 1.0
    assert report.critical_violations_before == 2
    assert report.critical_violation_count == 0
    assert report.final_evaluation_status == PolicyEvaluationStatus.PASS


def test_candidate_evaluation_thresholds_are_explicit_and_deterministic():
    passing = SimulationScores(1.0, 0.9, 0.0, 0.5, 0)

    assert PolicyScorer.evaluate_candidate(passing) == PolicyEvaluationStatus.PASS
    assert PolicyScorer.evaluate_candidate(
        SimulationScores(0.99, 1.0, 1.0, 1.0, 0)
    ) == PolicyEvaluationStatus.FAIL
    assert PolicyScorer.evaluate_candidate(
        SimulationScores(1.0, 0.89, 1.0, 1.0, 0)
    ) == PolicyEvaluationStatus.FAIL
    assert PolicyScorer.evaluate_candidate(
        SimulationScores(1.0, 1.0, 1.0, 1.0, 1)
    ) == PolicyEvaluationStatus.FAIL


def test_simulation_does_not_mutate_authoritative_or_candidate_state(evaluated):
    report, _, registry, candidate = evaluated

    assert registry.active_policies() == ()
    assert candidate.status == PolicyStatus.VALIDATED
    assert report.policy_id == candidate.policy_id
    assert report.requirement_id == candidate.requirement_id
    assert report.test_suite_id == compliance_suite().suite_id


def test_historical_replay_counts_blast_radius_without_executing_tools():
    tools = FakeToolRegistry()
    candidate_policy = candidate_to_runtime_policy(validated_candidate())
    summary = HistoricalReplayEngine(
        build_local_agent_registry(), tools
    ).replay(
        synthetic_historical_actions(),
        (),
        (candidate_policy,),
    )

    assert summary.total_actions == 40
    assert summary.unchanged_actions == 37
    assert summary.newly_denied_actions == 3
    assert summary.newly_allowed_actions == 0
    assert summary.decision_change_rate == pytest.approx(0.075)
    assert summary.affected_agent_ids == ("refund-agent",)
    assert summary.affected_tool_names == ("gmail.send",)
    assert all(
        tools.resolve(name).executions == []
        for name in ("customer_db.read", "gmail.send", "stripe.refund")
    )


def test_historical_action_cannot_override_trusted_tool_metadata():
    with pytest.raises(ValidationError):
        HistoricalAction.model_validate(
            {
                "action_id": "SPOOF-001",
                "agent_id": "refund-agent",
                "agent_version": "1.0.0",
                "tool_name": "gmail.send",
                "data_classifications": ["BANK_ACCOUNT"],
                "purpose": "AUTHORIZED_FINANCIAL_TRANSACTION",
                "destination_type": "APPROVED_PAYMENT_PROCESSOR",
            }
        )

    action = HistoricalAction(
        action_id="TRUSTED-001",
        agent_id="refund-agent",
        agent_version="1.0.0",
        tool_name="gmail.send",
        data_classifications=frozenset({DataClassification.BANK_ACCOUNT}),
        purpose=Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
    )
    summary = HistoricalReplayEngine(
        build_local_agent_registry(), FakeToolRegistry()
    ).replay((action,), (), (candidate_to_runtime_policy(validated_candidate()),))
    assert summary.individual_results[0].candidate_decision == Decision.DENY


def test_allowed_fake_tool_failure_is_an_error_not_a_policy_failure():
    created = []

    def failing_tools():
        tools = FakeToolRegistry()
        tools.register(
            FakeTool(
                name="stripe.refund",
                metadata=ToolMetadata(
                    action_type=ActionType.TRANSMIT,
                    destination_type=DestinationType.APPROVED_PAYMENT_PROCESSOR,
                ),
                result_factory=lambda _: (_ for _ in ()).throw(
                    RuntimeError("provider unavailable")
                ),
            )
        )
        created.append(tools)
        return tools

    harness = SimulationHarness(
        build_local_agent_registry(),
        PolicyRegistry(),
        tool_registry_factory=failing_tools,
    )
    run = harness.run(
        compliance_suite(include_review=False),
        validated_candidate(),
        SimulationMode.CANDIDATE,
    )
    refund = result_by_id(run, "TEST-002")

    assert refund.actual_decision == Decision.ALLOW
    assert refund.execution_status == ResultStatus.ERROR
    assert refund.tool_executed is True
    assert run.error_tests == 1
    assert PolicyScorer.score(run).utility == 1.0
    assert len(created[0].resolve("stripe.refund").executions) == 1
