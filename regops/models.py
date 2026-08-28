from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class ActionType(StrEnum):
    READ = "READ"
    TRANSMIT = "TRANSMIT"


class DataClassification(StrEnum):
    BANK_ACCOUNT = "BANK_ACCOUNT"
    CUSTOMER_RECORD = "CUSTOMER_RECORD"


class DestinationType(StrEnum):
    INTERNAL_DATABASE = "INTERNAL_DATABASE"
    EMAIL_PROVIDER = "EMAIL_PROVIDER"
    APPROVED_PAYMENT_PROCESSOR = "APPROVED_PAYMENT_PROCESSOR"


class Purpose(StrEnum):
    CUSTOMER_SUPPORT = "CUSTOMER_SUPPORT"
    CUSTOMER_REQUESTED_EXTERNAL_EMAIL = "CUSTOMER_REQUESTED_EXTERNAL_EMAIL"
    AUTHORIZED_FINANCIAL_TRANSACTION = "AUTHORIZED_FINANCIAL_TRANSACTION"


class Decision(StrEnum):
    ALLOW = "ALLOW"
    DENY = "DENY"


class ExecutionStatus(StrEnum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class Environment(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"


class ImpactStatus(StrEnum):
    AFFECTED = "AFFECTED"
    NOT_AFFECTED = "NOT_AFFECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class RiskSeverity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PolicyStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    INVALID = "INVALID"


class PolicyEffect(StrEnum):
    DENY = "DENY"


class PolicyOverlapStatus(StrEnum):
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"
    NO_CONFLICT = "NO_CONFLICT"


class TestCategory(StrEnum):
    PROHIBITED = "PROHIBITED"
    LEGITIMATE = "LEGITIMATE"
    ADVERSARIAL = "ADVERSARIAL"
    EDGE_CASE = "EDGE_CASE"


class TestCaseStatus(StrEnum):
    READY = "READY"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    REJECTED = "REJECTED"


class SimulationMode(StrEnum):
    BASELINE = "BASELINE"
    CANDIDATE = "CANDIDATE"


class TestExecutionStatus(StrEnum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    ERROR = "ERROR"


class ReplayChange(StrEnum):
    UNCHANGED = "UNCHANGED"
    NEWLY_DENIED = "NEWLY_DENIED"
    NEWLY_ALLOWED = "NEWLY_ALLOWED"


class PolicyEvaluationStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"


class ReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_CHANGES = "REQUEST_CHANGES"


class ReviewerRole(StrEnum):
    COMPLIANCE_OFFICER = "COMPLIANCE_OFFICER"
    ADMIN = "ADMIN"
    VIEWER = "VIEWER"


class DeploymentStatus(StrEnum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    DEPLOYED = "DEPLOYED"
    ACTIVE = "ACTIVE"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"


class DeploymentOperatorRole(StrEnum):
    ADMIN = "ADMIN"
    DEPLOYMENT_OPERATOR = "DEPLOYMENT_OPERATOR"
    VIEWER = "VIEWER"


class AgentManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    name: str
    version: str
    allowed_tools: frozenset[str]
    data_access: frozenset[DataClassification]
    owner: str
    environment: Environment


class ActionContext(BaseModel):
    agent_id: str
    agent_version: str
    tool_name: str
    action_type: ActionType
    data_classifications: frozenset[DataClassification]
    destination_type: DestinationType
    purpose: Purpose


class InvocationMetadata(BaseModel):
    """Invocation-specific facts supplied at the gateway boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    data_classifications: frozenset[DataClassification]
    purpose: Purpose


class Policy(BaseModel):
    policy_id: str
    version: int = Field(default=1, ge=1)
    description: str
    active: bool = False
    protected_classification: DataClassification
    governed_action: ActionType
    allowed_destination: DestinationType
    required_purpose: Purpose


class PolicyDecision(BaseModel):
    decision: Decision
    policy_id: str | None = None
    reason: str


class AuditEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    context: ActionContext
    decision: PolicyDecision
    tool_executed: bool
    execution_status: ExecutionStatus
    error_type: str | None = None


class Regulation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    regulation_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_text: str = Field(min_length=1)
    version: str = Field(min_length=1)


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(min_length=1)
    regulation_id: str = Field(min_length=1)
    source_excerpt: str = Field(min_length=1, max_length=500)
    data_classification: DataClassification
    governed_action: ActionType
    allowed_destination: DestinationType
    required_purpose: Purpose
    confidence: float = Field(ge=0, le=1)


class CapabilityPath(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    data_classification: DataClassification
    agent_id: str
    agent_version: str
    tool_name: str
    action_type: ActionType
    destination_type: DestinationType


class AgentImpact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    agent_id: str
    agent_name: str
    agent_version: str
    status: ImpactStatus
    severity: RiskSeverity
    relevant_data_classifications: frozenset[DataClassification]
    risky_tools: tuple[str, ...]
    capability_paths: tuple[CapabilityPath, ...]
    reasons: tuple[str, ...]


class ImpactReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str
    analyzed_agent_count: int = Field(ge=0)
    affected_agents: tuple[str, ...]
    not_affected_agents: tuple[str, ...]
    needs_review_agents: tuple[str, ...]
    agent_impacts: tuple[AgentImpact, ...]


class CandidatePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: str = Field(min_length=1)
    version: int = Field(ge=1)
    requirement_id: str = Field(min_length=1)
    regulation_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    effect: PolicyEffect
    protected_classification: DataClassification
    governed_action: ActionType
    allowed_destination: DestinationType
    required_purpose: Purpose
    status: PolicyStatus
    affected_agent_ids: tuple[str, ...]


class PolicyOverlapResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: PolicyOverlapStatus
    matching_policy_ids: tuple[str, ...]
    reasons: tuple[str, ...]


class ComplianceTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    test_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    category: TestCategory
    agent_id: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    scenario: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    data_classifications: frozenset[DataClassification]
    purpose: Purpose
    expected_decision: Decision
    expected_reason: str = Field(min_length=1)
    tags: tuple[str, ...]
    status: TestCaseStatus = TestCaseStatus.READY


class ComplianceScenarioIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_index: int = Field(ge=0)
    status: TestCaseStatus
    category: TestCategory | None = None
    agent_id: str | None = None
    tool_name: str | None = None
    scenario: str | None = None
    reason: str = Field(min_length=1)


class ComplianceCoverageSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_test_count: int = Field(ge=0)
    prohibited_count: int = Field(ge=0)
    legitimate_count: int = Field(ge=0)
    adversarial_count: int = Field(ge=0)
    edge_case_count: int = Field(ge=0)
    affected_agents_covered: tuple[str, ...]
    risky_tools_covered: tuple[str, ...]
    known_destinations_covered: tuple[DestinationType, ...]


class ComplianceTestSuite(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    suite_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    candidate_policy_version: int = Field(ge=1)
    affected_agent_ids: tuple[str, ...]
    test_cases: tuple[ComplianceTestCase, ...]
    needs_review: tuple[ComplianceScenarioIssue, ...]
    rejected: tuple[ComplianceScenarioIssue, ...]
    coverage: ComplianceCoverageSummary


class SimulationTestResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    test_id: str = Field(min_length=1)
    category: TestCategory
    agent_id: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    expected_decision: Decision
    actual_decision: Decision
    execution_status: TestExecutionStatus
    tool_executed: bool
    policy_id_used: str | None = None
    reason: str = Field(min_length=1)


class SimulationRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    simulation_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    test_suite_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: int = Field(ge=1)
    mode: SimulationMode
    total_ready_tests: int = Field(ge=0)
    passed_tests: int = Field(ge=0)
    failed_tests: int = Field(ge=0)
    needs_review_tests: int = Field(ge=0)
    error_tests: int = Field(ge=0)
    individual_results: tuple[SimulationTestResult, ...]


class HistoricalAction(BaseModel):
    """Normalized action facts for policy replay; never contains tool payloads."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    data_classifications: frozenset[DataClassification]
    purpose: Purpose
    original_decision: Decision | None = None
    original_execution_status: ExecutionStatus | None = None


class HistoricalReplayResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action_id: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    agent_version: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    baseline_decision: Decision
    candidate_decision: Decision
    change: ReplayChange
    baseline_policy_id: str | None = None
    candidate_policy_id: str | None = None


class HistoricalReplaySummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    total_actions: int = Field(ge=0)
    unchanged_actions: int = Field(ge=0)
    newly_denied_actions: int = Field(ge=0)
    newly_allowed_actions: int = Field(ge=0)
    decision_change_rate: float = Field(ge=0, le=1)
    affected_agent_ids: tuple[str, ...]
    affected_tool_names: tuple[str, ...]
    individual_results: tuple[HistoricalReplayResult, ...]


class PolicyEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluation_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: int = Field(ge=1)
    policy_fingerprint: str = Field(min_length=64, max_length=64)
    requirement_id: str = Field(min_length=1)
    test_suite_id: str = Field(min_length=1)
    baseline_run: SimulationRun
    candidate_run: SimulationRun
    compliance_score_before: float = Field(ge=0, le=1)
    compliance_score_after: float = Field(ge=0, le=1)
    utility_score_before: float = Field(ge=0, le=1)
    utility_score_after: float = Field(ge=0, le=1)
    adversarial_score_before: float = Field(ge=0, le=1)
    adversarial_score_after: float = Field(ge=0, le=1)
    overall_correctness_before: float = Field(ge=0, le=1)
    overall_correctness_after: float = Field(ge=0, le=1)
    critical_violations_before: int = Field(ge=0)
    critical_violation_count: int = Field(ge=0)
    historical_replay_summary: HistoricalReplaySummary
    blast_radius: float = Field(ge=0, le=1)
    final_evaluation_status: PolicyEvaluationStatus


class ReviewerIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reviewer_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    role: ReviewerRole


class ReviewEligibility(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    eligible: bool
    policy_id: str = Field(min_length=1)
    policy_version: int = Field(ge=1)
    policy_fingerprint: str = Field(min_length=64, max_length=64)
    evaluation_id: str = Field(min_length=1)
    reasons: tuple[str, ...]


class PolicyReviewRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    review_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: int = Field(ge=1)
    policy_fingerprint: str = Field(min_length=64, max_length=64)
    evaluation_id: str = Field(min_length=1)
    reviewer: ReviewerIdentity
    decision: ReviewDecision
    comment: str = Field(min_length=1)
    reviewed_at: datetime
    previous_status: PolicyStatus
    resulting_status: PolicyStatus


class PolicyReviewOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate: CandidatePolicy
    record: PolicyReviewRecord


class DeploymentOperatorIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    operator_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    role: DeploymentOperatorRole


class PolicyDeployment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    deployment_id: str = Field(min_length=1)
    policy_id: str = Field(min_length=1)
    policy_version: int = Field(ge=1)
    policy_fingerprint: str = Field(min_length=64, max_length=64)
    approval_review_id: str = Field(min_length=1)
    environment: Environment
    operator: DeploymentOperatorIdentity
    status: DeploymentStatus
    deployed_at: datetime | None = None
    activated_at: datetime | None = None
    rolled_back_at: datetime | None = None
    previous_active_policy_id: str | None = None
    previous_active_policy_version: int | None = Field(default=None, ge=1)
    failure_reason: str | None = None
