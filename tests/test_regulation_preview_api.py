import json
from hashlib import sha256

from fastapi.testclient import TestClient

from regops.api import create_app
from regops.cloud import LocalContentScreeningService
from regops.config import RegOpsConfiguration, RegOpsEnvironment
from regops.impact import ImpactAnalyzer
from regops.models import (
    ActionType,
    AgentManifest,
    DataClassification,
    DestinationType,
    Environment,
    Purpose,
)
from regops.policy_generation import (
    CandidatePolicyIdentity,
    PolicyGenerationAgent,
)
from regops.preview import RegulationAnalysisPreviewService
from regops.registry import InMemoryAgentRegistry
from regops.regulation_analysis import RegulationAnalysisAgent
from regops.test_generation import TestGenerationAgent as ComplianceTestGenerator
from regops.tools import FakeTool, FakeToolRegistry, ToolMetadata


TEXT = "Customer financial records may only be transmitted to an approved payment processor for an authorized financial transaction."


class StaticBoundary:
    def __init__(self, payload: dict):
        self.payload = payload

    async def generate(self, _request: str) -> str:
        return json.dumps(self.payload)


class FailingBoundary:
    async def generate(self, _request: str) -> str:
        raise ValueError("upstream model unavailable")


def preview_service(*, failing_analysis: bool = False):
    agents = InMemoryAgentRegistry()
    agents.register_agent(
        AgentManifest(
            agent_id="treasury-assistant",
            name="TreasuryAssistant",
            version="7.2.0",
            allowed_tools=frozenset({"secure.transfer", "external.message"}),
            data_access=frozenset({DataClassification.BANK_ACCOUNT}),
            owner="treasury-platform",
            environment=Environment.PRODUCTION,
        )
    )
    agents.register_agent(
        AgentManifest(
            agent_id="knowledge-assistant",
            name="KnowledgeAssistant",
            version="2.0.0",
            allowed_tools=frozenset(),
            data_access=frozenset({DataClassification.CUSTOMER_RECORD}),
            owner="knowledge-platform",
            environment=Environment.PRODUCTION,
        )
    )
    tools = FakeToolRegistry()
    tools.register(
        FakeTool(
            name="external.message",
            metadata=ToolMetadata(
                action_type=ActionType.TRANSMIT,
                destination_type=DestinationType.EMAIL_PROVIDER,
            ),
            result_factory=lambda _args: {},
        )
    )
    tools.register(
        FakeTool(
            name="secure.transfer",
            metadata=ToolMetadata(
                action_type=ActionType.TRANSMIT,
                destination_type=DestinationType.APPROVED_PAYMENT_PROCESSOR,
            ),
            result_factory=lambda _args: {},
        )
    )
    digest = sha256(TEXT.encode("utf-8")).hexdigest()[:12].upper()
    analysis_payload = {
        "requirement_id": "REQ-LIVE-001",
        "regulation_id": f"PREVIEW-REG-{digest}",
        "source_excerpt": TEXT,
        "data_classification": "BANK_ACCOUNT",
        "governed_action": "TRANSMIT",
        "allowed_destination": "APPROVED_PAYMENT_PROCESSOR",
        "required_purpose": "AUTHORIZED_FINANCIAL_TRANSACTION",
        "confidence": 0.97,
    }
    analyzer = RegulationAnalysisAgent(
        model_boundary=(
            FailingBoundary() if failing_analysis else StaticBoundary(analysis_payload)
        ),
        content_screening=LocalContentScreeningService(),
    )
    policy = PolicyGenerationAgent(
        model_boundary=StaticBoundary(
            {
                "requirement_id": "REQ-LIVE-001",
                "regulation_id": f"PREVIEW-REG-{digest}",
                "description": "Restrict financial transmissions to approved processing.",
                "effect": "DENY",
                "protected_classification": "BANK_ACCOUNT",
                "governed_action": "TRANSMIT",
                "allowed_destination": "APPROVED_PAYMENT_PROCESSOR",
                "required_purpose": "AUTHORIZED_FINANCIAL_TRANSACTION",
                "affected_agent_ids": ["treasury-assistant"],
            }
        ),
        identity=CandidatePolicyIdentity(policy_id="PREVIEW-CONTROL-001", version=1),
    )
    tests = ComplianceTestGenerator(
        agents,
        tools,
        model_boundary=StaticBoundary(
            {
                "scenarios": [
                    {
                        "category": "PROHIBITED",
                        "agent_id": "treasury-assistant",
                        "scenario": "Attempt to email protected financial data.",
                        "tool_name": "external.message",
                        "data_classifications": ["BANK_ACCOUNT"],
                        "purpose": "CUSTOMER_SUPPORT",
                        "tags": ["external"],
                    },
                    {
                        "category": "LEGITIMATE",
                        "agent_id": "treasury-assistant",
                        "scenario": "Send protected data to the approved processor.",
                        "tool_name": "secure.transfer",
                        "data_classifications": ["BANK_ACCOUNT"],
                        "purpose": "AUTHORIZED_FINANCIAL_TRANSACTION",
                        "tags": ["approved"],
                    },
                ]
            }
        ),
    )
    return RegulationAnalysisPreviewService(
        analyzer=analyzer,
        impact_analyzer=ImpactAnalyzer(agents, tools),
        policy_generator=policy,
        test_generator=tests,
    )


