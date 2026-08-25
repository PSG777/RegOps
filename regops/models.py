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
