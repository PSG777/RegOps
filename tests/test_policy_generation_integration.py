import asyncio
import os

import pytest

from regops.config import gemini_configuration_available, load_local_environment
from regops.impact import ImpactAnalyzer
from regops.models import PolicyStatus
from regops.policy_generation import PolicyGenerationAgent
from regops.registry import build_local_agent_registry
from regops.regulations import SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
from regops.tools import FakeToolRegistry


load_local_environment()
RUN_LIVE_TEST = (
    os.getenv("RUN_GEMINI_INTEGRATION_TESTS") == "1"
    and gemini_configuration_available()
)


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_LIVE_TEST,
    reason="Enable live Gemini tests and configure Vertex AI or an API key to run",
)
def test_gemini_generates_validated_candidate_policy():
    impact_report = ImpactAnalyzer(
        build_local_agent_registry(), FakeToolRegistry()
    ).analyze(SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT)

    candidate = asyncio.run(
        PolicyGenerationAgent().generate(
            SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT, impact_report
        )
    )

    assert candidate.status == PolicyStatus.VALIDATED
    assert candidate.affected_agent_ids == ("refund-agent",)
