import asyncio

from regops.config import load_local_environment, require_gemini_api_key
from regops.impact import ImpactAnalyzer
from regops.models import ImpactStatus
from regops.policy import PolicyRegistry
from regops.policy_generation import PolicyGenerationAgent
from regops.registry import build_local_agent_registry
from regops.regulation_analysis import RegulationAnalysisAgent
from regops.regulations import SAMPLE_FINANCIAL_REGULATION
from regops.tools import FakeToolRegistry


async def _run() -> None:
    requirement = await RegulationAnalysisAgent().analyze(
        SAMPLE_FINANCIAL_REGULATION
    )
    impact_report = ImpactAnalyzer(
        build_local_agent_registry(), FakeToolRegistry()
    ).analyze(requirement)
    candidate = await PolicyGenerationAgent().generate(
        requirement, impact_report
    )

    print("=== VERIFIED REQUIREMENT ===")
    print(f"Data: {requirement.data_classification.value}")
    print(f"Action: {requirement.governed_action.value}")
    print(f"Allowed destination: {requirement.allowed_destination.value}")
    print(f"Purpose: {requirement.required_purpose.value}")

    print("\n=== IMPACT ===")
    print("Affected agents:")
    for impact in impact_report.agent_impacts:
        if impact.status != ImpactStatus.AFFECTED:
            continue
        print(f"- {impact.agent_name} v{impact.agent_version}")
        for path in impact.capability_paths:
            print(
                f"Risk path: {path.data_classification.value} -> "
                f"{impact.agent_name} -> {path.tool_name} -> "
                f"{path.destination_type.value}"
            )

    print("\n=== GENERATED CANDIDATE POLICY ===")
    print(f"Policy: {candidate.policy_id} v{candidate.version}")
    print(f"Status: {candidate.status.value}")
    print(f"Effect: {candidate.effect.value}")
    print(f"Protected classification: {candidate.protected_classification.value}")
    print(f"Governed action: {candidate.governed_action.value}")
    print("Allowed only when:")
    print(f"Destination: {candidate.allowed_destination.value}")
    print(f"Purpose: {candidate.required_purpose.value}")
    print("Affected agents:")
    for agent_id in candidate.affected_agent_ids:
        print(f"- {agent_id}")

    runtime_registry = PolicyRegistry()
    assert runtime_registry.active_policies() == ()
    print("Deployment status: NOT ACTIVE")


def main() -> None:
    load_local_environment()
    try:
        require_gemini_api_key()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    asyncio.run(_run())


if __name__ == "__main__":
    main()
