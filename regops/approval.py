import hashlib
import json
from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from regops.models import (
    CandidatePolicy,
    PolicyEvaluationReport,
    PolicyEvaluationStatus,
    PolicyReviewOutcome,
    PolicyReviewRecord,
    PolicyStatus,
    ReviewDecision,
    ReviewEligibility,
    ReviewerIdentity,
    ReviewerRole,
)


class PolicyApprovalError(ValueError):
    pass


class PolicyLifecycleError(PolicyApprovalError):
    pass


class ReviewEligibilityError(PolicyApprovalError):
    def __init__(self, eligibility: ReviewEligibility) -> None:
        self.eligibility = eligibility
        super().__init__("; ".join(eligibility.reasons))


class PolicyArtifactMismatchError(PolicyApprovalError):
    pass


class ReviewerAuthorizationError(PolicyApprovalError):
    pass


class PolicyLifecycle:
    VALID_TRANSITIONS = {
        PolicyStatus.CANDIDATE: frozenset({PolicyStatus.VALIDATED}),
        PolicyStatus.VALIDATED: frozenset({PolicyStatus.READY_FOR_REVIEW}),
        PolicyStatus.READY_FOR_REVIEW: frozenset(
            {
                PolicyStatus.APPROVED,
                PolicyStatus.REJECTED,
                PolicyStatus.CHANGES_REQUESTED,
            }
        ),
    }

    def transition(
        self, candidate: CandidatePolicy, resulting_status: PolicyStatus
    ) -> CandidatePolicy:
        allowed = self.VALID_TRANSITIONS.get(candidate.status, frozenset())
        if resulting_status not in allowed:
            raise PolicyLifecycleError(
                f"Invalid policy lifecycle transition: "
                f"{candidate.status.value} -> {resulting_status.value}."
            )
        return candidate.model_copy(update={"status": resulting_status}, deep=True)


