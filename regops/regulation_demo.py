import asyncio

from regops.config import load_local_environment, require_gemini_api_key
from regops.regulation_analysis import RegulationAnalysisAgent
from regops.regulations import SAMPLE_FINANCIAL_REGULATION


async def _run() -> None:
    regulation = SAMPLE_FINANCIAL_REGULATION
    requirement = await RegulationAnalysisAgent().analyze(regulation)

    print("=== REGULATION ===")
    print(regulation.source_text)
    print("\n=== EXTRACTED REQUIREMENT ===")
    print(f"Data classification: {requirement.data_classification.value}")
    print(f"Action: {requirement.governed_action.value}")
    print(f"Allowed destination: {requirement.allowed_destination.value}")
    print(f"Required purpose: {requirement.required_purpose.value}")
    print(f"Source evidence: {requirement.source_excerpt}")


def main() -> None:
    load_local_environment()
    try:
        require_gemini_api_key()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    asyncio.run(_run())


if __name__ == "__main__":
    main()
