import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from regops.application import ApplicationServices, build_demo_state
from regops.config import RegOpsConfiguration, load_regops_configuration
from regops.demo_state import DemoArtifactNotFoundError, DemoState
from regops.telemetry import configure_telemetry


logger = logging.getLogger(__name__)
configure_telemetry()


def create_app(
    configuration: RegOpsConfiguration | None = None,
    *,
    services: ApplicationServices | None = None,
) -> FastAPI:
    config = configuration or load_regops_configuration()
    state = build_demo_state(config, services=services)
    application = FastAPI(title="RegOps API", version="0.1.0")
    application.state.demo_state = state
    application.state.configuration = config
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[config.frontend_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "Accept"],
    )
    FastAPIInstrumentor.instrument_app(application)

    @application.exception_handler(DemoArtifactNotFoundError)
    async def missing_artifact_handler(
        _request: Request, error: DemoArtifactNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @application.exception_handler(Exception)
    async def unexpected_error_handler(
        _request: Request, error: Exception
    ) -> JSONResponse:
        logger.exception("Unexpected RegOps API error", exc_info=error)
        return JSONResponse(
            status_code=500,
            content={"detail": "The RegOps API could not complete the request."},
        )

    @application.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "service": "regops-api",
            "infrastructure": state.infrastructure.model_dump(mode="json"),
        }

    @application.get("/api/demo/dashboard")
    def dashboard() -> dict[str, Any]:
        return state.dashboard()

    @application.post("/api/demo/runtime/unsafe-email")
    def unsafe_email() -> dict[str, Any]:
        return state.run_unsafe_email()

    @application.post("/api/demo/runtime/refund")
    def refund() -> dict[str, Any]:
        return state.run_refund()

    @application.post("/api/demo/reset")
    def reset() -> dict[str, Any]:
        return state.reset()

    @application.get("/api/demo/lineage/{audit_event_id}")
    def lineage(audit_event_id: str) -> dict[str, Any]:
        return state.lineage(audit_event_id)

    logger.info(
        "RegOps application started",
        extra={"environment": config.environment.value},
    )
    return application


app = create_app()
demo_state: DemoState = app.state.demo_state
