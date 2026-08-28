import os
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv


GEMINI_MODEL = "gemini-3.5-flash"
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


class GeminiBackend(str, Enum):
    VERTEX_AI = "vertex_ai"
    DEVELOPER_API = "developer_api"


class RegOpsEnvironment(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"


@dataclass(frozen=True)
class GeminiConfiguration:
    """Non-secret description of the configured Gemini backend."""

    backend: GeminiBackend
    project: str | None = None
    location: str | None = None


@dataclass(frozen=True)
class RegOpsConfiguration:
    environment: RegOpsEnvironment
    frontend_origin: str
    project: str | None = None
    vertex_location: str | None = None
    firestore_database: str | None = None
    pubsub_topic: str | None = None
    model_armor_location: str | None = None
    model_armor_template: str | None = None
    agent_registry_location: str | None = None


def load_regops_configuration() -> RegOpsConfiguration:
    raw_environment = os.getenv("REGOPS_ENV", "local").strip().lower()
    try:
        environment = RegOpsEnvironment(raw_environment)
    except ValueError as error:
        raise RuntimeError("REGOPS_ENV must be local or cloud.") from error
    frontend_origin = os.getenv(
        "REGOPS_FRONTEND_ORIGIN", "http://localhost:3000"
    ).strip()
    if not frontend_origin or frontend_origin == "*":
        raise RuntimeError("REGOPS_FRONTEND_ORIGIN must be a specific origin.")
    if environment == RegOpsEnvironment.LOCAL:
        return RegOpsConfiguration(environment=environment, frontend_origin=frontend_origin)

    names = (
        "GOOGLE_CLOUD_PROJECT",
        "GOOGLE_CLOUD_LOCATION",
        "REGOPS_FIRESTORE_DATABASE",
        "REGOPS_PUBSUB_TOPIC",
        "REGOPS_MODEL_ARMOR_LOCATION",
        "REGOPS_MODEL_ARMOR_TEMPLATE",
        "REGOPS_AGENT_REGISTRY_LOCATION",
    )
    values = {name: os.getenv(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError(
            "Cloud configuration is missing: " + ", ".join(sorted(missing)) + "."
        )
    return RegOpsConfiguration(
        environment=environment,
        frontend_origin=frontend_origin,
        project=values["GOOGLE_CLOUD_PROJECT"],
        vertex_location=values["GOOGLE_CLOUD_LOCATION"],
        firestore_database=values["REGOPS_FIRESTORE_DATABASE"],
        pubsub_topic=values["REGOPS_PUBSUB_TOPIC"],
        model_armor_location=values["REGOPS_MODEL_ARMOR_LOCATION"],
        model_armor_template=values["REGOPS_MODEL_ARMOR_TEMPLATE"],
        agent_registry_location=values["REGOPS_AGENT_REGISTRY_LOCATION"],
    )


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
