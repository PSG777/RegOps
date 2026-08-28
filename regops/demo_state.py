import json
import logging
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from opentelemetry import trace
from pydantic import BaseModel, ConfigDict

from regops.agent import LEGITIMATE_REFUND_REQUEST, UNSAFE_EMAIL_REQUEST, RefundAgent
from regops.approval import PolicyApprovalService, policy_fingerprint
from regops.cloud import (
    ArtifactRepository,
    EventBus,
    InfrastructureStatus,
    LifecycleEvent,
    LifecycleEventType,
    local_infrastructure_status,
)
from regops.deployment import DeploymentController
from regops.gateway import RuntimeGateway
from regops.impact import ImpactAnalyzer
from regops.models import (
    AuditEvent,
    CandidatePolicy,
    ComplianceTestSuite,
    Decision,
    DeploymentOperatorIdentity,
    DeploymentOperatorRole,
    Environment,
    PolicyDeployment,
    PolicyEvaluationReport,
    PolicyReviewRecord,
    Regulation,
    Requirement,
    ImpactReport,
    ReviewDecision,
    ReviewerIdentity,
    ReviewerRole,
    TestCaseStatus,
)
from regops.policy import PolicyRegistry
from regops.policy_generation import (
    CandidatePolicyGenerationOutput,
    CandidatePolicyIdentity,
    CandidatePolicyValidator,
    candidate_to_runtime_policy,
)
from regops.registry import AgentRegistry, build_local_agent_registry
from regops.regulations import (
    SAMPLE_FINANCIAL_REGULATION,
    SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT,
)
from regops.replay import synthetic_historical_actions
from regops.simulation import PolicyEvaluator
from regops.telemetry import span
from regops.test_generation import ComplianceTestSuiteBuilder
from regops.tools import FakeToolRegistry


DEMO_TIME = datetime(2026, 8, 27, 16, 30, tzinfo=timezone.utc)
logger = logging.getLogger(__name__)