def client_for(service) -> TestClient:
    config = RegOpsConfiguration(
        environment=RegOpsEnvironment.LOCAL,
        frontend_origin="http://localhost:3000",
    )
    return TestClient(create_app(config, preview_service=service))


def test_empty_regulation_input_is_rejected():
    response = client_for(preview_service()).post(
        "/api/regulations/analyze", json={"text": "   "}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Regulation text must not be empty."}


def test_successful_pipeline_returns_typed_preview_and_completed_stages():
    response = client_for(preview_service()).post(
        "/api/regulations/analyze", json={"text": TEXT}
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["preview_only"] is True
    assert payload["regulation"]["source_text"] == TEXT
    assert payload["requirement"]["requirement_id"] == "REQ-LIVE-001"
    assert payload["input_screening"]["status"] == "PASSED"
    assert payload["candidate_policy"]["policy_id"] == "PREVIEW-CONTROL-001"
    assert payload["candidate_validation_status"] == "VALIDATED"
    assert len(payload["compliance_tests"]["test_cases"]) == 2
    assert len(payload["stages"]) == 8
    assert {stage["status"] for stage in payload["stages"]} == {"COMPLETED"}


def test_impact_comes_from_injected_authoritative_registry():
    payload = client_for(preview_service()).post(
        "/api/regulations/analyze", json={"text": TEXT}
    ).json()

    assert payload["analyzed_agent_count"] == 2
    assert payload["affected_agent_count"] == 1
    assert payload["affected_agents"] == ["treasury-assistant@7.2.0"]
    assert payload["unaffected_agents"] == ["knowledge-assistant@2.0.0"]
    assert {item["agent_id"] for item in payload["agent_impacts"]} == {
        "treasury-assistant",
        "knowledge-assistant",
    }
    assert payload["agent_impacts"][1]["capability_paths"][0]["tool_name"] == "external.message"


def test_preview_does_not_mutate_active_policy_or_invoke_tools():
    service = preview_service()
    client = client_for(service)
    before = client.get("/api/demo/dashboard").json()

    response = client.post("/api/regulations/analyze", json={"text": TEXT})
    after = client.get("/api/demo/dashboard").json()

    assert response.status_code == 200
    assert after["deployment"] == before["deployment"]
    assert after["candidate_policy"] == before["candidate_policy"]
    assert after["runtime"]["recent_decisions"] == before["runtime"]["recent_decisions"]
    assert all(
        not service.impact_analyzer._tool_registry.resolve(name).executions
        for name in ("external.message", "secure.transfer")
    )


def test_ai_failure_returns_error_without_seeded_demo_fallback():
    response = client_for(preview_service(failing_analysis=True)).post(
        "/api/regulations/analyze", json={"text": TEXT}
    )

    assert response.status_code == 422
    assert "interpretation or requirement validation failed" in response.json()["detail"]
    assert "FIN-REG-001" not in response.text
    assert "FIN-POL-001" not in response.text


def test_existing_runtime_endpoint_remains_deterministic():
    client = client_for(preview_service())

    denied = client.post("/api/demo/runtime/unsafe-email").json()
    allowed = client.post("/api/demo/runtime/refund").json()

    assert denied["decision"] == "DENY"
    assert denied["tool_executed"] is False
    assert allowed["decision"] == "ALLOW"
    assert allowed["tool_executed"] is True
