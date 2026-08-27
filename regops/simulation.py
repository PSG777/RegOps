from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from regops.approval import policy_fingerprint
from regops.gateway import RuntimeGateway
from regops.models import (
    CandidatePolicy,
    ComplianceTestCase,
    ComplianceTestSuite,
    Decision,
    ExecutionStatus,
    HistoricalAction,
    InvocationMetadata,
    Policy,
    PolicyEvaluationReport,
    PolicyEvaluationStatus,
    PolicyStatus,
    SimulationMode,
    SimulationRun,
    SimulationTestResult,
    TestCaseStatus,
    TestCategory,
    TestExecutionStatus,
)
from regops.policy import PolicyEngine, PolicyRegistry
from regops.policy_generation import candidate_to_runtime_policy
from regops.registry import AgentRegistry
from regops.replay import HistoricalReplayEngine
from regops.tools import FakeToolRegistry


MINIMUM_COMPLIANCE_SCORE = 1.0
MINIMUM_UTILITY_SCORE = 0.9
MAXIMUM_CRITICAL_VIOLATIONS = 0


class SimulationError(ValueError):
    pass


ToolRegistryFactory = Callable[[], FakeToolRegistry]


@dataclass(frozen=True)
class SimulationScores:
    compliance: float
    utility: float
    adversarial: float
    overall_correctness: float
    critical_violations: int


