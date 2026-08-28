# Final judge demo (3–5 minutes)

1. Open the financial regulation and point out Model Armor `Input screening: PASSED`.
2. Show the Gemini/ADK-extracted, typed requirement and its source evidence.
3. Show Enterprise Fleet from Agent Registry and RefundAgent as `AFFECTED`.
4. Show the candidate rule and the four legitimate/adversarial test categories.
5. Show compliance improvement, historical replay blast radius, and deterministic `PASS`.
6. Show the exact artifact fingerprint bound to Maya Chen's human approval.
7. Show the active deployment; explain that startup only reloads this persisted state.
8. Attempt the unsafe bank-data email. Show `DENY`, `tool_executed: NO`, and the audit ID.
9. Process the authorized Stripe refund. Show `ALLOW` and successful execution.
10. Click **Why was this blocked?** and trace policy → requirement → regulation.
11. Finish on the infrastructure panel: Vertex AI, Firestore, Pub/Sub, Agent Registry,
    Model Armor, Cloud Run, Cloud Logging, and OpenTelemetry.

The dashboard demo uses persisted/deterministic artifacts and makes no Gemini call,
so a temporary live-model outage does not interrupt the judging sequence.
