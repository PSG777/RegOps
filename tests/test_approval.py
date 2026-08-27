from datetime import datetime, timezone

import pytest

from regops.approval import (
    PolicyApprovalService,
    PolicyArtifactMismatchError,
    PolicyLifecycle,
    PolicyLifecycleError,
    ReviewEligibilityError,
    ReviewerAuthorizationError,
    policy_fingerprint,
)
from regops.gateway import RuntimeGateway
from regops.models import (
    ActionType,
    CandidatePolicy,
    ComplianceCoverageSummary,
    ComplianceTestCase,
    ComplianceTestSuite,
    DataClassification,
    Decision,
    DestinationType,
    InvocationMetadata,
    PolicyEffect,
    PolicyEvaluationStatus,
    PolicyStatus,
    Purpose,
    ReviewDecision,
    ReviewerIdentity,
    ReviewerRole,
    TestCategory as Category,
)
from regops.policy import PolicyRegistry
from regops.registry import build_local_agent_registry
from regops.replay import synthetic_historical_actions
from regops.simulation import PolicyEvaluator
from regops.tools import FakeToolRegistry


FIXED_TIME = datetime(2026, 8, 27, 14, 30, tzinfo=timezone.utc)


def candidate_policy(
    policy_id: str = "FIN-POL-001", version: int = 1
) -> CandidatePolicy:
    return CandidatePolicy(
        policy_id=policy_id,
        version=version,
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


def compliance_suite(candidate: CandidatePolicy) -> ComplianceTestSuite:
    def case(
        test_id: str,
        category: Category,
        tool_name: str,
        purpose: Purpose,
        expected: Decision,
    ) -> ComplianceTestCase:
        return ComplianceTestCase(
            test_id=test_id,
            requirement_id=candidate.requirement_id,
            policy_id=candidate.policy_id,
            category=category,
            agent_id="refund-agent",
            agent_version="1.0.0",
            scenario=f"Approval fixture {test_id}",
            tool_name=tool_name,
            data_classifications=frozenset(
                {DataClassification.BANK_ACCOUNT}
            ),
            purpose=purpose,
            expected_decision=expected,
            expected_reason="Derived from candidate semantics.",
            tags=("approval",),
        )

    tests = (
        case(
            "TEST-001",
            Category.PROHIBITED,
            "gmail.send",
            Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL,
            Decision.DENY,
        ),
        case(
            "TEST-002",
            Category.LEGITIMATE,
            "stripe.refund",
            Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
            Decision.ALLOW,
        ),
    )
    return ComplianceTestSuite(
        suite_id=f"SUITE-{candidate.policy_id}-v{candidate.version}",
        requirement_id=candidate.requirement_id,
        policy_id=candidate.policy_id,
        candidate_policy_version=candidate.version,
        affected_agent_ids=candidate.affected_agent_ids,
        test_cases=tests,
        needs_review=(),
        rejected=(),
        coverage=ComplianceCoverageSummary(
            total_test_count=2,
            prohibited_count=1,
            legitimate_count=1,
            adversarial_count=0,
            edge_case_count=0,
            affected_agents_covered=("refund-agent",),
            risky_tools_covered=("gmail.send",),
            known_destinations_covered=(
                DestinationType.APPROVED_PAYMENT_PROCESSOR,
                DestinationType.EMAIL_PROVIDER,
            ),
        ),
    )


def evaluated_artifacts(
    policy_id: str = "FIN-POL-001", version: int = 1
):
    candidate = candidate_policy(policy_id, version)
    registry = PolicyRegistry()
    report = PolicyEvaluator(
        build_local_agent_registry(), registry
    ).evaluate(
        candidate,
        compliance_suite(candidate),
        synthetic_historical_actions(),
    )
    return candidate, report, registry


def reviewer(role: ReviewerRole = ReviewerRole.COMPLIANCE_OFFICER):
    return ReviewerIdentity(
        reviewer_id="compliance-001",
        display_name="Compliance Officer",
        role=role,
    )


def deterministic_service(review_id: str = "REVIEW-001"):
    return PolicyApprovalService(
        review_id_factory=lambda: review_id,
        clock=lambda: FIXED_TIME,
    )


def test_passing_evaluation_makes_validated_candidate_ready_for_review():
    candidate, report, _ = evaluated_artifacts()
    service = deterministic_service()

    eligibility = service.assess_review_eligibility(candidate, report)
    ready = service.prepare_for_review(candidate, report)

    assert eligibility.eligible is True
    assert eligibility.reasons == ()
    assert eligibility.policy_fingerprint == policy_fingerprint(candidate)
    assert ready.status == PolicyStatus.READY_FOR_REVIEW
    assert candidate.status == PolicyStatus.VALIDATED
    assert policy_fingerprint(ready) == policy_fingerprint(candidate)


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"final_evaluation_status": PolicyEvaluationStatus.FAIL}, "PASS"),
        ({"critical_violation_count": 1}, "zero critical"),
        ({"policy_id": "OTHER-POLICY"}, "policy ID"),
        ({"policy_version": 2}, "policy version"),
    ],
)
def test_ineligible_evaluation_cannot_enter_review(updates, reason):
    candidate, report, _ = evaluated_artifacts()
    report = report.model_copy(update=updates)
    service = deterministic_service()

    eligibility = service.assess_review_eligibility(candidate, report)

    assert eligibility.eligible is False
    assert any(reason in item for item in eligibility.reasons)
    with pytest.raises(ReviewEligibilityError):
        service.prepare_for_review(candidate, report)
    assert candidate.status == PolicyStatus.VALIDATED


