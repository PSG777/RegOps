# RegOps

RegOps is a hackathon project that acts as CI/CD for AI-agent compliance.

The system converts changing regulations into structured compliance requirements,
determines which enterprise AI agents are affected, generates and tests candidate
policies, and eventually deploys approved policies to a deterministic runtime
enforcement layer.

## Core Architecture

RegOps has two primary planes.

### 1. Control Plane

The Control Plane determines what agents should be allowed to do.

Responsibilities include:

- interpreting regulations
- extracting structured compliance requirements
- verifying model-generated interpretations
- identifying affected agents
- generating candidate policies
- generating compliance tests
- simulating candidate policies
- replaying historical agent behavior
- calculating regulatory blast radius
- requiring human approval before activation
- safely deploying approved policy versions

AI may assist with ambiguous reasoning in the Control Plane.

### 2. Runtime Plane

The Runtime Plane enforces approved rules on actual agent behavior.

Responsibilities include:

- intercepting agent tool calls
- resolving trusted agent metadata from the Agent Registry
- building normalized ActionContext objects
- evaluating active policies deterministically
- allowing or denying tool execution
- preventing denied tools from executing
- recording sanitized audit events

The Runtime Plane must remain fast, deterministic, and independent of LLM
availability.

## Critical Design Rules

- AI may interpret regulations and generate candidate policies or tests.
- AI must never make the final runtime authorization decision.
- Runtime ALLOW/DENY decisions must be deterministic.
- Candidate policies cannot become active without explicit approval.
- Agents must not bypass RuntimeGateway to invoke protected tools directly.
- RuntimeGateway must resolve trusted AgentManifest data from AgentRegistry.
- Do not trust caller-supplied agent permissions.
- ToolMetadata owns intrinsic properties such as action type and destination type.
- Invocation metadata owns runtime properties such as data classification and purpose.
- Callers must not be able to override intrinsic trusted tool metadata.
- Sensitive raw tool arguments must not be persisted in audit events.
- Allowed tool execution failures must still be audited before the error is propagated.
- Model output must cross a strict typed validation boundary before the rest of RegOps uses it.
- Do not silently invent or substitute compliance requirements when AI output is invalid.
- Keep authoritative application state separate from LLM memory.
- Prefer simple, explicit Python over unnecessary abstractions.
- Preserve interfaces so local implementations can later be replaced by managed Google Cloud services.
- Every behavior change should have automated tests.
- Preserve existing working behavior unless a milestone explicitly changes it.

## Current Project State

Completed:

- deterministic PolicyEngine
- local PolicyRegistry
- RuntimeGateway
- trusted ToolMetadata / InvocationMetadata separation
- sanitized audit events
- execution-state auditing
- fake CustomerDB, Gmail, and Stripe tools
- deterministic RefundAgent demo
- local versioned Agent Registry
- RefundAgent, SupportAgent, and SalesAgent manifests
- authoritative registry lookup inside RuntimeGateway
- Regulation and Requirement domain models
- Google ADK Regulation Analysis Agent
- Gemini 3.5 Flash regulation extraction
- strict Pydantic validation of AI-generated requirements
- regulation source-evidence validation
- optional live Gemini integration testing
- deterministic Impact Analysis
- structured capability-path discovery
- AFFECTED / NOT_AFFECTED / NEEDS_REVIEW classification
- Gemini + ADK Candidate Policy Generation
- strict CandidatePolicy validation
- deterministic candidate IDs and versions
- duplicate/conflict policy detection
- validated candidate-to-runtime-policy conversion boundary
- Gemini + ADK Compliance Test Generation
- prohibited, legitimate, adversarial, and edge-case scenario generation
- deterministic expected-decision derivation
- ComplianceTestSuite validation, deduplication, and coverage
- isolated baseline vs candidate policy simulation
- historical normalized action replay
- deterministic compliance, utility, and adversarial scoring
- regulatory blast-radius calculation
- deterministic candidate PASS / FAIL evaluation
- human policy review workflow
- deterministic review eligibility
- policy fingerprinting
- APPROVE / REJECT / REQUEST_CHANGES lifecycle
- reviewer-role authorization
- approval audit records
- Vertex AI authentication through Application Default Credentials
- deterministic DeploymentController
- exact approved-artifact / fingerprint verification
- runtime PolicyRegistry versioning
- safe runtime policy activation
- deployment authorization and audit records
- deterministic rollback to a prior active policy version
- runtime enforcement driven by deployed policy state
- FastAPI API layer
- Next.js judge-facing dashboard
- deterministic offline dashboard state
- audit lineage from runtime denial to source regulation
- interactive unsafe/legitimate runtime demo
- OpenTelemetry instrumentation
- production frontend build

