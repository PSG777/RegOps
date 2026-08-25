from dataclasses import dataclass, field
from typing import Any, Callable

from regops.models import ActionType, DestinationType


@dataclass(frozen=True)
class ToolMetadata:
    action_type: ActionType
    destination_type: DestinationType


@dataclass
class FakeTool:
    name: str
    metadata: ToolMetadata
    result_factory: Callable[[dict[str, Any]], Any]
    executions: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, arguments: dict[str, Any]) -> Any:
        self.executions.append(arguments.copy())
        return self.result_factory(arguments)


class FakeToolRegistry:
    def __init__(self) -> None:
        self._tools = {
            "customer_db.read": FakeTool(
                name="customer_db.read",
                metadata=ToolMetadata(
                    action_type=ActionType.READ,
                    destination_type=DestinationType.INTERNAL_DATABASE,
                ),
                result_factory=lambda args: {
                    "customer_id": args["customer_id"],
                    "bank_account": "****6789",
                },
            ),
            "gmail.send": FakeTool(
                name="gmail.send",
                metadata=ToolMetadata(
                    action_type=ActionType.TRANSMIT,
                    destination_type=DestinationType.EMAIL_PROVIDER,
                ),
                result_factory=lambda args: {"message_id": "fake-gmail-message"},
            ),
            "stripe.refund": FakeTool(
                name="stripe.refund",
                metadata=ToolMetadata(
                    action_type=ActionType.TRANSMIT,
                    destination_type=DestinationType.APPROVED_PAYMENT_PROCESSOR,
                ),
                result_factory=lambda args: {
                    "refund_id": "fake-stripe-refund",
                    "status": "succeeded",
                },
            ),
        }

    def resolve(self, name: str) -> FakeTool:
        return self._tools[name]

    def register(self, tool: FakeTool) -> None:
        self._tools[tool.name] = tool
