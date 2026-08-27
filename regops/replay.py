from collections.abc import Iterable

from regops.impact import TrustedToolRegistry
from regops.models import (
    ActionContext,
    DataClassification,
    Decision,
    ExecutionStatus,
    HistoricalAction,
    HistoricalReplayResult,
    HistoricalReplaySummary,
    Policy,
    Purpose,
    ReplayChange,
)
from regops.policy import PolicyEngine
from regops.registry import AgentRegistry
from regops.tools import ToolMetadata


class HistoricalReplayError(ValueError):
    pass


class HistoricalReplayEngine:
    """Evaluates normalized history without invoking any tool implementation."""

    def __init__(
        self,
        agent_registry: AgentRegistry,
        tool_registry: TrustedToolRegistry,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry
        self._policy_engine = policy_engine or PolicyEngine()

    def replay(
        self,
        actions: Iterable[HistoricalAction],
        baseline_policies: tuple[Policy, ...],
        candidate_policies: tuple[Policy, ...],
    ) -> HistoricalReplaySummary:
        results = tuple(
            self._replay_action(action, baseline_policies, candidate_policies)
            for action in actions
        )
        changed = tuple(
            result for result in results if result.change != ReplayChange.UNCHANGED
        )
        newly_denied = sum(
            result.change == ReplayChange.NEWLY_DENIED for result in results
        )
        newly_allowed = sum(
            result.change == ReplayChange.NEWLY_ALLOWED for result in results
        )
        total = len(results)
        return HistoricalReplaySummary(
            total_actions=total,
            unchanged_actions=total - newly_denied - newly_allowed,
            newly_denied_actions=newly_denied,
            newly_allowed_actions=newly_allowed,
            decision_change_rate=len(changed) / total if total else 0.0,
            affected_agent_ids=tuple(sorted({item.agent_id for item in changed})),
            affected_tool_names=tuple(sorted({item.tool_name for item in changed})),
            individual_results=results,
        )

    def _replay_action(
        self,
        action: HistoricalAction,
        baseline_policies: tuple[Policy, ...],
        candidate_policies: tuple[Policy, ...],
    ) -> HistoricalReplayResult:
        manifest = self._agent_registry.get_agent(
            action.agent_id, action.agent_version
        )
        if action.tool_name not in manifest.allowed_tools:
            raise HistoricalReplayError(
                f"{action.agent_id}@{action.agent_version} is not registered "
                f"for {action.tool_name}."
            )
        if not action.data_classifications.issubset(manifest.data_access):
            raise HistoricalReplayError(
                f"{action.action_id} exceeds the registered agent's data access."
            )
        try:
            tool = self._tool_registry.resolve(action.tool_name)
        except LookupError as error:
            raise HistoricalReplayError(
                f"Trusted metadata is unavailable for {action.tool_name}."
            ) from error
        metadata = getattr(tool, "metadata", None)
        if not isinstance(metadata, ToolMetadata):
            raise HistoricalReplayError(
                f"Trusted metadata is incomplete for {action.tool_name}."
            )

        context = ActionContext(
            agent_id=manifest.agent_id,
            agent_version=manifest.version,
            tool_name=action.tool_name,
            action_type=metadata.action_type,
            data_classifications=action.data_classifications,
            destination_type=metadata.destination_type,
            purpose=action.purpose,
        )
        baseline = self._policy_engine.evaluate(context, baseline_policies)
        candidate = self._policy_engine.evaluate(context, candidate_policies)
        if baseline.decision == candidate.decision:
            change = ReplayChange.UNCHANGED
        elif candidate.decision == Decision.DENY:
            change = ReplayChange.NEWLY_DENIED
        else:
            change = ReplayChange.NEWLY_ALLOWED
        return HistoricalReplayResult(
            action_id=action.action_id,
            agent_id=manifest.agent_id,
            agent_version=manifest.version,
            tool_name=action.tool_name,
            baseline_decision=baseline.decision,
            candidate_decision=candidate.decision,
            change=change,
            baseline_policy_id=baseline.policy_id,
            candidate_policy_id=candidate.policy_id,
        )


def synthetic_historical_actions() -> tuple[HistoricalAction, ...]:
    """Deterministic, payload-free history for the local enterprise demo."""

    specifications = (
        *(
            ("refund-agent", "stripe.refund", {DataClassification.BANK_ACCOUNT},
             Purpose.AUTHORIZED_FINANCIAL_TRANSACTION)
            for _ in range(12)
        ),
        *(
            ("refund-agent", "gmail.send", {DataClassification.CUSTOMER_RECORD},
             Purpose.CUSTOMER_SUPPORT)
            for _ in range(6)
        ),
        *(
            ("refund-agent", "gmail.send", {DataClassification.BANK_ACCOUNT},
             Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL)
            for _ in range(3)
        ),
        *(
            ("support-agent", "customer_db.read", {DataClassification.CUSTOMER_RECORD},
             Purpose.CUSTOMER_SUPPORT)
            for _ in range(6)
        ),
        *(
            ("support-agent", "gmail.send", {DataClassification.CUSTOMER_RECORD},
             Purpose.CUSTOMER_SUPPORT)
            for _ in range(6)
        ),
        *(
            ("sales-agent", "gmail.send", {DataClassification.CUSTOMER_RECORD},
             Purpose.CUSTOMER_SUPPORT)
            for _ in range(4)
        ),
        *(
            ("refund-agent", "customer_db.read", {DataClassification.BANK_ACCOUNT},
             Purpose.AUTHORIZED_FINANCIAL_TRANSACTION)
            for _ in range(3)
        ),
    )
    return tuple(
        HistoricalAction(
            action_id=f"HIST-{index:03d}",
            agent_id=agent_id,
            agent_version="1.0.0",
            tool_name=tool_name,
            data_classifications=frozenset(classifications),
            purpose=purpose,
            original_decision=Decision.ALLOW,
            original_execution_status=ExecutionStatus.SUCCEEDED,
        )
        for index, (agent_id, tool_name, classifications, purpose) in enumerate(
            specifications, start=1
        )
    )
