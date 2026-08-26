import asyncio
import os

import pytest

from regops.config import load_local_environment
from regops.impact import ImpactAnalyzer
from regops.policy_generation import PolicyGenerationAgent
from regops.registry import build_local_agent_registry
from regops.regulations import SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
from regops.test_generation import TestGenerationAgent as GenerationAgent
from regops.tools import FakeToolRegistry


load_local_environment()
RUN_LIVE_TEST = os.getenv("RUN_GEMINI_INTEGRATION_TESTS") == "1" and bool(
    os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
)


@pytest.mark.integration
@pytest.mark.skipif(
    not RUN_LIVE_TEST,
    reason="Set RUN_GEMINI_INTEGRATION_TESTS=1 and a Gemini API key to run",
)
def test_gemini_generates_validated_compliance_test_suite():
    requirement = SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
    agents = build_local_agent_registry()
    tools = FakeToolRegistry()
    impact_report = ImpactAnalyzer(agents, tools).analyze(requirement)
    candidate = asyncio.run(
        PolicyGenerationAgent().generate(requirement, impact_report)
    )

    suite = asyncio.run(
        GenerationAgent(agents, tools).generate(
            requirement, candidate, impact_report
        )
    )

    assert suite.test_cases
    assert len({test.category for test in suite.test_cases}) >= 2
    assert all(test.agent_id == "refund-agent" for test in suite.test_cases)
