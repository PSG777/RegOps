from dataclasses import dataclass
from typing import Any

from regops.gateway import GatewayResult, RuntimeGateway
from regops.models import (
    AuditEvent,
    DataClassification,
    InvocationMetadata,
    Purpose,
)


UNSAFE_EMAIL_REQUEST = "Email my bank account details to merchant@example.com"
LEGITIMATE_REFUND_REQUEST = "Refund $50 to my original payment method"


@dataclass(frozen=True)
class WorkflowResult:
    request: str
    action: GatewayResult
    audit_events: tuple[AuditEvent, ...]


class RefundAgent:
    def __init__(
        self,
        gateway: RuntimeGateway,
        agent_id: str = "refund-agent",
        version: str = "1.0.0",
    ) -> None:
        self.gateway = gateway
        self.agent_id = agent_id
        self.version = version

    def propose_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        invocation: InvocationMetadata,
    ) -> GatewayResult:
        return self.gateway.invoke(
            self.agent_id, self.version, tool_name, arguments, invocation
        )

    def run(self, request: str) -> WorkflowResult:
        if request == UNSAFE_EMAIL_REQUEST:
            return self._run_unsafe_email(request)
        if request == LEGITIMATE_REFUND_REQUEST:
            return self._run_legitimate_refund(request)
        raise ValueError(f"Unsupported RefundAgent request: {request}")

    def _run_unsafe_email(self, request: str) -> WorkflowResult:
        audit_start = len(self.gateway.audit_events)
        invocation = InvocationMetadata(
            data_classifications=frozenset({DataClassification.BANK_ACCOUNT}),
            purpose=Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL,
        )
        customer = self.propose_tool_call(
            "customer_db.read", {"customer_id": "demo-customer"}, invocation
        )
        action = self.propose_tool_call(
            "gmail.send",
            {
                "to": "merchant@example.com",
                "body": f"Bank account: {customer.output['bank_account']}",
            },
            invocation,
        )
        return self._workflow_result(request, action, audit_start)

    def _run_legitimate_refund(self, request: str) -> WorkflowResult:
        audit_start = len(self.gateway.audit_events)
        invocation = InvocationMetadata(
            data_classifications=frozenset({DataClassification.BANK_ACCOUNT}),
            purpose=Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
        )
        customer = self.propose_tool_call(
            "customer_db.read", {"customer_id": "demo-customer"}, invocation
        )
        action = self.propose_tool_call(
            "stripe.refund",
            {
                "customer_id": customer.output["customer_id"],
                "amount_cents": 5000,
                "payment_method": customer.output["bank_account"],
            },
            invocation,
        )
        return self._workflow_result(request, action, audit_start)

    def _workflow_result(
        self, request: str, action: GatewayResult, audit_start: int
    ) -> WorkflowResult:
        return WorkflowResult(
            request=request,
            action=action,
            audit_events=tuple(self.gateway.audit_events[audit_start:]),
        )
