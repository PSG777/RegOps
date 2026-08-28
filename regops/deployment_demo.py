import argparse
from datetime import datetime, timezone

from regops.agent import LEGITIMATE_REFUND_REQUEST, UNSAFE_EMAIL_REQUEST, RefundAgent
from regops.approval import policy_fingerprint
from regops.deployment import DeploymentController
from regops.gateway import RuntimeGateway
from regops.models import (
    ActionType,
    CandidatePolicy,
    DataClassification,
    DeploymentOperatorIdentity,
    DeploymentOperatorRole,
    DestinationType,
    Environment,
    PolicyEffect,
    PolicyReviewRecord,
    PolicyStatus,
    Purpose,
    ReviewDecision,
    ReviewerIdentity,
    ReviewerRole,
)
from regops.policy import PolicyRegistry
from regops.registry import build_local_agent_registry
from regops.tools import FakeToolRegistry


def _approved_candidate(version: int, *, email_allowed: bool = False) -> CandidatePolicy:
    return CandidatePolicy(
        policy_id="FIN-POL-001",
        version=version,
        requirement_id="FIN-REQ-001",
        regulation_id="FIN-REG-001",
        description=f"Offline approved financial transmission policy v{version}.",
        effect=PolicyEffect.DENY,
        protected_classification=DataClassification.BANK_ACCOUNT,
        governed_action=ActionType.TRANSMIT,
        allowed_destination=(
            DestinationType.EMAIL_PROVIDER
            if email_allowed
            else DestinationType.APPROVED_PAYMENT_PROCESSOR
        ),
        required_purpose=(
            Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL
            if email_allowed
            else Purpose.AUTHORIZED_FINANCIAL_TRANSACTION
        ),
        status=PolicyStatus.APPROVED,
        affected_agent_ids=("refund-agent",),
    )


def _approval(candidate: CandidatePolicy) -> PolicyReviewRecord:
    return PolicyReviewRecord(
        review_id=f"REVIEW-OFFLINE-{candidate.version}",
        policy_id=candidate.policy_id,
        policy_version=candidate.version,
        policy_fingerprint=policy_fingerprint(candidate),
        evaluation_id=f"EVAL-OFFLINE-{candidate.version}",
        reviewer=ReviewerIdentity(
            reviewer_id="compliance-offline",
            display_name="Offline Compliance Fixture",
            role=ReviewerRole.COMPLIANCE_OFFICER,
        ),
        decision=ReviewDecision.APPROVE,
        comment="Deterministic approved fixture for deployment demonstration.",
        reviewed_at=datetime.now(timezone.utc),
        previous_status=PolicyStatus.READY_FOR_REVIEW,
        resulting_status=PolicyStatus.APPROVED,
    )


def _yes_no(value: bool) -> str:
    return "YES" if value else "NO"


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline RegOps deployment demo")
    parser.add_argument("--offline", action="store_true", help="Use deterministic local artifacts")
    parser.parse_args()

    registry = PolicyRegistry()
    tools = FakeToolRegistry()
    agent = RefundAgent(
        RuntimeGateway(registry, tools, build_local_agent_registry())
    )
    controller = DeploymentController(registry)
    operator = DeploymentOperatorIdentity(
        operator_id="local-deployment-operator",
        display_name="Local Deployment Operator",
        role=DeploymentOperatorRole.DEPLOYMENT_OPERATOR,
    )
    v1 = _approved_candidate(1)
    v1_approval = _approval(v1)

    print("=== APPROVED POLICY ===")
    print(f"\n{v1.policy_id} v{v1.version}")
    print(f"Status: {v1.status.value}")
    print(f"Fingerprint verified: {_yes_no(v1_approval.policy_fingerprint == policy_fingerprint(v1))}")

    print("\n=== BEFORE DEPLOYMENT ===")
    before = agent.run(UNSAFE_EMAIL_REQUEST)
    print("\nBank account -> Gmail")
    print(f"Decision: {before.action.decision.decision.value}")

    deployed_v1 = controller.deploy(
        v1, v1_approval, Environment.DEVELOPMENT, operator
    )
    print("\n=== DEPLOYMENT ===")
    print(f"\nDeployment ID: {deployed_v1.deployment_id}")
    print(f"Environment: {deployed_v1.environment.value}")
    print("Approved artifact verified: YES")
    print(f"Runtime policy registered: {_yes_no(bool(registry.registered_policies()))}")
    print(f"Runtime policy active: {_yes_no(bool(registry.active_policies()))}")

    print("\n=== AFTER DEPLOYMENT ===")
    after = agent.run(UNSAFE_EMAIL_REQUEST)
    print("\nBank account -> Gmail")
    print(f"Decision: {after.action.decision.decision.value}")
    print(f"Tool executed: {_yes_no(after.audit_events[-1].tool_executed)}")
    refund = agent.run(LEGITIMATE_REFUND_REQUEST)
    print("\nAuthorized refund -> Stripe")
    print(f"Decision: {refund.action.decision.decision.value}")
    print(f"Tool executed: {_yes_no(refund.audit_events[-1].tool_executed)}")

    v2 = _approved_candidate(2, email_allowed=True)
    deployed_v2 = controller.deploy(
        v2, _approval(v2), Environment.DEVELOPMENT, operator
    )
    controller.rollback(deployed_v2.deployment_id, operator)
    active = registry.active_policies()
    restored = len(active) == 1 and active[0].version == v1.version
    print("\n=== ROLLBACK DEMO ===")
    print(f"\nPrevious policy version restored: {_yes_no(restored)}")
    print("\nCurrent active policy:")
    print(f"{active[0].policy_id} v{active[0].version}")


if __name__ == "__main__":
    main()
