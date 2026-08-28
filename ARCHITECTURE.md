# RegOps architecture

```mermaid
flowchart TB
  subgraph CP[CONTROL PLANE — AI interprets]
    R[Regulation] --> MA[Model Armor]
    MA --> G[Gemini / Google ADK]
    G --> Q[Validated Requirement]
    Q --> I[Deterministic Impact Analysis]
    I <--> AR[Google Cloud Agent Registry]
    I --> P[Candidate Policy]
    P --> T[Compliance Tests]
    T --> S[Simulation / Historical Replay]
    S --> H[Human Approval]
    H --> D[Deployment]
  end
  subgraph RP[RUNTIME PLANE — deterministic software enforces]
    A[Enterprise Agent] --> RG[RuntimeGateway]
    RG --> PE[PolicyEngine]
    PE --> X{ALLOW / DENY}
    X --> ET[Enterprise Tool]
  end
  D --> C[Cached active runtime policy]
  C --> PE
  FS[(Firestore)] <--> CP
  PS[(Pub/Sub)] --- CP
  PS --- RG
  CL[Cloud Logging] --- CP
  CL --- RG
  OT[OpenTelemetry] --- CP
  OT --- RG
  CR[Cloud Run] --- CP
  CR --- RP
```

Firestore is authoritative for lifecycle history. A validated active policy is
loaded into the process-local `PolicyRegistry`; neither Firestore, Pub/Sub,
logging, nor tracing participates in a single `PolicyEngine` decision.