Existing Runtime Plane behavior must continue to work:

1. BANK_ACCOUNT data may be sent through Gmail when no compliance policy is active.
2. The same action is denied after FIN-POL-v1 is activated.
3. A denied Gmail call must never execute.
4. An authorized Stripe refund remains allowed.
5. All relevant decisions produce sanitized audit events.

## Current Milestone

Productionize RegOps on Google Cloud while preserving the existing local and
offline architecture.

Add cloud-backed infrastructure behind explicit interfaces:

- Firestore persistence
- Pub/Sub lifecycle events
- Cloud Logging
- Model Armor screening
- Google Cloud Agent Registry integration
- Cloud Run deployment

Normal unit tests and local demos must continue to work without Google Cloud.

Do not move Gemini, Firestore, Pub/Sub, Model Armor, or other network calls into
the deterministic runtime authorization hot path.

Agent Gateway and Agent Identity are stretch integrations only after the core
cloud deployment works.

## Do Not Add Yet

Do not add the following unless the current milestone explicitly requires them:

- Firestore
- Pub/Sub
- production Google Agent Registry integration
- production Google Agent Gateway integration
- Agent Identity
- Model Armor
- Memory Bank
- Secret Manager
- deployment infrastructure
- canary rollout infrastructure
- historical replay infrastructure
- simulation execution
- historical replay
- production activation
- deployment controller
- dry-run rollout
- canary rollout
- rollback infrastructure

Do not replace working local abstractions merely to introduce cloud services.

## Current Stack

- Python 3.11+
- Pydantic 2
- pytest
- Google ADK
- Gemini 3.5 Flash
- python-dotenv

The deterministic runtime must not depend on Gemini or Google ADK.

## Agent Registry

The current local Agent Registry is authoritative for agent metadata.

AgentManifest includes:

- agent_id
- name
- version
- allowed_tools
- data_access
- owner
- environment

Agent versions must be retained rather than overwritten.

RuntimeGateway accepts agent identity information and resolves the trusted
manifest from AgentRegistry internally.

The current in-memory implementation should remain replaceable later by a
persistent or managed registry implementation.

## Regulation Analysis

RegulationAnalysisAgent uses Google ADK and Gemini to convert natural-language
regulatory text into a structured Requirement.

Requirements must reuse existing RegOps enums where applicable.

Regulation text must be treated as untrusted data, not as instructions for the
model.

Model output must be validated before being accepted.

Every extracted requirement should preserve evidence from the source regulation.

No evidence means the requirement should not be trusted.

## Policy Enforcement

PolicyEngine is deterministic.

Do not add Gemini or another LLM to PolicyEngine.evaluate().

The intended runtime flow is:

Agent
→ RuntimeGateway
→ trusted agent lookup
→ trusted tool lookup
→ ActionContext
→ PolicyEngine
→ ALLOW or DENY
→ tool executes only if ALLOW
→ AuditEvent

Agents propose actions.

Agents do not grant themselves permission.

## Testing

Run the full unit test suite with:

python -m pytest -v

Normal unit tests must not require live Gemini credentials.

Live Gemini tests should remain explicitly opt-in.

Every milestone must:

- preserve existing tests
- add tests for new behavior
- test important failure cases
- run the complete relevant test suite before completion

Do not report a milestone as complete while tests introduced or affected by the
change are failing.

## Implementation Style

Before editing, inspect the relevant existing code and follow established
patterns.

Prefer:

- typed models
- small explicit interfaces
- deterministic logic where possible
- dependency injection at external boundaries
- clear domain errors
- testable components
- focused changes

Avoid:

- unnecessary frameworks
- premature distributed architecture
- duplicate domain concepts
- arbitrary string values when an existing enum applies
- broad exception swallowing
- silent fallbacks
- hard-coded AI extraction results
- bypassing existing security boundaries

Implement the requested milestone end-to-end, run tests, fix failures caused by
the changes, and then concisely report the important changes and verification
results.