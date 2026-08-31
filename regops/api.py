import logging
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from pydantic import BaseModel, ConfigDict, Field

from regops.application import (
    ApplicationServices,
    build_cloud_services,
    build_demo_state,
)
from regops.cloud import ContentScreeningError, LocalContentScreeningService
from regops.config import RegOpsConfiguration, load_regops_configuration
from regops.demo_state import DemoArtifactNotFoundError, DemoState
from regops.policy_generation import PolicyGenerationError
from regops.preview import (
    RegulationAnalysisPreview,
    RegulationAnalysisPreviewService,
    build_preview_service,
)
from regops.registry import AgentNotFoundError
from regops.regulation_analysis import RegulationAnalysisAgent, RegulationAnalysisError
from regops.telemetry import configure_telemetry
from regops.test_generation import TestGenerationError


logger = logging.getLogger(__name__)
configure_telemetry()


class AgentDiscoveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    name: str
    version: str
    status: Literal["AVAILABLE"] = "AVAILABLE"
    interface: Literal["HTTP_JSON"] = "HTTP_JSON"


class RegulationAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str = Field(min_length=1)


def create_app(
    configuration: RegOpsConfiguration | None = None,
    *,
    services: ApplicationServices | None = None,
    preview_service: RegulationAnalysisPreviewService | None = None,
) -> FastAPI:
    config = configuration or load_regops_configuration()
    resolved_services = services
    if config.environment.value == "cloud" and resolved_services is None:
        resolved_services = build_cloud_services(config)
    state = build_demo_state(config, services=resolved_services)
    screening = (
        resolved_services.screening
        if resolved_services is not None
        else LocalContentScreeningService()
    )
    analysis_preview = preview_service or build_preview_service(
        state.agents,
        state.tools,
        RegulationAnalysisAgent(content_screening=screening),
    )
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

    @application.get(
        "/api/agents/{agent_id}", response_model=AgentDiscoveryResponse
    )
    def discover_agent(agent_id: str) -> AgentDiscoveryResponse:
        try:
            manifest = state.agents.get_agent(agent_id)
        except AgentNotFoundError as error:
            raise HTTPException(
                status_code=404, detail="Agent is not available."
            ) from error

        return AgentDiscoveryResponse(
            agent_id=manifest.agent_id,
            name=manifest.name,
            version=manifest.version,
        )

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

    @application.post(
        "/api/regulations/analyze",
        response_model=RegulationAnalysisPreview,
    )
    async def analyze_regulation(
        request: RegulationAnalysisRequest,
    ) -> RegulationAnalysisPreview:
        if not request.text.strip():
            raise HTTPException(
                status_code=422,
                detail="Regulation text must not be empty.",
            )
        try:
            return await analysis_preview.analyze(request.text)
        except ContentScreeningError as error:
            raise HTTPException(
                status_code=400,
                detail=f"Input screening rejected the regulation: {error}",
            ) from error
        except RegulationAnalysisError as error:
            raise HTTPException(
                status_code=422,
                detail=f"Regulation interpretation or requirement validation failed: {error}",
            ) from error
        except PolicyGenerationError as error:
            raise HTTPException(
                status_code=422,
                detail=f"Candidate policy generation or validation failed: {error}",
            ) from error
        except TestGenerationError as error:
            raise HTTPException(
                status_code=422,
                detail=f"Compliance test generation or validation failed: {error}",
            ) from error

    logger.info(
        "RegOps application started",
        extra={"environment": config.environment.value},
    )
    return application


app = create_app()
demo_state: DemoState = app.state.demo_state
