from regops.agent import LEGITIMATE_REFUND_REQUEST, UNSAFE_EMAIL_REQUEST, RefundAgent
from regops.models import AuditEvent, Decision
from regops.policy import PolicyRegistry, financial_policy_v1
from regops.registry import build_local_agent_registry
from regops.gateway import RuntimeGateway
from regops.tools import FakeToolRegistry


def _allowed(decision: Decision) -> str:
    return "ALLOWED" if decision == Decision.ALLOW else "DENIED"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _print_audits(events: tuple[AuditEvent, ...]) -> None:
    print("Audit events:")
    for event in events:
        classifications = ",".join(sorted(event.context.data_classifications)) or "NONE"
        print(
            f"  {event.context.tool_name}: {event.decision.decision.value}; "
            f"data={classifications}; purpose={event.context.purpose.value}; "
            f"execution={event.execution_status.value}"
        )


def main() -> None:
    policies = PolicyRegistry()
    tools = FakeToolRegistry()
    agents = build_local_agent_registry()
    gateway = RuntimeGateway(policies, tools, agents)
    agent = RefundAgent(gateway)

    print("=== BEFORE POLICY ===")
    print("Unsafe bank-data email request")
    before = agent.run(UNSAFE_EMAIL_REQUEST)
    print(f"Gmail action: {_allowed(before.action.decision.decision)}")
    print(f"Tool executed: {_yes_no(before.audit_events[-1].tool_executed)}")
    _print_audits(before.audit_events)

    print("\n=== ACTIVATE FIN-POL-v1 ===")
    policies.register(financial_policy_v1())
    policies.activate("FIN-POL-v1")

    print("\n=== AFTER POLICY ===")
    print("Same unsafe bank-data email request")
    after = agent.run(UNSAFE_EMAIL_REQUEST)
    print(f"Gmail action: {_allowed(after.action.decision.decision)}")
    print(f"Tool executed: {_yes_no(after.audit_events[-1].tool_executed)}")
    print(f"Reason: {after.action.decision.reason}")
    _print_audits(after.audit_events)

    print("\n=== LEGITIMATE REFUND ===")
    refund = agent.run(LEGITIMATE_REFUND_REQUEST)
    print(f"Stripe refund action: {_allowed(refund.action.decision.decision)}")
    print(f"Tool executed: {_yes_no(refund.audit_events[-1].tool_executed)}")
    _print_audits(refund.audit_events)


if __name__ == "__main__":
    main()
