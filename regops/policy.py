from regops.models import (
    ActionContext,
    ActionType,
    DataClassification,
    Decision,
    DestinationType,
    Policy,
    PolicyDecision,
    Purpose,
)


def financial_policy_v1(*, active: bool = False) -> Policy:
    return Policy(
        policy_id="FIN-POL-v1",
        description=(
            "Financial account information may only be transmitted to an "
            "approved payment processor for an authorized financial transaction."
        ),
        active=active,
        protected_classification=DataClassification.BANK_ACCOUNT,
        governed_action=ActionType.TRANSMIT,
        allowed_destination=DestinationType.APPROVED_PAYMENT_PROCESSOR,
        required_purpose=Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
    )


class PolicyRegistry:
    """Local authoritative policy state for the runtime slice."""

    def __init__(self) -> None:
        self._policies: dict[str, Policy] = {}

    def register(self, policy: Policy) -> None:
        self._policies[policy.policy_id] = policy.model_copy(deep=True)

    def activate(self, policy_id: str) -> None:
        policy = self._policies[policy_id]
        self._policies[policy_id] = policy.model_copy(update={"active": True})

    def active_policies(self) -> tuple[Policy, ...]:
        return tuple(
            policy.model_copy(deep=True)
            for policy in self._policies.values()
            if policy.active
        )

    def registered_policies(self) -> tuple[Policy, ...]:
        return tuple(
            policy.model_copy(deep=True) for policy in self._policies.values()
        )


class PolicyEngine:
    def evaluate(
        self, context: ActionContext, policies: tuple[Policy, ...]
    ) -> PolicyDecision:
        for policy in sorted(policies, key=lambda item: item.policy_id):
            applies = (
                policy.protected_classification in context.data_classifications
                and context.action_type == policy.governed_action
            )
            if not applies:
                continue

            permitted = (
                context.destination_type == policy.allowed_destination
                and context.purpose == policy.required_purpose
            )
            if not permitted:
                return PolicyDecision(
                    decision=Decision.DENY,
                    policy_id=policy.policy_id,
                    reason="Destination and purpose do not satisfy the active policy.",
                )

        return PolicyDecision(
            decision=Decision.ALLOW,
            reason="No active policy denies this action.",
        )
