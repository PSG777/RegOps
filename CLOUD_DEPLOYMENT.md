# Google Cloud deployment

All application clients use Cloud Run service identity and Application Default
Credentials. Never download or mount a service-account JSON key.

Set operator-local placeholders:

```bash
export PROJECT_ID="your-project-id"
export REGION="us-central1"
export AR_REPOSITORY="regops"
export BACKEND_SERVICE="regops-api"
export FRONTEND_SERVICE="regops-dashboard"
export BACKEND_SA="regops-backend@${PROJECT_ID}.iam.gserviceaccount.com"
export PUBSUB_TOPIC="regops-lifecycle-events"
```

Enable APIs and create infrastructure manually:

```bash
gcloud services enable run.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com firestore.googleapis.com pubsub.googleapis.com logging.googleapis.com aiplatform.googleapis.com modelarmor.googleapis.com agentregistry.googleapis.com --project "$PROJECT_ID"
gcloud firestore databases create --database="(default)" --location="$REGION" --project "$PROJECT_ID"
gcloud pubsub topics create "$PUBSUB_TOPIC" --project "$PROJECT_ID"
gcloud artifacts repositories create "$AR_REPOSITORY" --repository-format=docker --location="$REGION" --project="$PROJECT_ID"
```

Create the Model Armor template with the current `gcloud model-armor` command for
the chosen region. Agent Registry registration follows the initial backend deploy
below because every Service requires a real interface URL.

On first bootstrap, each exact display name must resolve to exactly one generated
Agent. Bootstrap stores a validated cloud binding containing the exact Google
Agent name/ID and the corresponding RegOps ID/version. It also stores RegOps-specific
`allowed_tools`, `data_access`, owner, environment, and version metadata in
Firestore keyed by a SHA-256 hash of the Google Agent resource name. Subsequent
loads validate the immutable binding rather than trusting display name alone.

Grant the backend service account only the capabilities it needs: Firestore data
read/write, Pub/Sub publisher, Model Armor user, Agent Registry reader, Vertex AI
user, and Logs Writer. Use the narrow predefined/custom roles available in your
organization; do not grant Owner or Editor.

Build and deploy the backend initially in local mode. This makes the read-only
discovery interfaces available without requiring Agent Registry or Firestore at
application startup:

```bash
gcloud builds submit --tag "$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPOSITORY/backend:latest" --project "$PROJECT_ID" .
gcloud run deploy "$BACKEND_SERVICE" --image "$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPOSITORY/backend:latest" --region "$REGION" --service-account "$BACKEND_SA" --set-env-vars "REGOPS_ENV=local" --project "$PROJECT_ID"
export BACKEND_URL="$(gcloud run services describe "$BACKEND_SERVICE" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')"
```

Confirm that `BACKEND_URL` is the actual HTTPS URL returned by Cloud Run, then
register the discovery interfaces. Check first because `services create` is not
an upsert:

```bash
gcloud agent-registry services list --project "$PROJECT_ID" --location global --format="table(name,displayName)"
gcloud agent-registry services create refund-agent --project "$PROJECT_ID" --location global --display-name RefundAgent --description "RegOps demo refund agent" --agent-spec-type no-spec --interfaces "url=$BACKEND_URL/api/agents/refund-agent,protocolBinding=http-json"
gcloud agent-registry services create support-agent --project "$PROJECT_ID" --location global --display-name SupportAgent --description "RegOps demo support agent" --agent-spec-type no-spec --interfaces "url=$BACKEND_URL/api/agents/support-agent,protocolBinding=http-json"
gcloud agent-registry services create sales-agent --project "$PROJECT_ID" --location global --display-name SalesAgent --description "RegOps demo sales agent" --agent-spec-type no-spec --interfaces "url=$BACKEND_URL/api/agents/sales-agent,protocolBinding=http-json"
gcloud agent-registry agents list --project "$PROJECT_ID" --location global --format="table(name,agentId,displayName,version)"
```

These are `NO_SPEC` HTTP/JSON discovery interfaces. They expose sanitized
identity metadata only; they are not A2A registrations and do not claim that the
three agents can be invoked through Agent Registry. In particular, SupportAgent
and SalesAgent remain manifests without workflow implementations. The executable
RefundAgent demonstrations remain the RuntimeGateway-backed `/api/demo/runtime/*`
routes.

Google Agent Registry identity is distinct from RegOps logical identity. Google
owns the generated Agent resource `name` and globally unique `agentId`, and a
`NO_SPEC` Agent may have no cloud version. RegOps retains logical IDs such as
`refund-agent` and version `1.0.0` in its trusted `AgentManifest`.

Bootstrap is explicit and idempotent; it never deletes/reset data. Run it from an
ADC-authenticated operator environment (or a one-off Cloud Run job) after creating
the three Agent Registry Services:

```bash
REGOPS_ENV=cloud python -m regops.cloud_bootstrap --seed-demo
```

After bootstrap succeeds, update the existing backend service to cloud mode:

```bash
gcloud run services update "$BACKEND_SERVICE" --region "$REGION" --project "$PROJECT_ID" --set-env-vars "REGOPS_ENV=cloud,GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,GOOGLE_CLOUD_LOCATION=global,REGOPS_FIRESTORE_DATABASE=(default),REGOPS_PUBSUB_TOPIC=$PUBSUB_TOPIC,REGOPS_MODEL_ARMOR_LOCATION=$REGION,REGOPS_MODEL_ARMOR_TEMPLATE=regops-control-plane-screening,REGOPS_AGENT_REGISTRY_LOCATION=global"
```

Build the frontend with the public backend URL and deploy it, then update the
backend `REGOPS_FRONTEND_ORIGIN` to the exact frontend URL:

```bash
gcloud builds submit frontend --config frontend/cloudbuild.yaml --project "$PROJECT_ID" --substitutions "_REGION=$REGION,_REPOSITORY=$AR_REPOSITORY,_NEXT_PUBLIC_REGOPS_API_URL=$BACKEND_URL"
gcloud run deploy "$FRONTEND_SERVICE" --image "$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPOSITORY/frontend:latest" --region "$REGION" --project "$PROJECT_ID"
python -m regops.cloud_smoke "$BACKEND_URL"
```

The frontend API URL is compiled into the browser bundle. Rebuild the frontend
when the backend URL changes.

To demonstrate persistence, note the review/deployment IDs, deploy a new backend
revision (or scale to zero), reopen the dashboard, and verify the same IDs and
history. Cloud startup validates dependencies and loads `demo_cases/DEMO-FINANCIAL-001`;
it does not invoke Gemini, seed, approve, deploy, or overwrite history.

Run opt-in infrastructure checks only with configured ADC:

```bash
RUN_GCP_INTEGRATION_TESTS=1 python -m pytest -v -m integration
```

Agent Gateway and Agent Identity remain production mappings: verified identity
should resolve to the existing `AgentManifest`, and managed gateway traffic should
still pass through `RuntimeGateway`/`PolicyEngine`. They are intentionally deferred
until product provisioning and IAM can be validated without weakening the demo.
