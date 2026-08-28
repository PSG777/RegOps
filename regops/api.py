import logging
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from regops.demo_state import DemoArtifactNotFoundError, DemoState
from regops.telemetry import configure_telemetry


logger = logging.getLogger(__name__)
configure_telemetry()

app = FastAPI(title="RegOps API", version="0.1.0")
cors_origins = tuple(
    origin.strip()
    for origin in os.getenv("REGOPS_CORS_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip() and origin.strip() != "*"
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)
FastAPIInstrumentor.instrument_app(app)

demo_state = DemoState()


@app.exception_handler(DemoArtifactNotFoundError)
async def missing_artifact_handler(
    _request: Request, error: DemoArtifactNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(error)})


@app.exception_handler(Exception)
async def unexpected_error_handler(_request: Request, error: Exception) -> JSONResponse:
    logger.exception("Unexpected RegOps API error", exc_info=error)
    return JSONResponse(
        status_code=500,
        content={"detail": "The RegOps API could not complete the request."},
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "regops-api"}


@app.get("/api/demo/dashboard")
def dashboard() -> dict[str, Any]:
    return demo_state.dashboard()


@app.post("/api/demo/runtime/unsafe-email")
def unsafe_email() -> dict[str, Any]:
    return demo_state.run_unsafe_email()


@app.post("/api/demo/runtime/refund")
def refund() -> dict[str, Any]:
    return demo_state.run_refund()


@app.post("/api/demo/reset")
def reset() -> dict[str, Any]:
    return demo_state.reset()


@app.get("/api/demo/lineage/{audit_event_id}")
def lineage(audit_event_id: str) -> dict[str, Any]:
    return demo_state.lineage(audit_event_id)