def test_changed_policy_fingerprint_invalidates_evaluation_and_review():
    candidate, report, _ = evaluated_artifacts()
    service = deterministic_service()
    ready = service.prepare_for_review(candidate, report)
    changed = ready.model_copy(
        update={"description": "Changed semantics under the same version."}
    )

    eligibility = service.assess_review_eligibility(
        changed.model_copy(update={"status": PolicyStatus.VALIDATED}), report
    )
    assert eligibility.eligible is False
    assert "fingerprint" in eligibility.reasons[0].lower()
    with pytest.raises(PolicyArtifactMismatchError, match="fingerprint"):
        service.submit_decision(
            changed,
            report,
            reviewer(),
            ReviewDecision.APPROVE,
            "Approve evaluated policy.",
        )
    assert service.review_records == ()


@pytest.mark.parametrize(
    ("decision", "expected_status"),
    [
        (ReviewDecision.APPROVE, PolicyStatus.APPROVED),
        (ReviewDecision.REJECT, PolicyStatus.REJECTED),
        (ReviewDecision.REQUEST_CHANGES, PolicyStatus.CHANGES_REQUESTED),
    ],
)
def test_ready_candidate_supports_each_human_decision(decision, expected_status):
    candidate, report, _ = evaluated_artifacts()
    service = deterministic_service()
    ready = service.prepare_for_review(candidate, report)

    outcome = service.submit_decision(
        ready, report, reviewer(), decision, "Explicit human decision."
    )

    assert outcome.candidate.status == expected_status
    assert outcome.record.previous_status == PolicyStatus.READY_FOR_REVIEW
    assert outcome.record.resulting_status == expected_status
    assert outcome.record.decision == decision


def test_lifecycle_rejects_direct_or_repeated_approval():
    candidate, report, _ = evaluated_artifacts()
    service = deterministic_service()

    with pytest.raises(PolicyLifecycleError, match="VALIDATED -> APPROVED"):
        service.submit_decision(
            candidate,
            report,
            reviewer(),
            ReviewDecision.APPROVE,
            "Invalid direct approval.",
        )

    ready = service.prepare_for_review(candidate, report)
    approved = service.submit_decision(
        ready,
        report,
        reviewer(),
        ReviewDecision.APPROVE,
        "First approval.",
    ).candidate
    with pytest.raises(PolicyLifecycleError, match="APPROVED -> APPROVED"):
        service.submit_decision(
            approved,
            report,
            reviewer(),
            ReviewDecision.APPROVE,
            "Duplicate approval.",
        )
    with pytest.raises(PolicyLifecycleError, match="already has"):
        service.submit_decision(
            ready,
            report,
            reviewer(),
            ReviewDecision.REJECT,
            "Stale conflicting decision.",
        )
    assert len(service.review_records) == 1


