from datetime import datetime, timezone

import pytest

from regops.approval import policy_fingerprint
from regops.deployment import (
    DeploymentAuthorizationError,
    DeploymentController,
    DeploymentError,
    DeploymentValidationError,
    RollbackError,
)
from regops.gateway import RuntimeGateway
from regops.models import (
    ActionType,
    CandidatePolicy,
    DataClassification,
    Decision,
    DeploymentOperatorIdentity,
    DeploymentOperatorRole,
    DeploymentStatus,
    DestinationType,
    Environment,
    InvocationMetadata,
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


FIXED_TIME = datetime(2026, 8, 27, 16, 0, tzinfo=timezone.utc)


def candidate(
    version: int = 1,
    *,
    status: PolicyStatus = PolicyStatus.APPROVED,
    allowed_destination: DestinationType = DestinationType.APPROVED_PAYMENT_PROCESSOR,
    required_purpose: Purpose = Purpose.AUTHORIZED_FINANCIAL_TRANSACTION,
) -> CandidatePolicy:
    return CandidatePolicy(
        policy_id="FIN-POL-001",
        version=version,
        requirement_id="FIN-REQ-001",
        regulation_id="FIN-REG-001",
        description=f"Trusted financial transmission policy v{version}.",
        effect=PolicyEffect.DENY,
        protected_classification=DataClassification.BANK_ACCOUNT,
        governed_action=ActionType.TRANSMIT,
        allowed_destination=allowed_destination,
        required_purpose=required_purpose,
        status=status,
        affected_agent_ids=("refund-agent",),
    )


def approval(item: CandidatePolicy, **updates) -> PolicyReviewRecord:
    record = PolicyReviewRecord(
        review_id=f"REVIEW-{item.version}",
        policy_id=item.policy_id,
        policy_version=item.version,
        policy_fingerprint=policy_fingerprint(item),
        evaluation_id=f"EVAL-{item.version}",
        reviewer=ReviewerIdentity(
            reviewer_id="compliance-001",
            display_name="Compliance Officer",
            role=ReviewerRole.COMPLIANCE_OFFICER,
        ),
        decision=ReviewDecision.APPROVE,
        comment="Approved exact evaluated artifact.",
        reviewed_at=FIXED_TIME,
        previous_status=PolicyStatus.READY_FOR_REVIEW,
        resulting_status=PolicyStatus.APPROVED,
    )
    return record.model_copy(update=updates)


def operator(
    role: DeploymentOperatorRole = DeploymentOperatorRole.DEPLOYMENT_OPERATOR,
) -> DeploymentOperatorIdentity:
    return DeploymentOperatorIdentity(
        operator_id="deploy-001",
        display_name="Deployment Operator",
        role=role,
    )


def controller(registry: PolicyRegistry, ids=("DEPLOY-001", "DEPLOY-002")):
    deployment_ids = iter(ids)
    return DeploymentController(
        registry,
        deployment_id_factory=lambda: next(deployment_ids),
        clock=lambda: FIXED_TIME,
    )


def invoke(registry: PolicyRegistry, tools: FakeToolRegistry, tool_name: str, purpose: Purpose):
    return RuntimeGateway(registry, tools, build_local_agent_registry()).invoke(
        "refund-agent",
        "1.0.0",
        tool_name,
        {"to": "merchant@example.com", "body": "synthetic"},
        InvocationMetadata(
            data_classifications=frozenset({DataClassification.BANK_ACCOUNT}),
            purpose=purpose,
        ),
    )


def test_approved_candidate_deploys_exact_runtime_policy_and_audit_evidence():
    registry = PolicyRegistry()
    item = candidate()
    record = controller(registry).deploy(
        item, approval(item), Environment.DEVELOPMENT, operator()
    )

    runtime = registry.get(item.policy_id, item.version)
    assert record.status == DeploymentStatus.ACTIVE
    assert record.policy_id == item.policy_id
    assert record.policy_version == item.version
    assert record.policy_fingerprint == policy_fingerprint(item)
    assert record.approval_review_id == "REVIEW-1"
    assert record.environment == Environment.DEVELOPMENT
    assert record.operator == operator()
    assert record.deployed_at == record.activated_at == FIXED_TIME
    assert runtime.active is True
    assert runtime.version == item.version
    assert runtime.description == item.description
    assert runtime.allowed_destination == item.allowed_destination


@pytest.mark.parametrize(
    "status",
    [PolicyStatus.VALIDATED, PolicyStatus.REJECTED, PolicyStatus.CHANGES_REQUESTED],
)
def test_unapproved_candidate_status_cannot_deploy(status):
    registry = PolicyRegistry()
    item = candidate(status=status)
    deployment = controller(registry)

    with pytest.raises(DeploymentValidationError, match="APPROVED"):
        deployment.deploy(item, approval(item), Environment.STAGING, operator())

    assert registry.registered_policies() == ()
    assert deployment.deployment_records[-1].status == DeploymentStatus.FAILED
    assert item.status == status


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"policy_id": "OTHER-POLICY"}, "policy ID"),
        ({"policy_version": 99}, "policy version"),
        ({"policy_fingerprint": "0" * 64}, "fingerprint"),
        ({"decision": ReviewDecision.REJECT}, "decision"),
    ],
)
def test_approval_must_bind_exact_approved_artifact(updates, message):
    registry = PolicyRegistry()
    item = candidate()

    with pytest.raises(DeploymentValidationError, match=message):
        controller(registry).deploy(
            item, approval(item, **updates), Environment.PRODUCTION, operator()
        )

    assert registry.registered_policies() == ()


