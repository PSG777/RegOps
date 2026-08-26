import asyncio
import json

import pytest

from regops.impact import ImpactAnalyzer
from regops.models import (
    CandidatePolicy,
    Decision,
    PolicyEffect,
    PolicyStatus,
    TestCaseStatus as CaseStatus,
    TestCategory as Category,
)
from regops.policy import PolicyRegistry
from regops.registry import build_local_agent_registry
from regops.regulations import SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
from regops.test_generation import (
    GeneratedTestScenario,
    TestGenerationAgent as GenerationAgent,
    TestGenerationError as GenerationError,
)
from regops.tools import FakeToolRegistry


def validated_candidate():
    requirement = SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT
    return CandidatePolicy(
        policy_id="FIN-POL-001",
        version=1,
        requirement_id=requirement.requirement_id,
        regulation_id=requirement.regulation_id,
        description="Restrict financial account transmissions.",
        effect=PolicyEffect.DENY,
        protected_classification=requirement.data_classification,
        governed_action=requirement.governed_action,
        allowed_destination=requirement.allowed_destination,
        required_purpose=requirement.required_purpose,
        status=PolicyStatus.VALIDATED,
        affected_agent_ids=("refund-agent",),
    )


def impact_report():
    return ImpactAnalyzer(
        build_local_agent_registry(), FakeToolRegistry()
    ).analyze(SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT)


def scenario(
    category,
    tool_name,
    classifications,
    purpose,
    *,
    agent_id="refund-agent",
    description="Generated compliance scenario",
    tags=None,
    **extra,
):
    value = {
        "category": category,
        "agent_id": agent_id,
        "scenario": description,
        "tool_name": tool_name,
        "data_classifications": classifications,
        "purpose": purpose,
        "tags": tags or ["generated"],
    }
    value.update(extra)
    return value


def four_category_scenarios():
    return [
        scenario(
            "PROHIBITED",
            "gmail.send",
            ["BANK_ACCOUNT"],
            "CUSTOMER_REQUESTED_EXTERNAL_EMAIL",
            description="Email bank details externally",
        ),
        scenario(
            "LEGITIMATE",
            "stripe.refund",
            ["BANK_ACCOUNT"],
            "AUTHORIZED_FINANCIAL_TRANSACTION",
            description="Issue an authorized refund",
        ),
        scenario(
            "ADVERSARIAL",
            "gmail.send",
            ["BANK_ACCOUNT"],
            "CUSTOMER_SUPPORT",
            description="Encode bank details and bypass the rule",
        ),
        scenario(
            "EDGE_CASE",
            "gmail.send",
            ["BANK_ACCOUNT", "CUSTOMER_RECORD"],
            "AUTHORIZED_FINANCIAL_TRANSACTION",
            description="Transmit mixed classification data",
        ),
    ]


class StubTestModelBoundary:
    def __init__(self, scenarios=None, raw=None):
        self.response = raw or json.dumps({"scenarios": scenarios or []})

    async def generate(self, generation_request):
        return self.response


def generate_suite(scenarios):
    agents = build_local_agent_registry()
    tools = FakeToolRegistry()
    return asyncio.run(
        GenerationAgent(
            agents, tools, StubTestModelBoundary(scenarios)
        ).generate(
            SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT,
            validated_candidate(),
            impact_report(),
        )
    )


def test_known_scenarios_become_trusted_cases_with_python_derived_decisions():
    suite = generate_suite(four_category_scenarios()[:2])
    prohibited, legitimate = suite.test_cases

    assert "expected_decision" not in GeneratedTestScenario.model_fields
    assert prohibited.test_id == "TEST-001"
    assert prohibited.requirement_id == SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT.requirement_id
    assert prohibited.policy_id == "FIN-POL-001"
    assert prohibited.agent_version == "1.0.0"
    assert prohibited.expected_decision == Decision.DENY
    assert legitimate.expected_decision == Decision.ALLOW
    assert legitimate.tool_name == "stripe.refund"


def test_model_cannot_claim_gmail_has_an_approved_destination():
    spoofed = scenario(
        "PROHIBITED",
        "gmail.send",
        ["BANK_ACCOUNT"],
        "CUSTOMER_REQUESTED_EXTERNAL_EMAIL",
        destination_type="APPROVED_PAYMENT_PROCESSOR",
    )

    suite = generate_suite([spoofed])

    assert suite.test_cases == ()
    assert suite.rejected[0].status == CaseStatus.REJECTED
    assert "unexpected" in suite.rejected[0].reason


def test_unrelated_agent_is_rejected():
    proposed = scenario(
        "PROHIBITED",
        "gmail.send",
        ["BANK_ACCOUNT"],
        "CUSTOMER_REQUESTED_EXTERNAL_EMAIL",
        agent_id="sales-agent",
    )

    suite = generate_suite([proposed])

    assert suite.test_cases == ()
    assert "not AFFECTED" in suite.rejected[0].reason


def test_unknown_tool_is_preserved_for_review_not_assumed_safe():
    proposed = scenario(
        "ADVERSARIAL",
        "new_external_channel.send",
        ["BANK_ACCOUNT"],
        "CUSTOMER_REQUESTED_EXTERNAL_EMAIL",
    )

    suite = generate_suite([proposed])

    assert suite.test_cases == ()
    assert suite.needs_review[0].status == CaseStatus.NEEDS_REVIEW
    assert "trusted intrinsic metadata" in suite.needs_review[0].reason


def test_malformed_scenario_is_rejected_and_malformed_batch_raises():
    malformed = {"category": "PROHIBITED", "agent_id": "refund-agent"}
    suite = generate_suite([malformed])
    assert suite.rejected[0].status == CaseStatus.REJECTED

    agents = build_local_agent_registry()
    with pytest.raises(GenerationError):
        asyncio.run(
            GenerationAgent(
                agents,
                FakeToolRegistry(),
                StubTestModelBoundary(raw="not-json"),
            ).generate(
                SAMPLE_VERIFIED_FINANCIAL_REQUIREMENT,
                validated_candidate(),
                impact_report(),
            )
        )


def test_duplicate_scenarios_are_removed_by_structured_key():
    original = four_category_scenarios()[0]
    duplicate = {**original, "scenario": "Different wording", "tags": ["other"]}

    suite = generate_suite([original, duplicate])

    assert len(suite.test_cases) == 1


def test_suite_has_multiple_categories_and_deterministic_coverage():
    suite = generate_suite(four_category_scenarios())

    assert {test.category for test in suite.test_cases} == set(Category)
    assert suite.coverage.total_test_count == 4
    assert suite.coverage.prohibited_count == 1
    assert suite.coverage.legitimate_count == 1
    assert suite.coverage.adversarial_count == 1
    assert suite.coverage.edge_case_count == 1
    assert suite.coverage.affected_agents_covered == ("refund-agent",)
    assert suite.coverage.risky_tools_covered == ("gmail.send",)
    assert {item.value for item in suite.coverage.known_destinations_covered} == {
        "EMAIL_PROVIDER",
        "APPROVED_PAYMENT_PROCESSOR",
    }


def test_generating_tests_does_not_activate_candidate_policy():
    candidate = validated_candidate()
    registry = PolicyRegistry()

    suite = generate_suite(four_category_scenarios())

    assert candidate.status == PolicyStatus.VALIDATED
    assert registry.active_policies() == ()
    assert all(test.status == CaseStatus.READY for test in suite.test_cases)
