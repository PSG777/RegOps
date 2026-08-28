# RegOps

RegOps is CI/CD for AI-agent compliance. The Python domain layer interprets,
validates, evaluates, approves, deploys, and deterministically enforces policy;
the local dashboard presents that authoritative state without duplicating rules.

## Local dashboard

Install the Python project and frontend dependencies, then use two terminals:

```powershell
python -m pip install -e ".[test]"
python -m uvicorn regops.api:app --reload --port 8000
```

```powershell
cd frontend
npm install
npm run dev
```

Open `http://localhost:3000`. The frontend defaults to
`http://localhost:8000`; copy `frontend/.env.example` to a local `.env.local`
only when a different API URL is needed.

The dashboard, reset, runtime actions, simulation evidence, and audit lineage
are deterministic and offline. They do not call Gemini or require Vertex AI.

Set `REGOPS_TELEMETRY_EXPORTER=console` before starting Uvicorn to print local
OpenTelemetry spans. The default exporter is no-op.
