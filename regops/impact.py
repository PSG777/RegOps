from typing import Protocol

from regops.models import (
    AgentImpact,
    AgentManifest,
    CapabilityPath,
    ImpactReport,
    ImpactStatus,
    Requirement,
    RiskSeverity,
)
from regops.registry import AgentRegistry
from regops.tools import ToolMetadata


class RegisteredTool(Protocol):
    metadata: ToolMetadata


class TrustedToolRegistry(Protocol):
    def resolve(self, name: str) -> RegisteredTool:
        """Resolve trusted intrinsic metadata for a registered tool."""


class ImpactAnalyzer:
    """Deterministic static capability analysis over trusted metadata."""

    def __init__(
        self, agent_registry: AgentRegistry, tool_registry: TrustedToolRegistry
    ) -> None:
        self._agent_registry = agent_registry
        self._tool_registry = tool_registry

    def analyze(self, requirement: Requirement) -> ImpactReport:
        manifests = sorted(
            self._agent_registry.list_agents(),
            key=lambda manifest: (manifest.agent_id, manifest.version),
        )
        impacts = tuple(
            self._analyze_agent(requirement, manifest) for manifest in manifests
        )
        return ImpactReport(
            requirement_id=requirement.requirement_id,
            analyzed_agent_count=len(impacts),
            affected_agents=self._identifiers(impacts, ImpactStatus.AFFECTED),
            not_affected_agents=self._identifiers(
                impacts, ImpactStatus.NOT_AFFECTED
            ),
            needs_review_agents=self._identifiers(
                impacts, ImpactStatus.NEEDS_REVIEW
            ),
            agent_impacts=impacts,
        )

    def _analyze_agent(
        self, requirement: Requirement, manifest: AgentManifest
    ) -> AgentImpact:
        if requirement.data_classification not in manifest.data_access:
            return self._impact(
                requirement,
                manifest,
                status=ImpactStatus.NOT_AFFECTED,
                severity=RiskSeverity.LOW,
                reasons=(
                    f"Agent cannot access {requirement.data_classification.value}.",
                ),
            )

        reasons = [
            f"Agent can access {requirement.data_classification.value}."
        ]
        risky_paths: list[CapabilityPath] = []
        allowed_destination_tools: list[str] = []
        unknown_metadata_tools: list[str] = []

        for tool_name in sorted(manifest.allowed_tools):
            metadata = self._resolve_metadata(tool_name)
            if metadata is None:
                unknown_metadata_tools.append(tool_name)
                continue
            if metadata.action_type != requirement.governed_action:
                continue
            if metadata.destination_type == requirement.allowed_destination:
                allowed_destination_tools.append(tool_name)
                continue
            risky_paths.append(
                CapabilityPath(
                    data_classification=requirement.data_classification,
                    agent_id=manifest.agent_id,
                    agent_version=manifest.version,
                    tool_name=tool_name,
                    action_type=metadata.action_type,
                    destination_type=metadata.destination_type,
                )
            )

        for path in risky_paths:
            reasons.append(
                f"{path.tool_name} performs {path.action_type.value} to "
                f"{path.destination_type.value}; the requirement permits only "
                f"{requirement.allowed_destination.value}."
            )
        if allowed_destination_tools:
            tool_names = ", ".join(allowed_destination_tools)
            reasons.append(
                f"Destination is permitted for {tool_names}, but invocation purpose "
                "must be evaluated at runtime."
            )
        if unknown_metadata_tools:
            reasons.append(
                "Trusted intrinsic metadata is unavailable or incomplete for: "
                + ", ".join(unknown_metadata_tools)
                + "."
            )

        if risky_paths:
            status = ImpactStatus.AFFECTED
            severity = RiskSeverity.HIGH
        elif unknown_metadata_tools or allowed_destination_tools:
            status = ImpactStatus.NEEDS_REVIEW
            severity = RiskSeverity.MEDIUM
        else:
            status = ImpactStatus.NOT_AFFECTED
            severity = RiskSeverity.LOW
            reasons.append(
                f"Agent has no known tool performing "
                f"{requirement.governed_action.value}."
            )

        return self._impact(
            requirement,
            manifest,
            status=status,
            severity=severity,
            reasons=tuple(reasons),
            risky_paths=tuple(risky_paths),
        )

    def _resolve_metadata(self, tool_name: str) -> ToolMetadata | None:
        try:
            tool = self._tool_registry.resolve(tool_name)
        except LookupError:
            return None
        metadata = getattr(tool, "metadata", None)
        if not isinstance(metadata, ToolMetadata):
            return None
        return metadata

    @staticmethod
    def _impact(
        requirement: Requirement,
        manifest: AgentManifest,
        *,
        status: ImpactStatus,
        severity: RiskSeverity,
        reasons: tuple[str, ...],
        risky_paths: tuple[CapabilityPath, ...] = (),
    ) -> AgentImpact:
        relevant = (
            frozenset({requirement.data_classification})
            if requirement.data_classification in manifest.data_access
            else frozenset()
        )
        return AgentImpact(
            requirement_id=requirement.requirement_id,
            agent_id=manifest.agent_id,
            agent_name=manifest.name,
            agent_version=manifest.version,
            status=status,
            severity=severity,
            relevant_data_classifications=relevant,
            risky_tools=tuple(path.tool_name for path in risky_paths),
            capability_paths=risky_paths,
            reasons=reasons,
        )

    @staticmethod
    def _identifiers(
        impacts: tuple[AgentImpact, ...], status: ImpactStatus
    ) -> tuple[str, ...]:
        return tuple(
            f"{impact.agent_id}@{impact.agent_version}"
            for impact in impacts
            if impact.status == status
        )
