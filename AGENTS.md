# RegOps

RegOps is a hackathon project that acts as CI/CD for AI-agent compliance.

## Core architecture

RegOps has two planes:

1. Control Plane
   - interprets regulations
   - identifies affected agents
   - generates candidate policies
   - generates compliance tests
   - simulates policies
   - requires human approval before activation

2. Runtime Plane
   - intercepts agent tool calls
   - builds an ActionContext
   - evaluates active policies deterministically
   - allows or denies the tool call
   - records an audit event

## Critical design rules

- AI may interpret regulations and generate candidate policies.
- AI must never make the final runtime authorization decision.
- Runtime ALLOW/DENY decisions must be deterministic.
- Candidate policies cannot become active without approval.
- Agents must not bypass the runtime gateway to invoke tools directly.
- Keep the database as authoritative state; LLM memory is not authoritative.
- Prefer simple, explicit Python over unnecessary abstractions.
- Do not introduce distributed infrastructure until the local vertical slice works.

## Current milestone

Build only the local Runtime Plane.

Do NOT add yet:
- Gemini
- Google ADK
- Firestore
- Pub/Sub
- frontend
- Google Agent Registry
- Agent Gateway
- Model Armor

## Stack for current milestone

- Python 3.11+
- FastAPI
- Pydantic
- pytest

## Testing

Run:

pytest

Every feature should have tests.

The milestone is complete when the same prohibited tool action:
1. succeeds with no active policy
2. is denied after the relevant policy is activated

while a legitimate Stripe refund remains allowed.