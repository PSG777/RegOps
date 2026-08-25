from dataclasses import dataclass
from typing import Any

from regops.models import (
    ActionContext,
    AuditEvent,
    Decision,
    ExecutionStatus,
    InvocationMetadata,
    PolicyDecision,
)
from regops.policy import PolicyEngine, PolicyRegistry
from regops.registry import AgentRegistry
from regops.tools import FakeToolRegistry


@dataclass(frozen=True)
class GatewayResult:
    decision: PolicyDecision
    output: Any | None


class RuntimeGateway:
    def __init__(
        self,
        policy_registry: PolicyRegistry,
        tool_registry: FakeToolRegistry,
        agent_registry: AgentRegistry,
        policy_engine: PolicyEngine | None = None,
    ) -> None:
        self._policy_registry = policy_registry
        self._tool_registry = tool_registry
        self._agent_registry = agent_registry
        self._policy_engine = policy_engine or PolicyEngine()
        self.audit_events: list[AuditEvent] = []

    def invoke(
        self,
        agent_id: str,
        agent_version: str,
        tool_name: str,
        arguments: dict[str, Any],
        invocation: InvocationMetadata,
    ) -> GatewayResult:
        manifest = self._agent_registry.get_agent(agent_id, agent_version)
        if tool_name not in manifest.allowed_tools:
            raise PermissionError(f"{manifest.agent_id} is not registered for {tool_name}")

        tool = self._tool_registry.resolve(tool_name)
        context = ActionContext(
            agent_id=manifest.agent_id,
            agent_version=manifest.version,
            tool_name=tool.name,
            action_type=tool.metadata.action_type,
            data_classifications=invocation.data_classifications,
            destination_type=tool.metadata.destination_type,
            purpose=invocation.purpose,
        )
        decision = self._policy_engine.evaluate(
            context, self._policy_registry.active_policies()
        )
        if decision.decision == Decision.DENY:
            self.audit_events.append(
                AuditEvent(
                    context=context,
                    decision=decision,
                    tool_executed=False,
                    execution_status=ExecutionStatus.NOT_ATTEMPTED,
                )
            )
            return GatewayResult(decision=decision, output=None)

        try:
            output = tool.execute(arguments)
        except Exception as error:
            self.audit_events.append(
                AuditEvent(
                    context=context,
                    decision=decision,
                    tool_executed=True,
                    execution_status=ExecutionStatus.FAILED,
                    error_type=type(error).__name__,
                )
            )
            raise

        self.audit_events.append(
            AuditEvent(
                context=context,
                decision=decision,
                tool_executed=True,
                execution_status=ExecutionStatus.SUCCEEDED,
            )
        )
        return GatewayResult(decision=decision, output=output)
