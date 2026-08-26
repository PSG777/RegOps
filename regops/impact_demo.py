from regops.impact import ImpactAnalyzer
from regops.models import ImpactStatus
from regops.registry import build_local_agent_registry
from regops.regulations import (
    SAMPLE_FINANCIAL_REGULATION,
    SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT,
)
from regops.tools import FakeToolRegistry


def main() -> None:
    regulation = SAMPLE_FINANCIAL_REGULATION
    requirement = SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
    if requirement.regulation_id != regulation.regulation_id:
        raise RuntimeError("Verified fixture does not match the sample regulation.")

    report = ImpactAnalyzer(
        build_local_agent_registry(), FakeToolRegistry()
    ).analyze(requirement)

    print("=== IMPACT ANALYSIS ===")
    print(f"Requirement: {report.requirement_id}")
    for impact in report.agent_impacts:
        print(f"\n{impact.agent_name} v{impact.agent_version}")
        print(f"Status: {impact.status.value}")
        print(f"Severity: {impact.severity.value}")
        for path in impact.capability_paths:
            print("Risk path:")
            print(
                f"{path.data_classification.value} -> {impact.agent_name} -> "
                f"{path.tool_name} -> {path.destination_type.value}"
            )
        if impact.status == ImpactStatus.NEEDS_REVIEW:
            print(f"Review reason: {impact.reasons[-1]}")


if __name__ == "__main__":
    main()
