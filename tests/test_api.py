import json

import pytest
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from regops.api import app, demo_state
from regops.demo_state import DemoState
from regops.regulation_analysis import ADKRegulationModelBoundary
from regops.policy_generation import ADKPolicyGenerationModelBoundary
from regops.test_generation import ADKTestGenerationModelBoundary


@pytest.fixture(autouse=True)
def reset_demo_state():
    demo_state.reset()
    yield
    demo_state.reset()


@pytest.fixture
def client():
    return TestClient(app)


def test_health_endpoint_succeeds(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "regops-api"
    assert payload["infrastructure"]["environment"] == "local"
    assert payload["infrastructure"]["firestore"] == "in-memory"


@pytest.mark.parametrize(
    ("agent_id", "name"),
    [
        ("refund-agent", "RefundAgent"),
        ("support-agent", "SupportAgent"),
        ("sales-agent", "SalesAgent"),
    ],
)
def test_agent_discovery_resolves_authoritative_manifest(client, agent_id, name):
    response = client.get(f"/api/agents/{agent_id}")

    assert response.status_code == 200
    assert response.json() == {
        "agent_id": agent_id,
        "name": name,
        "version": "1.0.0",
        "status": "AVAILABLE",
        "interface": "HTTP_JSON",
    }


def test_agent_discovery_returns_safe_404_for_unknown_agent(client):
    response = client.get("/api/agents/not-present")

    assert response.status_code == 404
    assert response.json() == {"detail": "Agent is not available."}
    assert "not-present" not in response.text


def test_agent_discovery_performs_no_tool_execution_or_auditing(client):
    tool_names = ("customer_db.read", "gmail.send", "stripe.refund")
    executions_before = {
        name: len(demo_state.tools.resolve(name).executions) for name in tool_names
    }
    audits_before = len(demo_state.gateway.audit_events)

    for agent_id in ("refund-agent", "support-agent", "sales-agent"):
        assert client.get(f"/api/agents/{agent_id}").status_code == 200

    assert {
        name: len(demo_state.tools.resolve(name).executions) for name in tool_names
    } == executions_before
    assert len(demo_state.gateway.audit_events) == audits_before


def test_agent_discovery_exposes_only_sanitized_metadata(client, monkeypatch):
    secret = "agent-discovery-secret-value"
    monkeypatch.setenv("GOOGLE_API_KEY", secret)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "private-adc-file.json")

    response = client.get("/api/agents/refund-agent")
    serialized = response.text

    assert set(response.json()) == {
        "agent_id",
        "name",
        "version",
        "status",
        "interface",
    }
    assert secret not in serialized
    assert "private-adc-file.json" not in serialized
    assert "allowed_tools" not in serialized
    assert "data_access" not in serialized
    assert "arguments" not in serialized
    assert "merchant@example.com" not in serialized
    assert "****6789" not in serialized


def test_dashboard_returns_complete_structured_projection(client):
    response = client.get("/api/demo/dashboard")
    dashboard = response.json()

    assert response.status_code == 200
    assert dashboard["regulation"]["regulation_id"] == "FIN-REG-001"
    assert dashboard["regulation"]["requirement"]["requirement_id"] == "FIN-REQ-001"
    assert dashboard["impact"]["analyzed_agent_count"] == 3
    assert dashboard["candidate_policy"]["policy_id"] == "FIN-POL-001"
    assert dashboard["tests"]["total_count"] == 4
    assert dashboard["evaluation"]["status"] == "PASS"
    assert dashboard["review"]["decision"] == "APPROVE"
    assert dashboard["deployment"]["status"] == "ACTIVE"
    assert dashboard["runtime"]["recent_decisions"]
    assert dashboard["enterprise_fleet"]["registry_source"] == "InMemoryAgentRegistry"


def test_dashboard_composition_never_constructs_gemini_boundaries(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("Gemini boundary must not be constructed")

    monkeypatch.setattr(ADKRegulationModelBoundary, "__init__", fail)
    monkeypatch.setattr(ADKPolicyGenerationModelBoundary, "__init__", fail)
    monkeypatch.setattr(ADKTestGenerationModelBoundary, "__init__", fail)

    state = DemoState()

    assert state.dashboard()["evaluation"]["status"] == "PASS"


def test_unsafe_email_uses_gateway_denies_and_does_not_execute_gmail(client):
    executions_before = len(demo_state.tools.resolve("gmail.send").executions)

    response = client.post("/api/demo/runtime/unsafe-email")
    result = response.json()

    assert response.status_code == 200
    assert result["tool_name"] == "gmail.send"
    assert result["decision"] == "DENY"
    assert result["policy_id"] == "FIN-POL-001"
    assert result["tool_executed"] is False
    assert len(demo_state.tools.resolve("gmail.send").executions) == executions_before


def test_legitimate_refund_uses_gateway_and_executes_stripe(client):
    executions_before = len(demo_state.tools.resolve("stripe.refund").executions)

    result = client.post("/api/demo/runtime/refund").json()

    assert result["tool_name"] == "stripe.refund"
    assert result["decision"] == "ALLOW"
    assert result["tool_executed"] is True
    assert len(demo_state.tools.resolve("stripe.refund").executions) == executions_before + 1


def test_lineage_connects_sanitized_runtime_event_to_regulation(client):
    runtime = client.post("/api/demo/runtime/unsafe-email").json()

    response = client.get(
        f"/api/demo/lineage/{runtime['audit_event_id']}"
    )
    lineage = response.json()
    serialized = json.dumps(lineage)

    assert response.status_code == 200
    assert lineage["decision"]["decision"] == "DENY"
    assert lineage["runtime_policy"]["policy_id"] == "FIN-POL-001"
    assert lineage["runtime_policy"]["version"] == 1
    assert lineage["approved_candidate"]["approval_review_id"] == "REVIEW-DEMO-001"
    assert lineage["requirement"]["requirement_id"] == "FIN-REQ-001"
    assert lineage["regulation"]["regulation_id"] == "FIN-REG-001"
    assert "arguments" not in serialized.lower()
    assert "merchant@example.com" not in serialized
    assert "****6789" not in serialized


def test_missing_lineage_returns_safe_404(client):
    response = client.get("/api/demo/lineage/not-present")

    assert response.status_code == 404
    assert "not available" in response.json()["detail"]
    assert "traceback" not in response.text.lower()


def test_reset_restores_deterministic_active_demo_state(client):
    client.post("/api/demo/runtime/refund")
    assert len(demo_state.tools.resolve("stripe.refund").executions) == 2

    response = client.post("/api/demo/reset")

    assert response.json() == {"status": "reset", "case_id": "DEMO-FINANCIAL-001"}
    assert len(demo_state.tools.resolve("stripe.refund").executions) == 1
    assert demo_state.registry.active_policies()[0].version == 1


def test_api_responses_do_not_expose_credentials(client, monkeypatch):
    secret = "super-secret-browser-forbidden-value"
    monkeypatch.setenv("GOOGLE_API_KEY", secret)
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "private-adc-file.json")

    payload = client.get("/api/demo/dashboard").text

    assert secret not in payload
    assert "private-adc-file.json" not in payload
    assert "GOOGLE_API_KEY" not in payload
    assert "GOOGLE_APPLICATION_CREDENTIALS" not in payload


def test_cors_is_narrow_and_never_wildcard_credentialed():
    cors = next(
        item for item in app.user_middleware if item.cls is CORSMiddleware
    )

    assert cors.kwargs["allow_origins"] == ["http://localhost:3000"]
    assert "*" not in cors.kwargs["allow_origins"]
    assert cors.kwargs["allow_credentials"] is True
