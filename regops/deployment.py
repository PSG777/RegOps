from collections.abc import Callable
from datetime import datetime, timezone
from uuid import uuid4

from regops.approval import policy_fingerprint
from regops.models import (
    CandidatePolicy,
    DeploymentOperatorIdentity,
    DeploymentOperatorRole,
    DeploymentStatus,
    Environment,
    PolicyDeployment,
    PolicyReviewRecord,
    PolicyStatus,
    ReviewDecision,
)
from regops.policy import PolicyRegistry
from regops.policy_generation import candidate_to_runtime_policy


class DeploymentError(ValueError):
    pass


class DeploymentValidationError(DeploymentError):
    pass


class DeploymentAuthorizationError(DeploymentError):
    pass


class RollbackError(DeploymentError):
    pass


DeploymentIdFactory = Callable[[], str]
Clock = Callable[[], datetime]


class DeploymentController:
    AUTHORIZED_ROLES = frozenset(
        {DeploymentOperatorRole.ADMIN, DeploymentOperatorRole.DEPLOYMENT_OPERATOR}
    )

    def __init__(
        self,
        policy_registry: PolicyRegistry,
        *,
        deployment_id_factory: DeploymentIdFactory | None = None,
        clock: Clock | None = None,
    ) -> None:
        self._policy_registry = policy_registry
        self._deployment_id_factory = deployment_id_factory or (
            lambda: f"DEPLOY-{uuid4()}"
        )
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._records: list[PolicyDeployment] = []

    @property
    def deployment_records(self) -> tuple[PolicyDeployment, ...]:
        return tuple(record.model_copy(deep=True) for record in self._records)

    def deploy(
        self,
        candidate: CandidatePolicy,
        approval: PolicyReviewRecord,
        environment: Environment,
        operator: DeploymentOperatorIdentity,
    ) -> PolicyDeployment:
        deployment = PolicyDeployment(
            deployment_id=self._new_deployment_id(),
            policy_id=candidate.policy_id,
            policy_version=candidate.version,
            policy_fingerprint=policy_fingerprint(candidate),
            approval_review_id=approval.review_id,
            environment=environment,
            operator=operator,
            status=DeploymentStatus.PENDING,
        )
        self._records.append(deployment)
        try:
            self._authorize(operator)
            self._replace_record(deployment.model_copy(update={"status": DeploymentStatus.VALIDATING}))
            self._validate(candidate, approval)
            runtime_policy = candidate_to_runtime_policy(candidate)
            now = self._now()
            previous = self._policy_registry.register_and_activate(runtime_policy)
            deployment = deployment.model_copy(
                update={
                    "status": DeploymentStatus.ACTIVE,
                    "deployed_at": now,
                    "activated_at": now,
                    "previous_active_policy_id": previous.policy_id if previous else None,
                    "previous_active_policy_version": previous.version if previous else None,
                }
            )
            self._replace_record(deployment)
            return deployment.model_copy(deep=True)
        except Exception as error:
            failed = deployment.model_copy(
                update={
                    "status": DeploymentStatus.FAILED,
                    "failure_reason": str(error) or type(error).__name__,
                }
            )
            self._replace_record(failed)
            if isinstance(error, DeploymentError):
                raise
            raise DeploymentError("Runtime policy deployment failed.") from error

    def rollback(
        self,
        deployment_id: str,
        operator: DeploymentOperatorIdentity,
    ) -> PolicyDeployment:
        self._authorize(operator)
        index, deployment = self._find_record(deployment_id)
        if deployment.status != DeploymentStatus.ACTIVE:
            raise RollbackError("Only an ACTIVE deployment can be rolled back.")
        if (
            deployment.previous_active_policy_id is None
            or deployment.previous_active_policy_version is None
        ):
            raise RollbackError("Deployment has no previous active policy version.")
        if deployment.previous_active_policy_id != deployment.policy_id:
            raise RollbackError("Previous active policy does not match this policy ID.")
        try:
            self._policy_registry.restore_active_version(
                deployment.policy_id,
                deployment.policy_version,
                deployment.previous_active_policy_version,
            )
        except ValueError as error:
            raise RollbackError(str(error)) from error
        rolled_back = deployment.model_copy(
            update={
                "status": DeploymentStatus.ROLLED_BACK,
                "rolled_back_at": self._now(),
            }
        )
        self._records[index] = rolled_back
        return rolled_back.model_copy(deep=True)

    @staticmethod
    def _validate(candidate: CandidatePolicy, approval: PolicyReviewRecord) -> None:
        issues: list[str] = []
        if candidate.status != PolicyStatus.APPROVED:
            issues.append("CandidatePolicy status must be APPROVED.")
        if approval.decision != ReviewDecision.APPROVE:
            issues.append("Approval record decision must be APPROVE.")
        if approval.resulting_status != PolicyStatus.APPROVED:
            issues.append("Approval record resulting status must be APPROVED.")
        if approval.policy_id != candidate.policy_id:
            issues.append("Approval policy ID does not match the candidate.")
        if approval.policy_version != candidate.version:
            issues.append("Approval policy version does not match the candidate.")
        if approval.policy_fingerprint != policy_fingerprint(candidate):
            issues.append("Approval fingerprint does not match the candidate artifact.")
        if issues:
            raise DeploymentValidationError("; ".join(issues))

    def _authorize(self, operator: DeploymentOperatorIdentity) -> None:
        if operator.role not in self.AUTHORIZED_ROLES:
            raise DeploymentAuthorizationError(
                f"Operator role {operator.role.value} cannot deploy or roll back policies."
            )

    def _new_deployment_id(self) -> str:
        deployment_id = self._deployment_id_factory()
        if not deployment_id or any(
            item.deployment_id == deployment_id for item in self._records
        ):
            raise DeploymentError("Deployment ID must be non-empty and unique.")
        return deployment_id

    def _now(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise DeploymentError("Deployment timestamps must be timezone-aware.")
        return timestamp

    def _replace_record(self, deployment: PolicyDeployment) -> None:
        index, _ = self._find_record(deployment.deployment_id)
        self._records[index] = deployment

    def _find_record(self, deployment_id: str) -> tuple[int, PolicyDeployment]:
        for index, deployment in enumerate(self._records):
            if deployment.deployment_id == deployment_id:
                return index, deployment
        raise RollbackError(f"Deployment is not recorded: {deployment_id}.")