def test_failed_registry_activation_is_atomic_and_candidate_stays_approved():
    registry = PolicyRegistry()
    existing = candidate()
    first = controller(registry).deploy(
        existing, approval(existing), Environment.DEVELOPMENT, operator()
    )
    changed = existing.model_copy(
        update={"description": "Different artifact with the same identity."}
    )
    second_controller = controller(registry, ids=("DEPLOY-CONFLICT",))

    with pytest.raises(DeploymentError, match="deployment failed"):
        second_controller.deploy(
            changed, approval(changed), Environment.DEVELOPMENT, operator()
        )

    assert first.status == DeploymentStatus.ACTIVE
    assert registry.active_policies() == (registry.get("FIN-POL-001", 1),)
    assert registry.get("FIN-POL-001", 1).description == existing.description
    assert second_controller.deployment_records[0].status == DeploymentStatus.FAILED
    assert second_controller.deployment_records[0].failure_reason
    assert changed.status == PolicyStatus.APPROVED


def test_new_version_replaces_only_same_policy_id_and_retains_history():
    registry = PolicyRegistry()
    deployment = controller(registry)
    v1 = candidate(1)
    v2 = candidate(
        2,
        allowed_destination=DestinationType.EMAIL_PROVIDER,
        required_purpose=Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL,
    )
    deployment.deploy(v1, approval(v1), Environment.DEVELOPMENT, operator())
    v2_record = deployment.deploy(v2, approval(v2), Environment.DEVELOPMENT, operator())

    assert v2_record.previous_active_policy_id == v1.policy_id
    assert v2_record.previous_active_policy_version == 1
    assert {item.version for item in registry.registered_policies()} == {1, 2}
    assert [(item.policy_id, item.version) for item in registry.active_policies()] == [
        ("FIN-POL-001", 2)
    ]
    assert registry.get("FIN-POL-001", 1).active is False


def test_runtime_gateway_enforces_only_after_deployment_and_keeps_refund_allowed():
    registry = PolicyRegistry()
    tools = FakeToolRegistry()
    before = invoke(
        registry, tools, "gmail.send", Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL
    )
    item = candidate()
    controller(registry).deploy(
        item, approval(item), Environment.DEVELOPMENT, operator()
    )
    after = invoke(
        registry, tools, "gmail.send", Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL
    )
    refund = invoke(
        registry, tools, "stripe.refund", Purpose.AUTHORIZED_FINANCIAL_TRANSACTION
    )

    assert before.decision.decision == Decision.ALLOW
    assert after.decision.decision == Decision.DENY
    assert len(tools.resolve("gmail.send").executions) == 1
    assert refund.decision.decision == Decision.ALLOW
    assert len(tools.resolve("stripe.refund").executions) == 1


def test_unauthorized_operator_is_rejected_without_runtime_change():
    registry = PolicyRegistry()
    item = candidate()
    deployment = controller(registry)

    with pytest.raises(DeploymentAuthorizationError, match="VIEWER"):
        deployment.deploy(
            item,
            approval(item),
            Environment.PRODUCTION,
            operator(DeploymentOperatorRole.VIEWER),
        )

    assert registry.registered_policies() == ()
    assert deployment.deployment_records[0].status == DeploymentStatus.FAILED


def test_active_new_version_rolls_back_to_retained_previous_runtime_behavior():
    registry = PolicyRegistry()
    tools = FakeToolRegistry()
    deployment = controller(registry)
    v1 = candidate(1)
    v2 = candidate(
        2,
        allowed_destination=DestinationType.EMAIL_PROVIDER,
        required_purpose=Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL,
    )
    deployment.deploy(v1, approval(v1), Environment.DEVELOPMENT, operator())
    v2_record = deployment.deploy(v2, approval(v2), Environment.DEVELOPMENT, operator())
    during_v2 = invoke(
        registry, tools, "gmail.send", Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL
    )

    rolled_back = deployment.rollback(v2_record.deployment_id, operator())
    after_rollback = invoke(
        registry, tools, "gmail.send", Purpose.CUSTOMER_REQUESTED_EXTERNAL_EMAIL
    )

    assert during_v2.decision.decision == Decision.ALLOW
    assert rolled_back.status == DeploymentStatus.ROLLED_BACK
    assert rolled_back.rolled_back_at == FIXED_TIME
    assert registry.get("FIN-POL-001", 2).active is False
    assert registry.get("FIN-POL-001", 1).active is True
    assert after_rollback.decision.decision == Decision.DENY
    assert {item.version for item in registry.registered_policies()} == {1, 2}


def test_rollback_without_previous_version_fails_explicitly():
    registry = PolicyRegistry()
    item = candidate()
    deployment = controller(registry)
    record = deployment.deploy(
        item, approval(item), Environment.DEVELOPMENT, operator()
    )

    with pytest.raises(RollbackError, match="no previous"):
        deployment.rollback(record.deployment_id, operator())

    assert registry.get(item.policy_id, item.version).active is True
    assert deployment.deployment_records[0].status == DeploymentStatus.ACTIVE
