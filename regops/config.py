import os
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv


GEMINI_MODEL = "gemini-3.5-flash"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


class GeminiBackend(str, Enum):
    VERTEX_AI = "vertex_ai"
    DEVELOPER_API = "developer_api"


@dataclass(frozen=True)
class GeminiConfiguration:
    """Non-secret description of the configured Gemini backend."""

    backend: GeminiBackend
    project: str | None = None
    location: str | None = None


def load_local_environment() -> None:
    load_dotenv()


def require_gemini_api_key() -> GeminiConfiguration:
    """Validate Gemini authentication settings without reading credentials.

    The historical function name is retained for existing demos. In Vertex AI
    mode, ADK uses Application Default Credentials and no API key is required.
    """

    use_vertex_ai = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower()
    if use_vertex_ai in _TRUE_VALUES:
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "").strip()
        if not project:
            raise RuntimeError(
                "Set GOOGLE_CLOUD_PROJECT when GOOGLE_GENAI_USE_VERTEXAI is true."
            )
        if not location:
            raise RuntimeError(
                "Set GOOGLE_CLOUD_LOCATION when GOOGLE_GENAI_USE_VERTEXAI is true."
            )
        return GeminiConfiguration(
            backend=GeminiBackend.VERTEX_AI,
            project=project,
            location=location,
        )

    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        raise RuntimeError(
            "Set GOOGLE_API_KEY in the environment or a local .env file."
        )
    return GeminiConfiguration(backend=GeminiBackend.DEVELOPER_API)


def gemini_configuration_available() -> bool:
    try:
        require_gemini_api_key()
    except RuntimeError:
        return False
    return True
