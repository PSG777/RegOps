import logging

import pytest

from regops.config import GeminiBackend, require_gemini_api_key


GEMINI_ENVIRONMENT_VARIABLES = (
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_LOCATION",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
)


@pytest.fixture(autouse=True)
def clear_gemini_environment(monkeypatch):
    for variable in GEMINI_ENVIRONMENT_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


def test_vertex_mode_works_without_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")

    configuration = require_gemini_api_key()

    assert configuration.backend == GeminiBackend.VERTEX_AI
    assert configuration.project == "test-project"
    assert configuration.location == "global"


def test_vertex_mode_requires_project(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "global")

    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_PROJECT"):
        require_gemini_api_key()


def test_vertex_mode_requires_location(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "test-project")

    with pytest.raises(RuntimeError, match="GOOGLE_CLOUD_LOCATION"):
        require_gemini_api_key()


def test_developer_api_mode_works_with_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "false")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-secret-api-key")

    configuration = require_gemini_api_key()

    assert configuration.backend == GeminiBackend.DEVELOPER_API
    assert configuration.project is None
    assert configuration.location is None


def test_credentials_are_not_exposed_in_repr_or_logging(monkeypatch, caplog):
    api_key = "test-secret-api-key"
    monkeypatch.setenv("GOOGLE_API_KEY", api_key)

    configuration = require_gemini_api_key()
    with caplog.at_level(logging.INFO):
        logging.getLogger(__name__).info("Gemini configuration: %r", configuration)

    assert api_key not in repr(configuration)
    assert api_key not in caplog.text
