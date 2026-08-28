from dataclasses import dataclass

from regops.cloud import (
    ArtifactRepository,
    ContentScreeningService,
    EventBus,
    FirestoreArtifactRepository,
    GoogleCloudAgentRegistry,
    GoogleModelArmorScreeningService,
    GooglePubSubEventBus,
    InfrastructureStatus,
    configure_cloud_logging,
    local_infrastructure_status,
)
from regops.config import RegOpsConfiguration, RegOpsEnvironment
from regops.demo_state import DemoCaseSnapshot, DemoState
from regops.registry import AgentRegistry


@dataclass(frozen=True)
class ApplicationServices:
    artifacts: ArtifactRepository
    events: EventBus
    screening: ContentScreeningService
    agents: AgentRegistry
    infrastructure: InfrastructureStatus


def build_demo_state(
    configuration: RegOpsConfiguration,
    *,
    services: ApplicationServices | None = None,
) -> DemoState:
    if configuration.environment == RegOpsEnvironment.LOCAL:
        return DemoState(infrastructure=local_infrastructure_status())

    cloud_services = services or build_cloud_services(configuration)
    snapshot = cloud_services.artifacts.load(
        "demo_cases", DemoState.case_id, DemoCaseSnapshot
    )
    return DemoState.from_snapshot(
        snapshot,
        cloud_services.agents,
        cloud_services.infrastructure,
        cloud_services.artifacts,
        cloud_services.events,
    )


def build_cloud_services(configuration: RegOpsConfiguration) -> ApplicationServices:
    if configuration.environment != RegOpsEnvironment.CLOUD:
        raise ValueError("Cloud services require REGOPS_ENV=cloud.")
    configure_cloud_logging()
    artifacts = FirestoreArtifactRepository(
        configuration.project or "", configuration.firestore_database or ""
    )
    events = GooglePubSubEventBus(
        configuration.project or "", configuration.pubsub_topic or ""
    )
    screening = GoogleModelArmorScreeningService(
        configuration.project or "",
        configuration.model_armor_location or "",
        configuration.model_armor_template or "",
    )
    agents = GoogleCloudAgentRegistry(
        configuration.project or "",
        configuration.agent_registry_location or "",
        artifacts,
    )
    # Explicit cloud mode fails startup when required infrastructure is unavailable.
    artifacts.readiness()
    events.readiness()
    agents.readiness()
    infrastructure = InfrastructureStatus(
        environment="cloud",
        firestore="ready",
        pubsub="ready",
        agent_registry="ready",
        model_armor="ready",
        vertex="configured",
        runtime="cloud-run",
        registry_source="Google Cloud Agent Registry",
        input_screening="configured",
    )
    return ApplicationServices(
        artifacts=artifacts,
        events=events,
        screening=screening,
        agents=agents,
        infrastructure=infrastructure,
    )
