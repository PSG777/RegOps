import os

from dotenv import load_dotenv


GEMINI_MODEL = "gemini-3.5-flash"


def load_local_environment() -> None:
    load_dotenv()


def require_gemini_api_key() -> None:
    if not (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")):
        raise RuntimeError(
            "Set GOOGLE_API_KEY in the environment or a local .env file."
        )
