"""Explicit, idempotent cloud checks and optional deterministic demo seeding."""

import argparse
from uuid import NAMESPACE_URL, uuid5

from regops.cloud import (
    ArtifactRepository,
    CloudAgentBinding,
    CloudInfrastructureError,
    FirestoreArtifactRepository,
    GoogleCloudAgentRegistry,
    GoogleModelArmorScreeningService,
    GooglePubSubEventBus,
    LifecycleEvent,
    LifecycleEventType,
    binding_from_remote,
    cloud_agent_binding_id,
    firestore_document_id,
)
from regops.config import RegOpsEnvironment, load_regops_configuration
from regops.demo_state import DemoState
from regops.registry import local_enterprise_manifests


def bootstrap_cloud_agent_bindings(
    remote_agents: tuple[object, ...],
    artifacts: ArtifactRepository,
) -> tuple[CloudAgentBinding, ...]:
    """Bind demo manifests once, then validate exact managed identity."""

    pending = []
    bindings = []
    missing = []
    for manifest in local_enterprise_manifests():
        binding_id = cloud_agent_binding_id(manifest.agent_id, manifest.version)
        display_matches = tuple(
            remote
            for remote in remote_agents
            if str(getattr(remote, "display_name", "")) == manifest.name
        )
        if artifacts.exists("cloud_agent_bindings", binding_id):
            binding = artifacts.load(
                "cloud_agent_bindings", binding_id, CloudAgentBinding
            )
            name_matches = tuple(
                remote
                for remote in remote_agents
                if str(getattr(remote, "name", "")) == binding.cloud_agent_name
            )
            if len(name_matches) > 1:
                raise CloudInfrastructureError(
                    f"Ambiguous bound Google Agent resource: {binding.cloud_agent_name}."
                )
            if not name_matches:
                id_matches = tuple(
                    remote
                    for remote in remote_agents
                    if str(getattr(remote, "agent_id", "")) == binding.cloud_agent_id
                )
                if id_matches:
                    raise CloudInfrastructureError(
                        f"Bound Google Agent resource name changed: {manifest.name}."
                    )
                raise CloudInfrastructureError(
                    f"Bound Google Agent is missing: {manifest.name}."
                )
            remote = name_matches[0]
            if str(getattr(remote, "agent_id", "")) != binding.cloud_agent_id:
                raise CloudInfrastructureError(
                    f"Bound Google Agent ID changed: {manifest.name}."
                )
        else:
            if not display_matches:
                missing.append(manifest.name)
                continue
            if len(display_matches) > 1:
                raise CloudInfrastructureError(
                    f"Ambiguous Google Agent display name: {manifest.name}."
                )
            remote = display_matches[0]
            binding = binding_from_remote(remote, manifest)
            manifest_document_id = firestore_document_id(binding.cloud_agent_name)
            if artifacts.exists("agent_manifests", manifest_document_id):
                stored_manifest = artifacts.load(
                    "agent_manifests", manifest_document_id, type(manifest)
                )
                if stored_manifest != manifest:
                    raise CloudInfrastructureError(
                        f"Conflicting RegOps manifest exists for {manifest.name}."
                    )
            pending.append((binding_id, manifest_document_id, manifest, binding))
        bindings.append(binding)
    if missing:
        raise CloudInfrastructureError(
            "Create the missing Agent Registry demo entries first: "
            + ", ".join(sorted(missing))
        )
    for binding_id, manifest_document_id, manifest, binding in pending:
        if not artifacts.exists("agent_manifests", manifest_document_id):
            artifacts.save("agent_manifests", manifest_document_id, manifest)
        artifacts.save("cloud_agent_bindings", binding_id, binding)
    return tuple(bindings)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-demo",
        action="store_true",
        help="Persist deterministic demo artifacts only when the case is absent.",
    )
    args = parser.parse_args()
    config = load_regops_configuration()
    if config.environment != RegOpsEnvironment.CLOUD:
        raise SystemExit("Set REGOPS_ENV=cloud before running cloud bootstrap.")

    artifacts = FirestoreArtifactRepository(
        config.project or "", config.firestore_database or ""
    )
    events = GooglePubSubEventBus(config.project or "", config.pubsub_topic or "")
    registry = GoogleCloudAgentRegistry(
        config.project or "", config.agent_registry_location or "", artifacts
    )
    artifacts.readiness()
    events.readiness()
    remote_agents = registry.remote_agents()
    try:
        bootstrap_cloud_agent_bindings(remote_agents, artifacts)
    except CloudInfrastructureError as error:
        raise SystemExit(str(error)) from error

    if args.seed_demo and not artifacts.exists("demo_cases", DemoState.case_id):
        state = DemoState()
        screening = GoogleModelArmorScreeningService(
            config.project or "",
            config.model_armor_location or "",
            config.model_armor_template or "",
        ).screen(state.regulation.source_text)
        snapshot = state.snapshot().model_copy(
            update={"input_screening": screening.status.value}
        )
        artifacts.save("regulations", state.regulation.regulation_id, state.regulation)
        artifacts.save("requirements", state.requirement.requirement_id, state.requirement)
        artifacts.save("impact_reports", state.requirement.requirement_id, state.impact)
        artifacts.save(
            "candidate_policies",
            f"{state.candidate.policy_id}-v{state.candidate.version}",
            state.candidate,
        )
        artifacts.save("test_suites", state.test_suite.suite_id, state.test_suite)
        artifacts.save("evaluation_reports", state.evaluation.evaluation_id, state.evaluation)
        artifacts.save("review_records", state.review.review_id, state.review)
        artifacts.save("deployment_records", state.deployment.deployment_id, state.deployment)
        for audit in state.gateway.audit_events:
            artifacts.save("audit_events", str(audit.event_id), audit)
        artifacts.save("demo_cases", DemoState.case_id, snapshot)
        lifecycle = (
            LifecycleEventType.REGULATION_ANALYZED,
            LifecycleEventType.IMPACT_ANALYZED,
            LifecycleEventType.POLICY_VALIDATED,
            LifecycleEventType.TEST_SUITE_CREATED,
            LifecycleEventType.EVALUATION_COMPLETED,
            LifecycleEventType.POLICY_APPROVED,
            LifecycleEventType.POLICY_DEPLOYED,
        )
        for event_type in lifecycle:
            events.publish(
                LifecycleEvent(
                    event_id=str(uuid5(NAMESPACE_URL, f"{DemoState.case_id}:{event_type}")),
                    event_type=event_type,
                    case_id=DemoState.case_id,
                    requirement_id=state.requirement.requirement_id,
                    policy_id=state.candidate.policy_id,
                    policy_version=state.candidate.version,
                    deployment_id=(
                        state.deployment.deployment_id
                        if event_type == LifecycleEventType.POLICY_DEPLOYED
                        else None
                    ),
                )
            )
        print(f"Seeded case {DemoState.case_id}.")
    else:
        print(
            f"Case {DemoState.case_id}: "
            + ("present" if artifacts.exists("demo_cases", DemoState.case_id) else "absent")
        )
    print(f"Discovered {len(remote_agents)} Agent Registry resource(s).")
    print("Firestore, Pub/Sub, Agent Registry, and Model Armor configuration verified.")


if __name__ == "__main__":
    main()