def test_only_authorized_reviewer_roles_can_submit_decisions():
    candidate, report, _ = evaluated_artifacts()
    ready = deterministic_service().prepare_for_review(candidate, report)
    service = deterministic_service()

    with pytest.raises(ReviewerAuthorizationError):
        service.submit_decision(
            ready,
            report,
            reviewer(ReviewerRole.VIEWER),
            ReviewDecision.APPROVE,
            "Viewer attempt.",
        )

    outcome = service.submit_decision(
        ready,
        report,
        reviewer(ReviewerRole.ADMIN),
        ReviewDecision.APPROVE,
        "Authorized administrator approval.",
    )
    assert outcome.candidate.status == PolicyStatus.APPROVED


def test_review_record_binds_trusted_identity_time_and_exact_artifacts():
    candidate, report, _ = evaluated_artifacts()
    service = deterministic_service("REVIEW-TRUSTED-001")
    ready = service.prepare_for_review(candidate, report)

    record = service.submit_decision(
        ready,
        report,
        reviewer(),
        ReviewDecision.REJECT,
        "Policy requires revision.",
    ).record

    assert record.review_id == "REVIEW-TRUSTED-001"
    assert record.reviewed_at == FIXED_TIME
    assert record.policy_id == candidate.policy_id
    assert record.policy_version == candidate.version
    assert record.policy_fingerprint == report.policy_fingerprint
    assert record.evaluation_id == report.evaluation_id
    assert record.reviewer == reviewer()
    assert record.comment == "Policy requires revision."


def test_approval_does_not_register_activate_or_change_runtime_behavior():
    candidate, report, registry = evaluated_artifacts()
    service = deterministic_service()
    ready = service.prepare_for_review(candidate, report)
    approved = service.submit_decision(
        ready,
        report,
        reviewer(),
        ReviewDecision.APPROVE,
        "Approved for future deployment consideration.",
    ).candidate

    tools = FakeToolRegistry()
    gateway = RuntimeGateway(
        registry, tools, build_local_agent_registry()
    )
    result = gateway.invoke(
        agent_id="refund-agent",
        agent_version="1.0.0",
        tool_name="gmail.send",
        arguments={"to": "merchant@example.com", "body": "Synthetic data"},
        invocation=InvocationMetadata(
            data_classifications=frozenset(
                {DataClassification.BANK_ACCOUNT}
            ),
            purpose=Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL,
        ),
    )

    assert approved.status == PolicyStatus.APPROVED
    assert registry.registered_policies() == ()
    assert registry.active_policies() == ()
    assert result.decision.decision == Decision.ALLOW
    assert len(tools.resolve("gmail.send").executions) == 1


def test_review_records_are_append_only_and_not_overwritten():
    first, first_report, _ = evaluated_artifacts("FIN-POL-001", 1)
    second, second_report, _ = evaluated_artifacts("FIN-POL-001", 2)
    ids = iter(("REVIEW-001", "REVIEW-002"))
    service = PolicyApprovalService(
        review_id_factory=lambda: next(ids),
        clock=lambda: FIXED_TIME,
    )

    first_ready = service.prepare_for_review(first, first_report)
    second_ready = service.prepare_for_review(second, second_report)
    service.submit_decision(
        first_ready,
        first_report,
        reviewer(),
        ReviewDecision.APPROVE,
        "Approve version one.",
    )
    service.submit_decision(
        second_ready,
        second_report,
        reviewer(),
        ReviewDecision.REQUEST_CHANGES,
        "Revise version two.",
    )

    records = service.review_records
    assert [record.review_id for record in records] == [
        "REVIEW-001",
        "REVIEW-002",
    ]
    assert [record.policy_version for record in records] == [1, 2]


def test_candidate_to_validated_transition_is_explicit():
    candidate = candidate_policy().model_copy(
        update={"status": PolicyStatus.CANDIDATE}
    )

    validated = PolicyLifecycle().transition(candidate, PolicyStatus.VALIDATED)

    assert validated.status == PolicyStatus.VALIDATED
    assert candidate.status == PolicyStatus.CANDIDATE
