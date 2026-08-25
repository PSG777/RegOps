from abc import ABC, abstractmethod

from regops.models import AgentManifest, DataClassification, Environment


class AgentNotFoundError(LookupError):
    pass


class AgentVersionNotFoundError(LookupError):
    pass


class AgentRegistry(ABC):
    """Authoritative source of versioned agent manifests."""

    @abstractmethod
    def register_agent(self, manifest: AgentManifest) -> None:
        """Register the first version of an agent."""

    @abstractmethod
    def get_agent(
        self, agent_id: str, version: str | None = None
    ) -> AgentManifest:
        """Retrieve a specific version, or the latest when omitted."""

    @abstractmethod
    def list_agents(self) -> tuple[AgentManifest, ...]:
        """List every retained agent version."""

    @abstractmethod
    def register_version(self, manifest: AgentManifest) -> None:
        """Register another version of an existing agent."""

    @abstractmethod
    def get_latest_agent(self, agent_id: str) -> AgentManifest:
        """Retrieve the most recently registered version of an agent."""


class InMemoryAgentRegistry(AgentRegistry):
    def __init__(self) -> None:
        self._manifests: dict[str, dict[str, AgentManifest]] = {}
        self._latest_versions: dict[str, str] = {}

    def register_agent(self, manifest: AgentManifest) -> None:
        if manifest.agent_id in self._manifests:
            raise ValueError(f"Agent already registered: {manifest.agent_id}")
        self._manifests[manifest.agent_id] = {}
        self._store(manifest)

    def get_agent(
        self, agent_id: str, version: str | None = None
    ) -> AgentManifest:
        if agent_id not in self._manifests:
            raise AgentNotFoundError(f"Agent is not registered: {agent_id}")
        if version is None:
            return self.get_latest_agent(agent_id)
        try:
            return self._manifests[agent_id][version].model_copy(deep=True)
        except KeyError as error:
            raise AgentVersionNotFoundError(
                f"Agent version is not registered: {agent_id}@{version}"
            ) from error

    def list_agents(self) -> tuple[AgentManifest, ...]:
        return tuple(
            manifest.model_copy(deep=True)
            for versions in self._manifests.values()
            for manifest in versions.values()
        )

    def register_version(self, manifest: AgentManifest) -> None:
        if manifest.agent_id not in self._manifests:
            raise AgentNotFoundError(
                f"Register the agent before adding versions: {manifest.agent_id}"
            )
        self._store(manifest)

    def get_latest_agent(self, agent_id: str) -> AgentManifest:
        if agent_id not in self._latest_versions:
            raise AgentNotFoundError(f"Agent is not registered: {agent_id}")
        return self.get_agent(agent_id, self._latest_versions[agent_id])

    def _store(self, manifest: AgentManifest) -> None:
        versions = self._manifests[manifest.agent_id]
        if manifest.version in versions:
            raise ValueError(
                f"Agent version already registered: "
                f"{manifest.agent_id}@{manifest.version}"
            )
        versions[manifest.version] = manifest.model_copy(deep=True)
        self._latest_versions[manifest.agent_id] = manifest.version


def local_enterprise_manifests() -> tuple[AgentManifest, ...]:
    return (
        AgentManifest(
            agent_id="refund-agent",
            name="RefundAgent",
            version="1.0.0",
            allowed_tools=frozenset(
                {"customer_db.read", "gmail.send", "stripe.refund"}
            ),
            data_access=frozenset(
                {DataClassification.BANK_ACCOUNT, DataClassification.CUSTOMER_RECORD}
            ),
            owner="payments-team",
            environment=Environment.PRODUCTION,
        ),
        AgentManifest(
            agent_id="support-agent",
            name="SupportAgent",
            version="1.0.0",
            allowed_tools=frozenset({"customer_db.read", "gmail.send"}),
            data_access=frozenset({DataClassification.CUSTOMER_RECORD}),
            owner="support-team",
            environment=Environment.PRODUCTION,
        ),
        AgentManifest(
            agent_id="sales-agent",
            name="SalesAgent",
            version="1.0.0",
            allowed_tools=frozenset({"gmail.send"}),
            data_access=frozenset({DataClassification.CUSTOMER_RECORD}),
            owner="sales-team",
            environment=Environment.PRODUCTION,
        ),
    )


def build_local_agent_registry() -> InMemoryAgentRegistry:
    registry = InMemoryAgentRegistry()
    for manifest in local_enterprise_manifests():
        registry.register_agent(manifest)
    return registry
