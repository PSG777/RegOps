import asyncio

from regops.config import load_local_environment, require_gemini_api_key
from regops.impact import ImpactAnalyzer
from regops.models import ImpactStatus
from regops.policy import PolicyRegistry
from regops.policy_generation import PolicyGenerationAgent
from regops.registry import build_local_agent_registry
from regops.regulation_analysis import RegulationAnalysisAgent
from regops.regulations import SAMPLE_FINANCIAL_REGULATION
from regops.test_generation import TestGenerationAgent
from regops.tools import FakeToolRegistry


async def _run() -> None:
    agents = build_local_agent_registry()
    tools = FakeToolRegistry()
    requirement = await RegulationAnalysisAgent().analyze(
        SAMPLE_FINANCIAL_REGULATION
    )
    impact_report = ImpactAnalyzer(agents, tools).analyze(requirement)
    candidate = await PolicyGenerationAgent().generate(requirement, impact_report)
    suite = await TestGenerationAgent(agents, tools).generate(
        requirement, candidate, impact_report
    )

    print("=== COMPLIANCE TEST SUITE ===")
    print(f"Policy: {suite.policy_id} v{suite.candidate_policy_version}")
    print("Affected agents:")
    for agent_id in suite.affected_agent_ids:
        print(f"- {agent_id}")
    print("Coverage:")
    print(f"Prohibited: {suite.coverage.prohibited_count}")
    print(f"Legitimate: {suite.coverage.legitimate_count}")
    print(f"Adversarial: {suite.coverage.adversarial_count}")
    print(f"Edge cases: {suite.coverage.edge_case_count}")

    for test in suite.test_cases:
        print(f"\n{test.test_id}")
        print(f"Category: {test.category.value}")
        print(f"Scenario: {test.scenario}")
        print(f"Agent: {test.agent_id}@{test.agent_version}")
        print(f"Tool: {test.tool_name}")
        print(f"Expected: {test.expected_decision.value}")

    if suite.needs_review:
        print(f"\nNeeds review: {len(suite.needs_review)}")
    if suite.rejected:
        print(f"Rejected proposals: {len(suite.rejected)}")

    runtime_registry = PolicyRegistry()
    assert runtime_registry.active_policies() == ()
    assert all(
        tools.resolve(tool_name).executions == []
        for tool_name in ("customer_db.read", "gmail.send", "stripe.refund")
    )
    print(f"\nCandidate Policy: {candidate.status.value}, NOT ACTIVE")
    print("Tests: GENERATED BUT NOT EXECUTED")


def main() -> None:
    load_local_environment()
    try:
        require_gemini_api_key()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    asyncio.run(_run())


if __name__ == "__main__":
    main()
