from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from regops.api import create_app
from regops.application import ApplicationServices
from regops.cloud import (
    ContentScreeningError,
    GoogleCloudAgentRegistry,
    GooglePubSubEventBus,
    InMemoryArtifactRepository,
    InMemoryEventBus,
    InfrastructureStatus,
    LifecycleEvent,
    LifecycleEventType,
    LocalContentScreeningService,
    firestore_document_id,
)
from regops.config import RegOpsConfiguration, RegOpsEnvironment, load_regops_configuration
from regops.demo_state import DemoState
from regops.models import AgentManifest, Regulation
from regops.registry import build_local_agent_registry


CLOUD_VARIABLES = (
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "REGOPS_FIRESTORE_DATABASE",
    "REGOPS_PUBSUB_TOPIC",
    "REGOPS_MODEL_ARMOR_LOCATION",
    "REGOPS_MODEL_ARMOR_TEMPLATE",
    "REGOPS_AGENT_REGISTRY_LOCATION",
)


def set_cloud_environment(monkeypatch):
    monkeypatch.setenv("REGOPS_ENV", "cloud")
    for name in CLOUD_VARIABLES:
        monkeypatch.setenv(name, "test-value")


def test_cloud_configuration_requires_every_dependency(monkeypatch):
    set_cloud_environment(monkeypatch)
    monkeypatch.delenv("REGOPS_PUBSUB_TOPIC")

    with pytest.raises(RuntimeError, match="REGOPS_PUBSUB_TOPIC"):
        load_regops_configuration()


def test_local_profile_needs_no_cloud_configuration(monkeypatch):
    monkeypatch.setenv("REGOPS_ENV", "local")
    for name in CLOUD_VARIABLES:
        monkeypatch.delenv(name, raising=False)

    assert load_regops_configuration().environment == RegOpsEnvironment.LOCAL


def test_repository_revalidates_loaded_documents():
    repository = InMemoryArtifactRepository()
    regulation = DemoState().regulation
    repository.save("regulations", regulation.regulation_id, regulation)

    assert repository.load("regulations", regulation.regulation_id, Regulation) == regulation
    repository._documents[("regulations", regulation.regulation_id)]["unexpected"] = True
    with pytest.raises(ValueError):
        repository.load("regulations", regulation.regulation_id, Regulation)


def test_pubsub_event_contains_only_stable_identifiers():
    published = {}

    class Future:
        def result(self, timeout):
            published["timeout"] = timeout

    class Publisher:
        def topic_path(self, project, topic):
            return f"projects/{project}/topics/{topic}"

        def publish(self, topic, payload, **attributes):
            published.update(topic=topic, payload=payload, attributes=attributes)
            return Future()

    bus = GooglePubSubEventBus("project", "topic", publisher=Publisher())
    bus.publish(
        LifecycleEvent(
            event_id="stable-id",
            event_type=LifecycleEventType.POLICY_DEPLOYED,
            case_id="case",
            policy_id="policy",
            policy_version=1,
        )
    )

    assert b"stable-id" in published["payload"]
    assert b"bank_account" not in published["payload"].lower()
    assert published["attributes"]["event_type"] == "POLICY_DEPLOYED"


def test_local_screening_is_offline_and_rejects_empty_input():
    screening = LocalContentScreeningService()
    assert screening.screen("regulation text").status == "PASSED"
    with pytest.raises(ContentScreeningError):
        screening.screen("  ")


def test_cloud_agent_registry_validates_firestore_metadata():
    repository = InMemoryArtifactRepository()
    manifest = build_local_agent_registry().get_agent("refund-agent")
    remote = SimpleNamespace(
        name="projects/p/locations/l/agents/refund",
        agent_id=manifest.agent_id,
        display_name=manifest.name,
        version=manifest.version,
    )
    repository.save(
        "agent_manifests", firestore_document_id(remote.name), manifest
    )

    class Client:
        def list_agents(self, parent):
            return [remote]

    registry = GoogleCloudAgentRegistry("p", "l", repository, client=Client())
    loaded = registry.get_agent("refund-agent")

    assert isinstance(loaded, AgentManifest)
    assert loaded == manifest


def test_cloud_app_loads_snapshot_without_reset_or_generation():
    seeded = DemoState()
    repository = InMemoryArtifactRepository()
    repository.save("demo_cases", seeded.case_id, seeded.snapshot())
    infrastructure = InfrastructureStatus(
        environment="cloud",
        firestore="ready",
        pubsub="ready",
        agent_registry="ready",
        model_armor="ready",
        vertex="configured",
        runtime="cloud-run",
        registry_source="Google Cloud Agent Registry",
        input_screening="PASSED",
    )
    services = ApplicationServices(
        artifacts=repository,
        events=InMemoryEventBus(),
        screening=LocalContentScreeningService(),
        agents=build_local_agent_registry(),
        infrastructure=infrastructure,
    )
    config = RegOpsConfiguration(
        environment=RegOpsEnvironment.CLOUD,
        frontend_origin="https://frontend.example",
    )

    app = create_app(config, services=services)
    client = TestClient(app)

    assert client.get("/api/health").json()["infrastructure"]["firestore"] == "ready"
    assert client.get("/api/demo/dashboard").json()["deployment"]["status"] == "ACTIVE"
    assert client.post("/api/demo/runtime/unsafe-email").json()["decision"] == "DENY"
    with pytest.raises(RuntimeError, match="explicit bootstrap"):
        app.state.demo_state.reset()
