from dataclasses import dataclass
from hashlib import sha256
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from regops.cloud import ScreeningResult
from regops.impact import ImpactAnalyzer, TrustedToolRegistry
from regops.models import (
    AgentImpact,
    CandidatePolicy,
    ComplianceTestSuite,
    ImpactReport,
    Regulation,
    Requirement,
)
from regops.policy_generation import (
    CandidatePolicyIdentity,
    PolicyGenerationAgent,
)
from regops.registry import AgentRegistry
from regops.regulation_analysis import RegulationAnalysisAgent
from regops.test_generation import TestGenerationAgent


class RegulationAnalyzer(Protocol):
    async def analyze_with_screening(
        self, regulation: Regulation
    ) -> tuple[ScreeningResult, Requirement]: ...


class CandidateGenerator(Protocol):
    async def generate(
        self, requirement: Requirement, impact_report: ImpactReport
    ) -> CandidatePolicy: ...


class ComplianceTestGenerator(Protocol):
    async def generate(
        self,
        requirement: Requirement,
        candidate: CandidatePolicy,
        impact_report: ImpactReport,
    ) -> ComplianceTestSuite: ...


class AnalysisStageStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: Literal[
        "INPUT_SCREENING",
        "REGULATION_INTERPRETATION",
        "REQUIREMENT_VALIDATION",
        "FLEET_IMPACT_ANALYSIS",
        "CANDIDATE_POLICY_GENERATION",
        "CANDIDATE_POLICY_VALIDATION",
        "COMPLIANCE_TEST_GENERATION",
        "COMPLIANCE_TEST_VALIDATION",
    ]
    status: Literal["COMPLETED"] = "COMPLETED"


class RegulationAnalysisPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    preview_only: Literal[True] = True
    regulation: Regulation
    requirement: Requirement
    input_screening: ScreeningResult
    analyzed_agent_count: int = Field(ge=0)
    affected_agent_count: int = Field(ge=0)
    affected_agents: tuple[str, ...]
    unaffected_agents: tuple[str, ...]
    needs_review_agents: tuple[str, ...]
    agent_impacts: tuple[AgentImpact, ...]
    candidate_policy: CandidatePolicy
    candidate_validation_status: Literal["VALIDATED"] = "VALIDATED"
    compliance_tests: ComplianceTestSuite
    stages: tuple[AnalysisStageStatus, ...]


@dataclass(frozen=True)
class RegulationAnalysisPreviewService:
    analyzer: RegulationAnalyzer
    impact_analyzer: ImpactAnalyzer
    policy_generator: CandidateGenerator
    test_generator: ComplianceTestGenerator

    async def analyze(self, text: str) -> RegulationAnalysisPreview:
        normalized = text.strip()
        if not normalized:
            raise ValueError("Regulation text must not be empty.")

        digest = sha256(normalized.encode("utf-8")).hexdigest()[:12].upper()
        regulation = Regulation(
            regulation_id=f"PREVIEW-REG-{digest}",
            title="Live regulation analysis preview",
            source_text=text,
            version="preview",
        )
        screening, requirement = await self.analyzer.analyze_with_screening(regulation)
        impact = self.impact_analyzer.analyze(requirement)
        candidate = await self.policy_generator.generate(requirement, impact)
        tests = await self.test_generator.generate(requirement, candidate, impact)
        stages = tuple(
            AnalysisStageStatus(stage=stage)
            for stage in (
                "INPUT_SCREENING",
                "REGULATION_INTERPRETATION",
                "REQUIREMENT_VALIDATION",
                "FLEET_IMPACT_ANALYSIS",
                "CANDIDATE_POLICY_GENERATION",
                "CANDIDATE_POLICY_VALIDATION",
                "COMPLIANCE_TEST_GENERATION",
                "COMPLIANCE_TEST_VALIDATION",
            )
        )
        return RegulationAnalysisPreview(
            regulation=regulation,
            requirement=requirement,
            input_screening=screening,
            analyzed_agent_count=impact.analyzed_agent_count,
            affected_agent_count=len(impact.affected_agents),
            affected_agents=impact.affected_agents,
            unaffected_agents=impact.not_affected_agents,
            needs_review_agents=impact.needs_review_agents,
            agent_impacts=impact.agent_impacts,
            candidate_policy=candidate,
            compliance_tests=tests,
            stages=stages,
        )


def build_preview_service(
    agents: AgentRegistry,
    tools: TrustedToolRegistry,
    analyzer: RegulationAnalysisAgent,
) -> RegulationAnalysisPreviewService:
    digest_identity = CandidatePolicyIdentity(policy_id="PREVIEW-POLICY", version=1)
    return RegulationAnalysisPreviewService(
        analyzer=analyzer,
        impact_analyzer=ImpactAnalyzer(agents, tools),
        policy_generator=PolicyGenerationAgent(identity=digest_identity),
        test_generator=TestGenerationAgent(agents, tools),
    )