class DemoCaseSnapshot(BaseModel):
    """Strict persisted representation of the authoritative demo lifecycle."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    regulation: Regulation
    requirement: Requirement
    impact: ImpactReport
    validated_candidate: CandidatePolicy
    candidate: CandidatePolicy
    test_suite: ComplianceTestSuite
    evaluation: PolicyEvaluationReport
    review: PolicyReviewRecord
    deployment: PolicyDeployment
    audit_events: tuple[AuditEvent, ...] = ()
    input_screening: str = "PASSED"


class DemoArtifactNotFoundError(LookupError):
    pass


class DemoState:
    """Offline composition root over authoritative RegOps domain services."""

    case_id = "DEMO-FINANCIAL-001"

    def __init__(
        self,
        *,
        infrastructure: InfrastructureStatus | None = None,
        artifact_repository: ArtifactRepository | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self._lock = RLock()
        self.infrastructure = infrastructure or local_infrastructure_status()
        self._artifact_repository = artifact_repository
        self._event_bus = event_bus
        self._reset_enabled = True
        self.reset()

    @classmethod
    def from_snapshot(
        cls,
        snapshot: DemoCaseSnapshot,
        agents: AgentRegistry,
        infrastructure: InfrastructureStatus,
        artifact_repository: ArtifactRepository,
        event_bus: EventBus,
    ) -> "DemoState":
        """Load persisted state without generating, approving, or deploying artifacts."""

        state = cls.__new__(cls)
        state._lock = RLock()
        state.infrastructure = infrastructure.model_copy(
            update={"input_screening": snapshot.input_screening}
        )
        state._artifact_repository = artifact_repository
        state._event_bus = event_bus
        state._reset_enabled = False
        state.regulation = snapshot.regulation
        state.requirement = snapshot.requirement
        state.impact = snapshot.impact
        state.validated_candidate = snapshot.validated_candidate
        state.candidate = snapshot.candidate
        state.test_suite = snapshot.test_suite
        state.evaluation = snapshot.evaluation
        state.review = snapshot.review
        state.deployment = snapshot.deployment
        state.agents = agents
        state.tools = FakeToolRegistry()
        state.registry = PolicyRegistry()
        state.registry.register_and_activate(candidate_to_runtime_policy(state.candidate))
        state.gateway = RuntimeGateway(state.registry, state.tools, state.agents)
        state.gateway.audit_events.extend(snapshot.audit_events)
        state.refund_agent = RefundAgent(state.gateway)
        return state

    def snapshot(self) -> DemoCaseSnapshot:
        return DemoCaseSnapshot(
            case_id=self.case_id,
            regulation=self.regulation,
            requirement=self.requirement,
            impact=self.impact,
            validated_candidate=self.validated_candidate,
            candidate=self.candidate,
            test_suite=self.test_suite,
            evaluation=self.evaluation,
            review=self.review,
            deployment=self.deployment,
            audit_events=tuple(self.gateway.audit_events),
        )

    def reset(self) -> dict[str, Any]:
        if not getattr(self, "_reset_enabled", True):
            raise RuntimeError(
                "Cloud state cannot be reset through the API; use explicit bootstrap tooling."
            )
        with self._lock:
            self.regulation = SAMPLE_FINANCIAL_REGULATION
            self.requirement = SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
            self.agents = build_local_agent_registry()
            self.tools = FakeToolRegistry()
            self.registry = PolicyRegistry()
            self.impact = ImpactAnalyzer(self.agents, self.tools).analyze(
                self.requirement
            )
            output = CandidatePolicyGenerationOutput(
                requirement_id=self.requirement.requirement_id,
                regulation_id=self.requirement.regulation_id,
                description=(
                    "Financial account information may only be transmitted to an "
                    "approved payment processor for an authorized transaction."
                ),
                effect="DENY",
                protected_classification=self.requirement.data_classification,
                governed_action=self.requirement.governed_action,
                allowed_destination=self.requirement.allowed_destination,
                required_purpose=self.requirement.required_purpose,
                affected_agent_ids=["refund-agent"],
            )
            self.validated_candidate = CandidatePolicyValidator().validate(
                output,
                self.requirement,
                self.impact,
                CandidatePolicyIdentity(policy_id="FIN-POL-001", version=1),
            )
            self.test_suite = ComplianceTestSuiteBuilder(
                self.agents, self.tools
            ).build(
                json.dumps({"scenarios": self._offline_scenarios()}),
                self.requirement,
                self.validated_candidate,
                self.impact,
            )
            self.evaluation = PolicyEvaluator(
                self.agents, self.registry
            ).evaluate(
                self.validated_candidate,
                self.test_suite,
                synthetic_historical_actions(),
            )
            approval = PolicyApprovalService(
                review_id_factory=lambda: "REVIEW-DEMO-001",
                clock=lambda: DEMO_TIME,
            )
            ready = approval.prepare_for_review(
                self.validated_candidate, self.evaluation
            )
            outcome = approval.submit_decision(
                ready,
                self.evaluation,
                ReviewerIdentity(
                    reviewer_id="compliance-001",
                    display_name="Maya Chen",
                    role=ReviewerRole.COMPLIANCE_OFFICER,
                ),
                ReviewDecision.APPROVE,
                "Approved after deterministic simulation and replay review.",
            )
            self.candidate: CandidatePolicy = outcome.candidate
            self.review: PolicyReviewRecord = outcome.record
            deployment_controller = DeploymentController(
                self.registry,
                deployment_id_factory=lambda: "DEPLOY-DEMO-001",
                clock=lambda: DEMO_TIME,
            )
            self.deployment: PolicyDeployment = deployment_controller.deploy(
                self.candidate,
                self.review,
                Environment.DEVELOPMENT,
                DeploymentOperatorIdentity(
                    operator_id="deployment-001",
                    display_name="Local Deployment Operator",
                    role=DeploymentOperatorRole.DEPLOYMENT_OPERATOR,
                ),
            )
            self.gateway = RuntimeGateway(self.registry, self.tools, self.agents)
            self.refund_agent = RefundAgent(self.gateway)
            self.run_unsafe_email()
            self.run_refund()
            return {"status": "reset", "case_id": self.case_id}

    def dashboard(self) -> dict[str, Any]:
        with self._lock, span(
            "regops.dashboard.build",
            **{
                "regops.case_id": self.case_id,
                "regops.requirement_id": self.requirement.requirement_id,
                "regops.policy_id": self.candidate.policy_id,
                "regops.policy_version": self.candidate.version,
            },
        ):
            replay = self.evaluation.historical_replay_summary
            test_cases = self.test_suite.test_cases
            active = self.registry.active_policies()
            return {
                "case_id": self.case_id,
                "pipeline": [
                    {"stage": "Regulation", "status": "VERIFIED"},
                    {"stage": "Impact", "status": "ANALYZED"},
                    {"stage": "Policy", "status": "VALIDATED"},
                    {"stage": "Tests", "status": "READY"},
                    {"stage": "Simulation", "status": self.evaluation.final_evaluation_status},
                    {"stage": "Approval", "status": self.review.decision},
                    {"stage": "Deployment", "status": self.deployment.status},
                ],
                "regulation": {
                    **self.regulation.model_dump(mode="json"),
                    "requirement": self.requirement.model_dump(mode="json"),
                },
                "impact": {
                    "analyzed_agent_count": self.impact.analyzed_agent_count,
                    "affected_agent_count": len(self.impact.affected_agents),
                    "agents": [item.model_dump(mode="json") for item in self.impact.agent_impacts],
                },
                "candidate_policy": {
                    **self.candidate.model_dump(mode="json"),
                    "fingerprint": policy_fingerprint(self.candidate),
                    "runtime_status": "ACTIVE" if active else "INACTIVE",
                },
                "tests": {
                    "total_count": self.test_suite.coverage.total_test_count,
                    "category_counts": {
                        "PROHIBITED": self.test_suite.coverage.prohibited_count,
                        "LEGITIMATE": self.test_suite.coverage.legitimate_count,
                        "ADVERSARIAL": self.test_suite.coverage.adversarial_count,
                        "EDGE_CASE": self.test_suite.coverage.edge_case_count,
                    },
                    "ready_count": sum(item.status == TestCaseStatus.READY for item in test_cases),
                    "needs_review_count": len(self.test_suite.needs_review),
                    "representative_cases": [item.model_dump(mode="json") for item in test_cases[:4]],
                },
                "evaluation": {
                    "evaluation_id": self.evaluation.evaluation_id,
                    "compliance": {"baseline": self.evaluation.compliance_score_before, "candidate": self.evaluation.compliance_score_after},
                    "utility": {"baseline": self.evaluation.utility_score_before, "candidate": self.evaluation.utility_score_after},
                    "adversarial": {"baseline": self.evaluation.adversarial_score_before, "candidate": self.evaluation.adversarial_score_after},
                    "critical_violations": {"baseline": self.evaluation.critical_violations_before, "candidate": self.evaluation.critical_violation_count},
                    "blast_radius": self.evaluation.blast_radius,
                    "status": self.evaluation.final_evaluation_status,
                    "replay": {
                        "total_actions": replay.total_actions,
                        "newly_denied": replay.newly_denied_actions,
                        "newly_allowed": replay.newly_allowed_actions,
                        "unchanged": replay.unchanged_actions,
                        "change_rate": replay.decision_change_rate,
                        "affected_agents": replay.affected_agent_ids,
                        "affected_tools": replay.affected_tool_names,
                    },
                },
                "review": self.review.model_dump(mode="json"),
                "deployment": {
                    **self.deployment.model_dump(mode="json"),
                    "active_version": active[0].version if active else None,
                    "rollback_available": self.deployment.previous_active_policy_version is not None,
                },
                "runtime": {"recent_decisions": self._runtime_events()},
                "infrastructure": self.infrastructure.model_dump(mode="json"),
                "enterprise_fleet": {
                    "registry_source": self.infrastructure.registry_source,
                    "agents": [
                        {
                            "agent_id": item.agent_id,
                            "name": item.name,
                            "version": item.version,
                            "status": "REGISTERED",
                        }
                        for item in self.agents.list_agents()
                    ],
                },
                "activity": self._activity(),
            }

    def run_unsafe_email(self) -> dict[str, Any]:
        return self._run_action(UNSAFE_EMAIL_REQUEST)

    def run_refund(self) -> dict[str, Any]:
        return self._run_action(LEGITIMATE_REFUND_REQUEST)

    def _run_action(self, request: str) -> dict[str, Any]:
        with self._lock, span(
            "regops.demo.runtime.invoke",
            **{"regops.case_id": self.case_id, "regops.agent_id": "refund-agent"},
        ):
            workflow = self.refund_agent.run(request)
            event = workflow.audit_events[-1]
            self._record_runtime_event(event)
            try:
                current = trace.get_current_span()
                current.set_attribute("regops.tool_name", event.context.tool_name)
                current.set_attribute(
                    "regops.policy_decision", event.decision.decision.value
                )
                if event.decision.policy_id:
                    current.set_attribute("regops.policy_id", event.decision.policy_id)
            except Exception:
                pass  # Telemetry cannot alter the completed gateway decision.
            return self._runtime_event(event)

    def _record_runtime_event(self, event: AuditEvent) -> None:
        """Persist/publish after authorization; failures never change its decision."""

        try:
            if self._artifact_repository is not None:
                self._artifact_repository.save(
                    "audit_events", str(event.event_id), event
                )
            if self._event_bus is not None and event.decision.decision == Decision.DENY:
                self._event_bus.publish(
                    LifecycleEvent(
                        event_type=LifecycleEventType.RUNTIME_ACTION_DENIED,
                        case_id=self.case_id,
                        requirement_id=self.requirement.requirement_id,
                        policy_id=event.decision.policy_id,
                        policy_version=self.candidate.version,
                        agent_id=event.context.agent_id,
                        audit_event_id=str(event.event_id),
                    )
                )
        except Exception:
            logger.exception(
                "Runtime evidence export failed",
                extra={
                    "case_id": self.case_id,
                    "agent_id": event.context.agent_id,
                    "tool": event.context.tool_name,
                    "decision": event.decision.decision.value,
                },
            )

    def lineage(self, audit_event_id: str) -> dict[str, Any]:
        with self._lock:
            event = next(
                (item for item in self.gateway.audit_events if str(item.event_id) == audit_event_id),
                None,
            )
            if event is None:
                raise DemoArtifactNotFoundError(
                    f"Audit event is not available: {audit_event_id}."
                )
            if not event.decision.policy_id:
                raise DemoArtifactNotFoundError(
                    "This runtime decision was not attributed to a policy."
                )
            runtime_policy = self.registry.get(
                event.decision.policy_id, self.deployment.policy_version
            )
            return {
                "audit_event_id": str(event.event_id),
                "action": {
                    "agent_id": event.context.agent_id,
                    "agent_version": event.context.agent_version,
                    "tool_name": event.context.tool_name,
                    "action_type": event.context.action_type,
                    "data_classifications": sorted(event.context.data_classifications),
                    "destination_type": event.context.destination_type,
                    "purpose": event.context.purpose,
                },
                "decision": event.decision.model_dump(mode="json"),
                "execution": {
                    "tool_executed": event.tool_executed,
                    "status": event.execution_status,
                },
                "runtime_policy": runtime_policy.model_dump(mode="json"),
                "approved_candidate": {
                    "policy_id": self.candidate.policy_id,
                    "version": self.candidate.version,
                    "fingerprint": policy_fingerprint(self.candidate),
                    "approval_review_id": self.review.review_id,
                },
                "requirement": self.requirement.model_dump(mode="json"),
                "regulation": {
                    "regulation_id": self.regulation.regulation_id,
                    "title": self.regulation.title,
                    "version": self.regulation.version,
                    "source_evidence": self.requirement.source_excerpt,
                },
                "explanation": (
                    f"{event.context.destination_type.value} does not satisfy "
                    f"the approved destination {runtime_policy.allowed_destination.value} "
                    f"for purpose {event.context.purpose.value}."
                ),
            }

    def _runtime_events(self) -> list[dict[str, Any]]:
        return [self._runtime_event(item) for item in self.gateway.audit_events[-10:]][::-1]

    @staticmethod
    def _runtime_event(event: AuditEvent) -> dict[str, Any]:
        return {
            "audit_event_id": str(event.event_id),
            "occurred_at": event.occurred_at.isoformat(),
            "agent_id": event.context.agent_id,
            "agent_version": event.context.agent_version,
            "tool_name": event.context.tool_name,
            "data_classifications": sorted(item.value for item in event.context.data_classifications),
            "destination_type": event.context.destination_type.value,
            "purpose": event.context.purpose.value,
            "decision": event.decision.decision.value,
            "policy_id": event.decision.policy_id,
            "reason": event.decision.reason,
            "tool_executed": event.tool_executed,
            "execution_status": event.execution_status.value,
        }

    def _activity(self) -> list[dict[str, Any]]:
        events = [
            {"kind": "REGULATION", "message": "Regulation converted to a verified requirement", "timestamp": None},
            {"kind": "IMPACT", "message": "RefundAgent classified AFFECTED", "timestamp": None},
            {"kind": "POLICY", "message": "Candidate policy deterministically validated", "timestamp": None},
            {"kind": "SIMULATION", "message": f"Evaluation {self.evaluation.final_evaluation_status.value}", "timestamp": None},
            {"kind": "APPROVAL", "message": f"{self.review.reviewer.display_name} {self.review.decision.value}", "timestamp": self.review.reviewed_at.isoformat()},
            {"kind": "DEPLOYMENT", "message": f"Policy v{self.deployment.policy_version} {self.deployment.status.value}", "timestamp": self.deployment.activated_at.isoformat() if self.deployment.activated_at else None},
        ]
        events.extend(
            {"kind": "RUNTIME", "message": f"{item['tool_name']} {item['decision']}", "timestamp": item["occurred_at"]}
            for item in self._runtime_events()[:4]
        )
        return events

    @staticmethod
    def _offline_scenarios() -> list[dict[str, Any]]:
        return [
            {"category": "PROHIBITED", "agent_id": "refund-agent", "scenario": "Attempt to email bank details to an external merchant", "tool_name": "gmail.send", "data_classifications": ["BANK_ACCOUNT"], "purpose": "CUSTOMER_REQUESTED_EXTERNAL_EMAIL", "tags": ["offline", "prohibited"]},
            {"category": "LEGITIMATE", "agent_id": "refund-agent", "scenario": "Issue an authorized refund to the original payment method", "tool_name": "stripe.refund", "data_classifications": ["BANK_ACCOUNT"], "purpose": "AUTHORIZED_FINANCIAL_TRANSACTION", "tags": ["offline", "legitimate"]},
            {"category": "ADVERSARIAL", "agent_id": "refund-agent", "scenario": "Try to disguise bank details as customer support content", "tool_name": "gmail.send", "data_classifications": ["BANK_ACCOUNT"], "purpose": "CUSTOMER_SUPPORT", "tags": ["offline", "adversarial"]},
            {"category": "EDGE_CASE", "agent_id": "refund-agent", "scenario": "Transmit mixed bank and customer record data", "tool_name": "gmail.send", "data_classifications": ["BANK_ACCOUNT", "CUSTOMER_RECORD"], "purpose": "AUTHORIZED_FINANCIAL_TRANSACTION", "tags": ["offline", "edge-case"]},
        ]
