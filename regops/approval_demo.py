import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from google.genai.errors import ServerError

from regops.approval import PolicyApprovalService
from regops.config import load_local_environment, require_gemini_api_key
from regops.impact import ImpactAnalyzer
from regops.models import ReviewDecision, ReviewerIdentity, ReviewerRole
from regops.policy import PolicyRegistry
from regops.policy_generation import PolicyGenerationAgent
from regops.registry import build_local_agent_registry
from regops.regulation_analysis import RegulationAnalysisAgent
from regops.regulations import SAMPLE_FINANCIAL_REGULATION
from regops.replay import synthetic_historical_actions
from regops.simulation import PolicyEvaluator
from regops.test_generation import TestGenerationAgent
from regops.tools import FakeToolRegistry


T = TypeVar("T")
LIVE_GENERATION_ATTEMPTS = 3


def _percentage(value: float) -> str:
    return f"{value:.0%}"


async def _with_transient_retry(operation: Callable[[], Awaitable[T]]) -> T:
    for attempt in range(1, LIVE_GENERATION_ATTEMPTS + 1):
        try:
            return await operation()
        except ServerError as error:
            if error.status != "UNAVAILABLE" or attempt == LIVE_GENERATION_ATTEMPTS:
                raise
            await asyncio.sleep(2**attempt)
    raise RuntimeError("Unreachable retry state.")


async def _run() -> None:
    agents = build_local_agent_registry()
    generation_tools = FakeToolRegistry()
    runtime_policies = PolicyRegistry()

    regulation_agent = RegulationAnalysisAgent()
    requirement = await _with_transient_retry(
        lambda: regulation_agent.analyze(SAMPLE_FINANCIAL_REGULATION)
    )
    impact = ImpactAnalyzer(agents, generation_tools).analyze(requirement)
    policy_agent = PolicyGenerationAgent()
    candidate = await _with_transient_retry(
        lambda: policy_agent.generate(requirement, impact)
    )
    test_agent = TestGenerationAgent(agents, generation_tools)
    suite = await _with_transient_retry(
        lambda: test_agent.generate(requirement, candidate, impact)
    )
    evaluation = PolicyEvaluator(agents, runtime_policies).evaluate(
        candidate, suite, synthetic_historical_actions()
    )

    approval = PolicyApprovalService()
    eligibility = approval.assess_review_eligibility(candidate, evaluation)
    ready = approval.prepare_for_review(candidate, evaluation)
    reviewer = ReviewerIdentity(
        reviewer_id="compliance-001",
        display_name="Compliance Officer",
        role=ReviewerRole.COMPLIANCE_OFFICER,
    )
    outcome = approval.submit_decision(
        ready,
        evaluation,
        reviewer,
        ReviewDecision.APPROVE,
        "Approved after reviewing the completed policy evaluation.",
    )

    print("=== POLICY REVIEW ===")
    print(f"\nCandidate:\n{candidate.policy_id} v{candidate.version}")
    print(f"\nStatus:\n{candidate.status.value}")
    print(f"\nEvaluation:\n{evaluation.final_evaluation_status.value}")
    print(f"\nCompliance:\n{_percentage(evaluation.compliance_score_after)}")
    print(f"\nUtility:\n{_percentage(evaluation.utility_score_after)}")
    print(f"\nCritical violations:\n{evaluation.critical_violation_count}")
    print(f"\nBlast radius:\n{_percentage(evaluation.blast_radius)}")
    print(f"\nPolicy fingerprint:\n{evaluation.policy_fingerprint[:16]}...")

    print("\n=== REVIEW ELIGIBILITY ===")
    print("\nREADY FOR REVIEW" if eligibility.eligible else "\nNOT ELIGIBLE")
    print(f"\nReviewer:\n{reviewer.reviewer_id}\n{reviewer.display_name}")
    print(f"\nDecision:\n{outcome.record.decision.value}")

    print("\n=== REVIEW RESULT ===")
    print(f"\nPrevious status:\n{outcome.record.previous_status.value}")
    print(f"\nNew status:\n{outcome.candidate.status.value}")
    print(f"\nEvaluation bound:\n{outcome.record.evaluation_id}")
    print("\nPolicy fingerprint verified:\nYES")
    print("\nRuntime deployment:\nNOT STARTED")
    print("\nRuntime policy active:\nNO")

    assert runtime_policies.registered_policies() == ()
    assert runtime_policies.active_policies() == ()


def main() -> None:
    load_local_environment()
    try:
        require_gemini_api_key()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
    asyncio.run(_run())


if __name__ == "__main__":
    main()
