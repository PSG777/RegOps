import hashlib
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from google.api_core.client_options import ClientOptions
from pydantic import BaseModel, ConfigDict, Field

from regops.models import AgentManifest
from regops.registry import (
    AgentNotFoundError,
    AgentRegistry,
    AgentVersionNotFoundError,
)


DomainModel = TypeVar("DomainModel", bound=BaseModel)


def firestore_document_id(value: str) -> str:
    """Return a stable Firestore-safe ID without exposing the source resource name."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CloudInfrastructureError(RuntimeError):
    pass


class ContentScreeningError(ValueError):
    pass


class LifecycleEventType(StrEnum):
    REGULATION_ANALYZED = "REGULATION_ANALYZED"
    IMPACT_ANALYZED = "IMPACT_ANALYZED"
    POLICY_VALIDATED = "POLICY_VALIDATED"
    TEST_SUITE_CREATED = "TEST_SUITE_CREATED"
    EVALUATION_COMPLETED = "EVALUATION_COMPLETED"
    POLICY_APPROVED = "POLICY_APPROVED"
    POLICY_DEPLOYED = "POLICY_DEPLOYED"
    POLICY_ROLLED_BACK = "POLICY_ROLLED_BACK"
    RUNTIME_ACTION_DENIED = "RUNTIME_ACTION_DENIED"


class LifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    event_type: LifecycleEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    case_id: str
    requirement_id: str | None = None
    policy_id: str | None = None
    policy_version: int | None = None
    deployment_id: str | None = None
    agent_id: str | None = None
    audit_event_id: str | None = None


class ArtifactRepository(Protocol):
    def save(self, collection: str, artifact_id: str, artifact: BaseModel) -> None: ...
    def load(
        self, collection: str, artifact_id: str, model_type: type[DomainModel]
    ) -> DomainModel: ...
    def exists(self, collection: str, artifact_id: str) -> bool: ...


class InMemoryArtifactRepository:
    def __init__(self) -> None:
        self._documents: dict[tuple[str, str], dict[str, Any]] = {}

    def save(self, collection: str, artifact_id: str, artifact: BaseModel) -> None:
        self._documents[(collection, artifact_id)] = artifact.model_dump(mode="json")

    def load(
        self, collection: str, artifact_id: str, model_type: type[DomainModel]
    ) -> DomainModel:
        try:
            document = self._documents[(collection, artifact_id)]
        except KeyError as error:
            raise LookupError(f"Artifact not found: {collection}/{artifact_id}") from error
        return model_type.model_validate(document)

    def exists(self, collection: str, artifact_id: str) -> bool:
        return (collection, artifact_id) in self._documents


class FirestoreArtifactRepository:
    """Firestore adapter; every loaded document crosses Pydantic validation."""

    def __init__(self, project: str, database: str, *, client: Any | None = None) -> None:
        if client is None:
            from google.cloud import firestore

            client = firestore.Client(project=project, database=database)
        self._client = client

    def save(self, collection: str, artifact_id: str, artifact: BaseModel) -> None:
        self._client.collection(collection).document(artifact_id).set(
            artifact.model_dump(mode="json")
        )

    def load(
        self, collection: str, artifact_id: str, model_type: type[DomainModel]
    ) -> DomainModel:
        snapshot = self._client.collection(collection).document(artifact_id).get()
        if not snapshot.exists:
            raise LookupError(f"Artifact not found: {collection}/{artifact_id}")
        return model_type.model_validate(snapshot.to_dict())

    def exists(self, collection: str, artifact_id: str) -> bool:
        return bool(
            self._client.collection(collection).document(artifact_id).get().exists
        )

    def readiness(self) -> bool:
        next(iter(self._client.collections()), None)
        return True


class EventBus(Protocol):
    def publish(self, event: LifecycleEvent) -> None: ...


class InMemoryEventBus:
    def __init__(self) -> None:
        self.events: list[LifecycleEvent] = []

    def publish(self, event: LifecycleEvent) -> None:
        self.events.append(event.model_copy(deep=True))


class GooglePubSubEventBus:
    def __init__(self, project: str, topic: str, *, publisher: Any | None = None) -> None:
        if publisher is None:
            from google.cloud import pubsub_v1

            publisher = pubsub_v1.PublisherClient()
        self._publisher = publisher
        self.topic_path = publisher.topic_path(project, topic)

    def publish(self, event: LifecycleEvent) -> None:
        payload = event.model_dump_json().encode("utf-8")
        self._publisher.publish(
            self.topic_path,
            payload,
            event_id=event.event_id,
            event_type=event.event_type.value,
        ).result(timeout=10)

    def readiness(self) -> bool:
        self._publisher.get_topic(request={"topic": self.topic_path})
        return True


class ScreeningStatus(StrEnum):
    PASSED = "PASSED"
    BLOCKED = "BLOCKED"


class ScreeningResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: ScreeningStatus
    provider: str
    findings: tuple[str, ...] = ()


class ContentScreeningService(Protocol):
    def screen(self, text: str) -> ScreeningResult: ...


class LocalContentScreeningService:
    def screen(self, text: str) -> ScreeningResult:
        if not text.strip():
            raise ContentScreeningError("Content to screen must not be empty.")
        return ScreeningResult(status=ScreeningStatus.PASSED, provider="local")


class GoogleModelArmorScreeningService:
    def __init__(
        self,
        project: str,
        location: str,
        template: str,
        *,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from google.cloud import modelarmor_v1

            client = modelarmor_v1.ModelArmorClient(
                transport="rest",
                client_options=ClientOptions(
                    api_endpoint=f"modelarmor.{location}.rep.googleapis.com"
                ),
            )
        self._client = client
        self._name = f"projects/{project}/locations/{location}/templates/{template}"

    def screen(self, text: str) -> ScreeningResult:
        if not text.strip():
            raise ContentScreeningError("Content to screen must not be empty.")
        from google.cloud import modelarmor_v1

        response = self._client.sanitize_user_prompt(
            request=modelarmor_v1.SanitizeUserPromptRequest(
                name=self._name,
                user_prompt_data=modelarmor_v1.DataItem(text=text),
            )
        )
        result = response.sanitization_result
        state = getattr(result.filter_match_state, "name", str(result.filter_match_state))
        blocked = state == "MATCH_FOUND"
        findings = tuple(
            sorted(
                key
                for key, value in result.filter_results.items()
                if "MATCH_FOUND" in str(value)
            )
        )
        screening = ScreeningResult(
            status=ScreeningStatus.BLOCKED if blocked else ScreeningStatus.PASSED,
            provider="google-model-armor",
            findings=findings,
        )
        if blocked:
            raise ContentScreeningError(
                "Regulation input was blocked by content screening: "
                + (", ".join(findings) or "configured filter")
            )
        return screening


class GoogleCloudAgentRegistry(AgentRegistry):
    """Cloud discovery plus Firestore-owned trusted RegOps manifest metadata."""

    def __init__(
        self,
        project: str,
        location: str,
        metadata_repository: ArtifactRepository,
        *,
        client: Any | None = None,
    ) -> None:
        if client is None:
            from google.cloud import agentregistry_v1

            client = agentregistry_v1.AgentRegistryClient()
        self._client = client
        self._parent = f"projects/{project}/locations/{location}"
        self._metadata = metadata_repository

    def readiness(self) -> bool:
        next(iter(self._client.list_agents(parent=self._parent)), None)
        return True

    def remote_agents(self) -> tuple[Any, ...]:
        return tuple(self._client.list_agents(parent=self._parent))

    def list_agents(self) -> tuple[AgentManifest, ...]:
        manifests = []
        for remote in self._client.list_agents(parent=self._parent):
            resource_name = str(remote.name)
            manifest = self._metadata.load(
                "agent_manifests", firestore_document_id(resource_name), AgentManifest
            )
            remote_identity = (
                str(getattr(remote, "agent_id", "")),
                str(getattr(remote, "display_name", "")),
                str(getattr(remote, "version", "")),
            )
            local_identity = (manifest.agent_id, manifest.name, manifest.version)
            if remote_identity != local_identity:
                raise CloudInfrastructureError(
                    f"Agent Registry identity does not match trusted metadata for {resource_name}."
                )
            manifests.append(manifest)
        return tuple(manifests)

    def get_agent(self, agent_id: str, version: str | None = None) -> AgentManifest:
        matches = [item for item in self.list_agents() if item.agent_id == agent_id]
        if not matches:
            raise AgentNotFoundError(f"Agent is not registered: {agent_id}")
        if version is None:
            return max(matches, key=lambda item: item.version)
        for manifest in matches:
            if manifest.version == version:
                return manifest
        raise AgentVersionNotFoundError(
            f"Agent version is not registered: {agent_id}@{version}"
        )

    def get_latest_agent(self, agent_id: str) -> AgentManifest:
        return self.get_agent(agent_id)

    def register_agent(self, manifest: AgentManifest) -> None:
        raise CloudInfrastructureError(
            "Cloud agents are bootstrapped explicitly through Agent Registry tooling."
        )

    def register_version(self, manifest: AgentManifest) -> None:
        self.register_agent(manifest)


def configure_cloud_logging() -> None:
    try:
        from google.cloud import logging as cloud_logging

        cloud_logging.Client().setup_logging()
    except Exception as error:
        raise CloudInfrastructureError("Cloud Logging initialization failed.") from error


class InfrastructureStatus(BaseModel):
    environment: str
    firestore: str
    pubsub: str
    agent_registry: str
    model_armor: str
    vertex: str
    runtime: str
    registry_source: str
    input_screening: str


def local_infrastructure_status() -> InfrastructureStatus:
    return InfrastructureStatus(
        environment="local",
        firestore="in-memory",
        pubsub="in-memory",
        agent_registry="ready",
        model_armor="local",
        vertex="configured-on-demand",
        runtime="local",
        registry_source="InMemoryAgentRegistry",
        input_screening="PASSED",
    )