def policy_fingerprint(candidate: CandidatePolicy) -> str:
    """Hash canonical policy semantics, excluding mutable lifecycle status."""

    payload = {
        "affected_agent_ids": sorted(candidate.affected_agent_ids),
        "allowed_destination": candidate.allowed_destination.value,
        "description": candidate.description,
        "effect": candidate.effect.value,
        "governed_action": candidate.governed_action.value,
        "policy_id": candidate.policy_id,
        "protected_classification": candidate.protected_classification.value,
        "regulation_id": candidate.regulation_id,
        "required_purpose": candidate.required_purpose.value,
        "requirement_id": candidate.requirement_id,
        "version": candidate.version,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


ReviewIdFactory = Callable[[], str]
Clock = Callable[[], datetime]


class PolicyApprovalService:
    AUTHORIZED_ROLES = frozenset(
        {ReviewerRole.COMPLIANCE_OFFICER, ReviewerRole.ADMIN}
    )

    def __init__(
        self,
        *,
        lifecycle: PolicyLifecycle | None = None,
        review_id_factory: ReviewIdFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._lifecycle = lifecycle or PolicyLifecycle()
        self._review_id_factory = review_id_factory or (
            lambda: f"REVIEW-{uuid4()}"
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._review_records: list[PolicyReviewRecord] = []

    @property
    def review_records(self) -> tuple[PolicyReviewRecord, ...]:
        return tuple(record.model_copy(deep=True) for record in self._review_records)

    def assess_review_eligibility(
        self,
        candidate: CandidatePolicy,
        evaluation: PolicyEvaluationReport,
    ) -> ReviewEligibility:
        fingerprint = policy_fingerprint(candidate)
        reasons: list[str] = []
        if candidate.status != PolicyStatus.VALIDATED:
            reasons.append("CandidatePolicy status must be VALIDATED.")
        reasons.extend(self._evaluation_issues(candidate, evaluation, fingerprint))
        return ReviewEligibility(
            eligible=not reasons,
            policy_id=candidate.policy_id,
            policy_version=candidate.version,
            policy_fingerprint=fingerprint,
            evaluation_id=evaluation.evaluation_id,
            reasons=tuple(reasons),
        )

    def prepare_for_review(
        self,
        candidate: CandidatePolicy,
        evaluation: PolicyEvaluationReport,
    ) -> CandidatePolicy:
        eligibility = self.assess_review_eligibility(candidate, evaluation)
        if not eligibility.eligible:
            raise ReviewEligibilityError(eligibility)
        return self._lifecycle.transition(
            candidate, PolicyStatus.READY_FOR_REVIEW
        )

    def submit_decision(
        self,
        candidate: CandidatePolicy,
        evaluation: PolicyEvaluationReport,
        reviewer: ReviewerIdentity,
        decision: ReviewDecision,
        comment: str,
    ) -> PolicyReviewOutcome:
        resulting_status = self._resulting_status(decision)
        reviewed_candidate = self._lifecycle.transition(
            candidate, resulting_status
        )
        if reviewer.role not in self.AUTHORIZED_ROLES:
            raise ReviewerAuthorizationError(
                f"Reviewer role {reviewer.role.value} cannot submit decisions."
            )

        fingerprint = policy_fingerprint(candidate)
        if any(
            record.policy_id == candidate.policy_id
            and record.policy_version == candidate.version
            and record.policy_fingerprint == fingerprint
            and record.evaluation_id == evaluation.evaluation_id
            for record in self._review_records
        ):
            raise PolicyLifecycleError(
                "This evaluated policy artifact already has a review decision."
            )
        issues = self._evaluation_issues(candidate, evaluation, fingerprint)
        if issues:
            raise PolicyArtifactMismatchError("; ".join(issues))
        if not comment.strip():
            raise PolicyApprovalError("A review comment is required.")

        reviewed_at = self._clock()
        if reviewed_at.tzinfo is None or reviewed_at.utcoffset() is None:
            raise PolicyApprovalError("Review timestamps must be timezone-aware.")
        review_id = self._review_id_factory()
        if not review_id or any(
            record.review_id == review_id for record in self._review_records
        ):
            raise PolicyApprovalError("Review ID must be non-empty and unique.")

        record = PolicyReviewRecord(
            review_id=review_id,
            policy_id=candidate.policy_id,
            policy_version=candidate.version,
            policy_fingerprint=fingerprint,
            evaluation_id=evaluation.evaluation_id,
            reviewer=reviewer,
            decision=decision,
            comment=comment.strip(),
            reviewed_at=reviewed_at,
            previous_status=candidate.status,
            resulting_status=reviewed_candidate.status,
        )
        self._review_records.append(record)
        return PolicyReviewOutcome(
            candidate=reviewed_candidate,
            record=record,
        )

    @staticmethod
    def _evaluation_issues(
        candidate: CandidatePolicy,
        evaluation: PolicyEvaluationReport,
        fingerprint: str,
    ) -> list[str]:
        issues: list[str] = []
        if evaluation.policy_id != candidate.policy_id:
            issues.append("Evaluation policy ID does not match the candidate.")
        if evaluation.policy_version != candidate.version:
            issues.append("Evaluation policy version does not match the candidate.")
        if evaluation.requirement_id != candidate.requirement_id:
            issues.append("Evaluation requirement does not match the candidate.")
        if evaluation.policy_fingerprint != fingerprint:
            issues.append("Evaluation fingerprint does not match the candidate artifact.")
        if evaluation.final_evaluation_status != PolicyEvaluationStatus.PASS:
            issues.append("Policy evaluation result must be PASS.")
        if evaluation.critical_violation_count != 0:
            issues.append("Policy evaluation must have zero critical violations.")
        return issues

    @staticmethod
    def _resulting_status(decision: ReviewDecision) -> PolicyStatus:
        return {
            ReviewDecision.APPROVE: PolicyStatus.APPROVED,
            ReviewDecision.REJECT: PolicyStatus.REJECTED,
            ReviewDecision.REQUEST_CHANGES: PolicyStatus.CHANGES_REQUESTED,
        }[decision]
