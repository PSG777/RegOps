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
        self._policies: dict[tuple[str, int], Policy] = {}

    def register(self, policy: Policy) -> None:
        self._policies[(policy.policy_id, policy.version)] = policy.model_copy(
            deep=True
        )

    def activate(self, policy_id: str, version: int | None = None) -> None:
        matching = [
            key for key in self._policies if key[0] == policy_id
        ]
        if not matching:
            raise KeyError(policy_id)
        key = (policy_id, version) if version is not None else max(
            matching, key=lambda item: item[1]
        )
        self._replace_active_state(key)

    def register_and_activate(self, policy: Policy) -> Policy | None:
        """Atomically retain a version and make it authoritative for its ID."""

        key = (policy.policy_id, policy.version)
        existing = self._policies.get(key)
        inactive = policy.model_copy(update={"active": False}, deep=True)
        if existing is not None and existing.model_copy(update={"active": False}) != inactive:
            raise ValueError(
                f"A different runtime policy is already registered: "
                f"{policy.policy_id} v{policy.version}."
            )
        previous = next(
            (
                item.model_copy(deep=True)
                for item in self._policies.values()
                if item.policy_id == policy.policy_id and item.active
            ),
            None,
        )
        updated = {key_: item.model_copy(deep=True) for key_, item in self._policies.items()}
        updated[key] = inactive
        self._policies = self._with_active_version(updated, key)
        return previous

    def restore_active_version(
        self,
        policy_id: str,
        rolled_back_version: int,
        restore_version: int,
    ) -> None:
        current_key = (policy_id, rolled_back_version)
        restore_key = (policy_id, restore_version)
        if current_key not in self._policies or not self._policies[current_key].active:
            raise ValueError("The deployment policy version is not currently active.")
        if restore_key not in self._policies:
            raise ValueError("The previous policy version is not registered.")
        updated = {key: item.model_copy(deep=True) for key, item in self._policies.items()}
        self._policies = self._with_active_version(updated, restore_key)

    def get(self, policy_id: str, version: int) -> Policy:
        return self._policies[(policy_id, version)].model_copy(deep=True)

    def _replace_active_state(self, active_key: tuple[str, int]) -> None:
        updated = {key: item.model_copy(deep=True) for key, item in self._policies.items()}
        self._policies = self._with_active_version(updated, active_key)

    @staticmethod
    def _with_active_version(
        policies: dict[tuple[str, int], Policy], active_key: tuple[str, int]
    ) -> dict[tuple[str, int], Policy]:
        policy_id = active_key[0]
        return {
            key: item.model_copy(
                update={"active": key == active_key if key[0] == policy_id else item.active}
            )
            for key, item in policies.items()
        }

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