class SimulationHarness:
    """Runs trusted test cases through disposable local runtime gateways."""

    def __init__(
        self,
        agent_registry: AgentRegistry,
        authoritative_policy_registry: PolicyRegistry,
        *,
        tool_registry_factory: ToolRegistryFactory = FakeToolRegistry,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._agent_registry = agent_registry
        self._authoritative_policy_registry = authoritative_policy_registry
        self._tool_registry_factory = tool_registry_factory
        self._policy_engine = policy_engine or PolicyEngine()
        self._last_tool_registries: dict[SimulationMode, FakeToolRegistry] = {}

    @property
    def last_tool_registries(self) -> dict[SimulationMode, FakeToolRegistry]:
        return dict(self._last_tool_registries)

    def run(
        self,
        suite: ComplianceTestSuite,
        candidate: CandidatePolicy,
        mode: SimulationMode,
    ) -> SimulationRun:
        self._validate_inputs(suite, candidate)
        sandbox_policies = self._sandbox_policy_registry(candidate, mode)
        sandbox_tools = self._tool_registry_factory()
        if not isinstance(sandbox_tools, FakeToolRegistry):
            raise SimulationError("Simulation requires a local FakeToolRegistry.")
        self._last_tool_registries[mode] = sandbox_tools
        gateway = RuntimeGateway(
            sandbox_policies,
            sandbox_tools,
            self._agent_registry,
            self._policy_engine,
        )

        ready_tests = tuple(
            test for test in suite.test_cases if test.status == TestCaseStatus.READY
        )
        results = tuple(self._execute_test(gateway, test) for test in ready_tests)
        return SimulationRun(
            simulation_id=f"SIM-{suite.suite_id}-{mode.value}",
            requirement_id=suite.requirement_id,
            test_suite_id=suite.suite_id,
            policy_id=candidate.policy_id,
            policy_version=candidate.version,
            mode=mode,
            total_ready_tests=len(ready_tests),
            passed_tests=sum(
                result.execution_status == TestExecutionStatus.PASSED
                for result in results
            ),
            failed_tests=sum(
                result.execution_status == TestExecutionStatus.FAILED
                for result in results
            ),
            needs_review_tests=(
                len(suite.needs_review)
                + sum(
                    test.status == TestCaseStatus.NEEDS_REVIEW
                    for test in suite.test_cases
                )
            ),
            error_tests=sum(
                result.execution_status == TestExecutionStatus.ERROR
                for result in results
            ),
            individual_results=results,
        )

    def _sandbox_policy_registry(
        self, candidate: CandidatePolicy, mode: SimulationMode
    ) -> PolicyRegistry:
        baseline = self._authoritative_policy_registry.active_policies()
        if any(policy.policy_id == candidate.policy_id for policy in baseline):
            raise SimulationError(
                "Candidate policy is already active in the authoritative registry."
            )
        sandbox = PolicyRegistry()
        for policy in baseline:
            sandbox.register(policy)
        if mode == SimulationMode.CANDIDATE:
            runtime_candidate = candidate_to_runtime_policy(candidate).model_copy(
                update={"active": True}
            )
            sandbox.register(runtime_candidate)
        return sandbox

    @staticmethod
    def _validate_inputs(
        suite: ComplianceTestSuite, candidate: CandidatePolicy
    ) -> None:
        if candidate.status != PolicyStatus.VALIDATED:
            raise SimulationError("CandidatePolicy must be VALIDATED.")
        if (
            suite.policy_id != candidate.policy_id
            or suite.candidate_policy_version != candidate.version
            or suite.requirement_id != candidate.requirement_id
        ):
            raise SimulationError(
                "ComplianceTestSuite does not match the CandidatePolicy."
            )

    def _execute_test(
        self, gateway: RuntimeGateway, test: ComplianceTestCase
    ) -> SimulationTestResult:
        audit_count = len(gateway.audit_events)
        try:
            result = gateway.invoke(
                agent_id=test.agent_id,
                agent_version=test.agent_version,
                tool_name=test.tool_name,
                arguments=self._safe_fake_arguments(test.tool_name),
                invocation=InvocationMetadata(
                    data_classifications=test.data_classifications,
                    purpose=test.purpose,
                ),
            )
        except Exception as error:
            if len(gateway.audit_events) == audit_count:
                raise SimulationError(
                    f"Trusted test {test.test_id} could not reach policy execution."
                ) from error
            event = gateway.audit_events[-1]
            if event.execution_status != ExecutionStatus.FAILED:
                raise SimulationError(
                    f"Trusted test {test.test_id} failed outside fake-tool execution."
                ) from error
            return SimulationTestResult(
                test_id=test.test_id,
                category=test.category,
                agent_id=test.agent_id,
                agent_version=test.agent_version,
                tool_name=test.tool_name,
                expected_decision=test.expected_decision,
                actual_decision=event.decision.decision,
                execution_status=TestExecutionStatus.ERROR,
                tool_executed=event.tool_executed,
                policy_id_used=event.decision.policy_id,
                reason=(
                    f"Policy decision preserved; fake tool execution failed "
                    f"with {type(error).__name__}."
                ),
            )

        status = (
            TestExecutionStatus.PASSED
            if result.decision.decision == test.expected_decision
            else TestExecutionStatus.FAILED
        )
        event = gateway.audit_events[-1]
        return SimulationTestResult(
            test_id=test.test_id,
            category=test.category,
            agent_id=test.agent_id,
            agent_version=test.agent_version,
            tool_name=test.tool_name,
            expected_decision=test.expected_decision,
            actual_decision=result.decision.decision,
            execution_status=status,
            tool_executed=event.tool_executed,
            policy_id_used=result.decision.policy_id,
            reason=result.decision.reason,
        )

    @staticmethod
    def _safe_fake_arguments(tool_name: str) -> dict[str, Any]:
        arguments = {
            "customer_db.read": {"customer_id": "simulation-customer"},
            "gmail.send": {
                "to": "simulation@example.invalid",
                "body": "Synthetic compliance simulation message.",
            },
            "stripe.refund": {
                "customer_id": "simulation-customer",
                "amount_cents": 5000,
            },
        }
        try:
            return arguments[tool_name].copy()
        except KeyError as error:
            raise SimulationError(
                f"No sandbox argument fixture exists for {tool_name}."
            ) from error


class PolicyScorer:
    @classmethod
    def score(cls, run: SimulationRun) -> SimulationScores:
        results = run.individual_results
        deny_expected = tuple(
            result for result in results if result.expected_decision == Decision.DENY
        )
        legitimate_allow = tuple(
            result
            for result in results
            if result.category == TestCategory.LEGITIMATE
            and result.expected_decision == Decision.ALLOW
        )
        adversarial = tuple(
            result
            for result in results
            if result.category == TestCategory.ADVERSARIAL
        )
        return SimulationScores(
            compliance=cls._decision_accuracy(deny_expected),
            utility=cls._decision_accuracy(legitimate_allow),
            adversarial=cls._decision_accuracy(adversarial),
            overall_correctness=cls._decision_accuracy(results),
            critical_violations=sum(
                result.expected_decision == Decision.DENY
                and result.actual_decision == Decision.ALLOW
                for result in results
            ),
        )

    @staticmethod
    def _decision_accuracy(
        results: Iterable[SimulationTestResult],
    ) -> float:
        items = tuple(results)
        if not items:
            return 0.0
        return sum(
            item.actual_decision == item.expected_decision for item in items
        ) / len(items)

    @staticmethod
    def evaluate_candidate(scores: SimulationScores) -> PolicyEvaluationStatus:
        return (
            PolicyEvaluationStatus.PASS
            if (
                scores.critical_violations <= MAXIMUM_CRITICAL_VIOLATIONS
                and scores.compliance >= MINIMUM_COMPLIANCE_SCORE
                and scores.utility >= MINIMUM_UTILITY_SCORE
            )
            else PolicyEvaluationStatus.FAIL
        )


class PolicyEvaluator:
    def __init__(
        self,
        agent_registry: AgentRegistry,
        authoritative_policy_registry: PolicyRegistry,
        *,
        tool_registry_factory: ToolRegistryFactory = FakeToolRegistry,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._authoritative_policy_registry = authoritative_policy_registry
        self._policy_engine = policy_engine or PolicyEngine()
        self._tool_registry_factory = tool_registry_factory
        self.simulation = SimulationHarness(
            agent_registry,
            authoritative_policy_registry,
            tool_registry_factory=tool_registry_factory,
            policy_engine=self._policy_engine,
        )
        self._agent_registry = agent_registry

    def evaluate(
        self,
        candidate: CandidatePolicy,
        suite: ComplianceTestSuite,
        historical_actions: Iterable[HistoricalAction],
    ) -> PolicyEvaluationReport:
        authoritative_before = self._authoritative_policy_registry.active_policies()
        baseline = self.simulation.run(suite, candidate, SimulationMode.BASELINE)
        candidate_run = self.simulation.run(
            suite, candidate, SimulationMode.CANDIDATE
        )
        if tuple(item.test_id for item in baseline.individual_results) != tuple(
            item.test_id for item in candidate_run.individual_results
        ):
            raise SimulationError("Baseline and candidate test inputs differ.")

        candidate_policy = candidate_to_runtime_policy(candidate).model_copy(
            update={"active": True}
        )
        replay_tools = self._tool_registry_factory()
        if not isinstance(replay_tools, FakeToolRegistry):
            raise SimulationError("Historical replay requires trusted local tools.")
        replay = HistoricalReplayEngine(
            self._agent_registry, replay_tools, self._policy_engine
        ).replay(
            historical_actions,
            authoritative_before,
            (*authoritative_before, candidate_policy),
        )

        authoritative_after = self._authoritative_policy_registry.active_policies()
        if authoritative_after != authoritative_before:
            raise SimulationError("Simulation mutated authoritative policy state.")
        if candidate.status != PolicyStatus.VALIDATED:
            raise SimulationError("Simulation mutated candidate lifecycle state.")

        before = PolicyScorer.score(baseline)
        after = PolicyScorer.score(candidate_run)
        final_status = PolicyScorer.evaluate_candidate(after)
        return PolicyEvaluationReport(
            evaluation_id=(
                f"EVAL-{candidate.policy_id}-v{candidate.version}-{suite.suite_id}"
            ),
            policy_id=candidate.policy_id,
            policy_version=candidate.version,
            policy_fingerprint=policy_fingerprint(candidate),
            requirement_id=candidate.requirement_id,
            test_suite_id=suite.suite_id,
            baseline_run=baseline,
            candidate_run=candidate_run,
            compliance_score_before=before.compliance,
            compliance_score_after=after.compliance,
            utility_score_before=before.utility,
            utility_score_after=after.utility,
            adversarial_score_before=before.adversarial,
            adversarial_score_after=after.adversarial,
            overall_correctness_before=before.overall_correctness,
            overall_correctness_after=after.overall_correctness,
            critical_violations_before=before.critical_violations,
            critical_violation_count=after.critical_violations,
            historical_replay_summary=replay,
            blast_radius=replay.decision_change_rate,
            final_evaluation_status=final_status,
        )
