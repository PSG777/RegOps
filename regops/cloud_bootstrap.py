"""Explicit, idempotent cloud checks and optional deterministic demo seeding."""

import argparse
from uuid import NAMESPACE_URL, uuid5

from regops.cloud import (
    FirestoreArtifactRepository,
    GoogleCloudAgentRegistry,
    GoogleModelArmorScreeningService,
    GooglePubSubEventBus,
    LifecycleEvent,
    LifecycleEventType,
    firestore_document_id,
)
from regops.config import RegOpsEnvironment, load_regops_configuration
from regops.demo_state import DemoState
from regops.registry import local_enterprise_manifests


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
    local_by_name = {item.name: item for item in local_enterprise_manifests()}
    discovered_names = {str(getattr(item, "display_name", "")) for item in remote_agents}
    missing_agents = sorted(set(local_by_name) - discovered_names)
    if missing_agents:
        raise SystemExit(
            "Create the missing Agent Registry demo entries first: "
            + ", ".join(missing_agents)
        )
    for remote in remote_agents:
        display_name = str(getattr(remote, "display_name", ""))
        manifest = local_by_name.get(display_name)
        if manifest is not None:
            if (
                str(getattr(remote, "agent_id", "")) != manifest.agent_id
                or str(getattr(remote, "version", "")) != manifest.version
            ):
                raise SystemExit(
                    f"Agent Registry identity/version mismatch for {display_name}."
                )
            document_id = firestore_document_id(str(remote.name))
            if not artifacts.exists("agent_manifests", document_id):
                artifacts.save("agent_manifests", document_id, manifest)

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
