import os

import pytest


pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("RUN_GCP_INTEGRATION_TESTS") != "1",
    reason="Set RUN_GCP_INTEGRATION_TESTS=1 for explicit cloud checks.",
)
def test_configured_cloud_services_are_ready():
    from regops.application import build_cloud_services
    from regops.config import load_regops_configuration

    services = build_cloud_services(load_regops_configuration())

    assert services.infrastructure.firestore == "ready"
    assert services.infrastructure.pubsub == "ready"
    assert services.infrastructure.agent_registry == "ready"
