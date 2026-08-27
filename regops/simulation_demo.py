import asyncio

from regops.config import load_local_environment, require_gemini_api_key
from regops.impact import ImpactAnalyzer
from regops.policy import PolicyRegistry
from regops.policy_generation import PolicyGenerationAgent
from regops.registry import build_local_agent_registry
from regops.regulation_analysis import RegulationAnalysisAgent
from regops.regulations import SAMPLE_FINANCIAL_REGULATION
from regops.replay import synthetic_historical_actions
from regops.simulation import PolicyEvaluator
from regops.test_generation import TestGenerationAgent
from regops.tools import FakeToolRegistry


def _percentage(value: float) -> str:
    return f"{value:.0%}"


async def _run() -> None:
    agents = build_local_agent_registry()
    generation_tools = FakeToolRegistry()
    authoritative_policies = PolicyRegistry()

    requirement = await RegulationAnalysisAgent().analyze(
        SAMPLE_FINANCIAL_REGULATION
    )
    impact_report = ImpactAnalyzer(agents, generation_tools).analyze(requirement)
    candidate = await PolicyGenerationAgent().generate(
        requirement, impact_report
    )
    suite = await TestGenerationAgent(agents, generation_tools).generate(
        requirement, candidate, impact_report
    )
    report = PolicyEvaluator(agents, authoritative_policies).evaluate(
        candidate, suite, synthetic_historical_actions()
    )

    print("=== POLICY EVALUATION ===")
    print(f"\nCandidate:\n{candidate.policy_id} v{candidate.version}")
    print(f"Status: {candidate.status.value} / NOT ACTIVE")
    print("\nTests:")
    print(f"{report.baseline_run.total_ready_tests} READY")
    print(f"{report.baseline_run.needs_review_tests} NEEDS REVIEW")

    print("\n=== BASELINE ===")
    print(f"\nCompliance: {_percentage(report.compliance_score_before)}")
    print(f"Utility: {_percentage(report.utility_score_before)}")
    print(f"Adversarial: {_percentage(report.adversarial_score_before)}")
    print(f"Critical violations: {report.critical_violations_before}")

    print("\n=== CANDIDATE POLICY ===")
    print(f"\nCompliance: {_percentage(report.compliance_score_after)}")
    print(f"Utility: {_percentage(report.utility_score_after)}")
    print(f"Adversarial: {_percentage(report.adversarial_score_after)}")
    print(f"Critical violations: {report.critical_violation_count}")

    replay = report.historical_replay_summary
    print("\n=== HISTORICAL REPLAY ===")
    print(f"\nActions analyzed: {replay.total_actions}")
    print(f"Unchanged: {replay.unchanged_actions}")
    print(f"Newly denied: {replay.newly_denied_actions}")
    print(f"Newly allowed: {replay.newly_allowed_actions}")
    print(f"Blast radius: {_percentage(report.blast_radius)}")
    print("\nAffected:")
    for agent_id in replay.affected_agent_ids:
        print(agent_id)
    for tool_name in replay.affected_tool_names:
        print(tool_name)

    assert authoritative_policies.active_policies() == ()
    print("\n=== RESULT ===")
    print(f"\n{report.final_evaluation_status.value}")
    print("\nCandidate policy remains:\nNOT ACTIVE")


def main() -> None:
    load_local_environment()
    try:
        require_gemini_api_key()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    asyncio.run(_run())


if __name__ == "__main__":
    main()
