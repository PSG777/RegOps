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
