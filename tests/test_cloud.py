from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from regops.api import create_app
from regops.application import ApplicationServices
from regops.cloud import (
    CloudAgentBinding,
    CloudInfrastructureError,
    ContentScreeningError,
    GoogleCloudAgentRegistry,
    GooglePubSubEventBus,
    InMemoryArtifactRepository,
    InMemoryEventBus,
    InfrastructureStatus,
    LifecycleEvent,
    LifecycleEventType,
    LocalContentScreeningService,
    cloud_agent_binding_id,
    firestore_document_id,
)
from regops.cloud_bootstrap import bootstrap_cloud_agent_bindings
from regops.config import RegOpsConfiguration, RegOpsEnvironment, load_regops_configuration
from regops.demo_state import DemoState
from regops.models import AgentManifest, Regulation
from regops.registry import build_local_agent_registry, local_enterprise_manifests


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


def remote_agent(manifest, *, suffix="managed", agent_id=None, version=None):
    return SimpleNamespace(
        name=f"projects/p/locations/l/agents/{manifest.agent_id}-{suffix}",
        agent_id=agent_id or f"urn:agent:google:{manifest.agent_id}:{suffix}",
        display_name=manifest.name,
        version=version,
    )


def demo_remote_agents(*, refund_version=None):
    return tuple(
        remote_agent(
            manifest,
            version=refund_version if manifest.agent_id == "refund-agent" else "",
        )
        for manifest in local_enterprise_manifests()
    )


def test_cloud_agent_registry_uses_binding_and_retains_logical_identity():
    repository = InMemoryArtifactRepository()
    manifest = build_local_agent_registry().get_agent("refund-agent")
    remote = remote_agent(manifest, version="")
    binding = CloudAgentBinding(
        cloud_agent_name=remote.name,
        cloud_agent_id=remote.agent_id,
        cloud_display_name=remote.display_name,
        cloud_version=None,
        regops_agent_id=manifest.agent_id,
        regops_agent_version=manifest.version,
    )
    repository.save(
        "agent_manifests", firestore_document_id(remote.name), manifest
    )
    repository.save(
        "cloud_agent_bindings",
        cloud_agent_binding_id(manifest.agent_id, manifest.version),
        binding,
    )

    class Client:
        def list_agents(self, parent):
            return [remote]

    registry = GoogleCloudAgentRegistry("p", "l", repository, client=Client())
    loaded = registry.get_agent("refund-agent")

    assert isinstance(loaded, AgentManifest)
    assert loaded == manifest
    assert loaded.agent_id == "refund-agent"
    assert loaded.version == "1.0.0"
    assert remote.agent_id != loaded.agent_id
    assert remote.version == ""


def test_initial_display_name_discovery_creates_validated_bindings():
    repository = InMemoryArtifactRepository()

    bindings = bootstrap_cloud_agent_bindings(demo_remote_agents(), repository)

    assert len(bindings) == 3
    refund = next(item for item in bindings if item.regops_agent_id == "refund-agent")
    assert refund.cloud_agent_id.startswith("urn:agent:google:")
    assert refund.cloud_version is None
    assert repository.exists(
        "cloud_agent_bindings", cloud_agent_binding_id("refund-agent", "1.0.0")
    )


def test_initial_discovery_reports_missing_display_name_without_writes():
    repository = InMemoryArtifactRepository()
    remotes = tuple(
        item for item in demo_remote_agents() if item.display_name != "SalesAgent"
    )

    with pytest.raises(CloudInfrastructureError, match="SalesAgent"):
        bootstrap_cloud_agent_bindings(remotes, repository)

    assert repository.list("cloud_agent_bindings", CloudAgentBinding) == ()


def test_initial_discovery_rejects_duplicate_display_names():
    repository = InMemoryArtifactRepository()
    remotes = demo_remote_agents()
    duplicate = remote_agent(local_enterprise_manifests()[0], suffix="duplicate")

    with pytest.raises(CloudInfrastructureError, match="Ambiguous.*RefundAgent"):
        bootstrap_cloud_agent_bindings(remotes + (duplicate,), repository)


@pytest.mark.parametrize(
    ("field", "message"),
    (("name", "resource name changed"), ("agent_id", "Agent ID changed")),
)
def test_existing_binding_rejects_changed_managed_identity(field, message):
    repository = InMemoryArtifactRepository()
    remotes = list(demo_remote_agents())
    bootstrap_cloud_agent_bindings(tuple(remotes), repository)
    refund = remotes[0]
    setattr(refund, field, getattr(refund, field) + "-changed")

    with pytest.raises(CloudInfrastructureError, match=message):
        bootstrap_cloud_agent_bindings(tuple(remotes), repository)


def test_existing_binding_does_not_rely_on_mutable_display_name():
    repository = InMemoryArtifactRepository()
    remotes = list(demo_remote_agents())
    bootstrap_cloud_agent_bindings(tuple(remotes), repository)
    remotes[0].display_name = "Renamed in cloud console"

    bindings = bootstrap_cloud_agent_bindings(tuple(remotes), repository)

    assert next(
        item for item in bindings if item.regops_agent_id == "refund-agent"
    ).cloud_display_name == "RefundAgent"


def test_binding_and_manifest_documents_are_strictly_revalidated():
    repository = InMemoryArtifactRepository()
    bootstrap_cloud_agent_bindings(demo_remote_agents(), repository)
    binding_id = cloud_agent_binding_id("refund-agent", "1.0.0")
    repository._documents[("cloud_agent_bindings", binding_id)]["untrusted"] = True

    with pytest.raises(ValueError):
        repository.load("cloud_agent_bindings", binding_id, CloudAgentBinding)

    manifest = local_enterprise_manifests()[0]
    remote = demo_remote_agents()[0]
    manifest_id = firestore_document_id(remote.name)
    repository._documents[("agent_manifests", manifest_id)]["version"] = None
    with pytest.raises(ValueError):
        repository.load("agent_manifests", manifest_id, AgentManifest)


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
