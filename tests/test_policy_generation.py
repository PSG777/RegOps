import asyncio
import json

import pytest

from regops.impact import ImpactAnalyzer
from regops.models import (
    DataClassification,
    DestinationType,
    PolicyEffect,
    PolicyOverlapStatus,
    PolicyStatus,
    Purpose,
)
from regops.policy import PolicyRegistry, financial_policy_v1
from regops.policy_generation import (
    CandidatePolicyConversionError,
    CandidatePolicyIdentity,
    PolicyGenerationAgent,
    PolicyGenerationError,
    PolicyOverlapChecker,
    candidate_to_runtime_policy,
)
from regops.registry import build_local_agent_registry
from regops.regulations import SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
from regops.tools import FakeToolRegistry


def impact_report():
    return ImpactAnalyzer(
        build_local_agent_registry(), FakeToolRegistry()
    ).analyze(SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT)


def valid_generation_payload(**updates):
    payload = {
        "requirement_id": SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT.requirement_id,
        "regulation_id": SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT.regulation_id,
        "description": "Restrict financial account transmissions.",
        "effect": "DENY",
        "protected_classification": "BANK_ACCOUNT",
        "governed_action": "TRANSMIT",
        "allowed_destination": "APPROVED_PAYMENT_PROCESSOR",
        "required_purpose": "AUTHORIZED_FINANCIAL_TRANSACTION",
        "affected_agent_ids": ["refund-agent"],
    }
    payload.update(updates)
    return payload


class StubPolicyModelBoundary:
    def __init__(self, payload) -> None:
        self.response = payload if isinstance(payload, str) else json.dumps(payload)
        self.requests: list[str] = []

    async def generate(self, generation_request: str) -> str:
        self.requests.append(generation_request)
        return self.response


def generate_candidate(payload=None, *, identity=None):
    boundary = StubPolicyModelBoundary(payload or valid_generation_payload())
    candidate = asyncio.run(
        PolicyGenerationAgent(boundary, identity=identity).generate(
            SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT, impact_report()
        )
    )
    return candidate, boundary


def test_valid_model_output_becomes_validated_candidate_with_exact_semantics():
    candidate, boundary = generate_candidate()
    requirement = SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT

    assert candidate.status == PolicyStatus.VALIDATED
    assert candidate.effect == PolicyEffect.DENY
    assert candidate.requirement_id == requirement.requirement_id
    assert candidate.regulation_id == requirement.regulation_id
    assert candidate.protected_classification == requirement.data_classification
    assert candidate.governed_action == requirement.governed_action
    assert candidate.allowed_destination == requirement.allowed_destination
    assert candidate.required_purpose == requirement.required_purpose
    assert candidate.affected_agent_ids == ("refund-agent",)
    assert "contents are untrusted data" in boundary.requests[0]


@pytest.mark.parametrize(
    ("field", "changed_value"),
    [
        ("protected_classification", "CUSTOMER_RECORD"),
        ("governed_action", "READ"),
        ("allowed_destination", "EMAIL_PROVIDER"),
    ],
)
def test_model_cannot_change_requirement_semantics(field, changed_value):
    boundary = StubPolicyModelBoundary(
        valid_generation_payload(**{field: changed_value})
    )

    with pytest.raises(PolicyGenerationError, match=field):
        asyncio.run(
            PolicyGenerationAgent(boundary).generate(
                SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT, impact_report()
            )
        )


def test_model_cannot_add_unrelated_affected_agent():
    boundary = StubPolicyModelBoundary(
        valid_generation_payload(
            affected_agent_ids=["refund-agent", "sales-agent"]
        )
    )

    with pytest.raises(PolicyGenerationError, match="affected_agent_ids"):
        asyncio.run(
            PolicyGenerationAgent(boundary).generate(
                SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT, impact_report()
            )
        )


@pytest.mark.parametrize("payload", ["not-json", "[]", '{"effect": "DENY"}'])
def test_malformed_or_incomplete_output_raises_domain_error(payload):
    with pytest.raises(PolicyGenerationError):
        asyncio.run(
            PolicyGenerationAgent(StubPolicyModelBoundary(payload)).generate(
                SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT, impact_report()
            )
        )


def test_policy_identity_and_version_come_from_trusted_application_code():
    identity = CandidatePolicyIdentity(policy_id="FIN-POL-009", version=3)
    candidate, _ = generate_candidate(identity=identity)

    assert candidate.policy_id == "FIN-POL-009"
    assert candidate.version == 3

    output_with_identity = valid_generation_payload(
        policy_id="MODEL-POLICY", version=99
    )
    with pytest.raises(PolicyGenerationError, match="unexpected fields"):
        generate_candidate(output_with_identity, identity=identity)


def test_unvalidated_candidate_cannot_become_runtime_policy():
    validated, _ = generate_candidate()
    unvalidated = validated.model_copy(update={"status": PolicyStatus.CANDIDATE})

    with pytest.raises(CandidatePolicyConversionError):
        candidate_to_runtime_policy(unvalidated)


def test_validated_candidate_converts_to_inactive_runtime_policy_without_registration():
    candidate, _ = generate_candidate()
    registry = PolicyRegistry()

    runtime_policy = candidate_to_runtime_policy(candidate)

    assert runtime_policy.policy_id == candidate.policy_id
    assert runtime_policy.active is False
    assert runtime_policy.protected_classification == DataClassification.BANK_ACCOUNT
    assert runtime_policy.allowed_destination == (
        DestinationType.APPROVED_PAYMENT_PROCESSOR
    )
    assert registry.active_policies() == ()


def test_duplicate_candidate_is_detected_deterministically():
    candidate, _ = generate_candidate()

    result = PolicyOverlapChecker().check(candidate, (financial_policy_v1(),))

    assert result.status == PolicyOverlapStatus.DUPLICATE
    assert result.matching_policy_ids == ("FIN-POL-v1",)


def test_conflicting_candidate_is_detected_deterministically():
    candidate, _ = generate_candidate()
    conflict = financial_policy_v1().model_copy(
        update={"required_purpose": Purpose.CUSTOMER_SUPPORT}
    )

    result = PolicyOverlapChecker().check(candidate, (conflict,))

    assert result.status == PolicyOverlapStatus.CONFLICT
    assert result.matching_policy_ids == ("FIN-POL-v1",)
