"use client";

import { useState } from "react";
import { PageState, Status, useDashboard } from "@/components/regops";
import { api, LineageData, RuntimeDecision } from "@/lib/api";

export default function RuntimeMonitor() {
  const state = useDashboard();
  const [busy, setBusy] = useState<"unsafe" | "refund" | null>(null);
  const [result, setResult] = useState<RuntimeDecision | null>(null);
  const [lineage, setLineage] = useState<LineageData | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  if (!state.data) return <PageState error={state.error} retry={state.reload} />;
  const { data } = state;

  async function run(kind: "unsafe" | "refund") {
    setBusy(kind); setActionError(null); setLineage(null);
    try { const event = kind === "unsafe" ? await api.unsafeEmail() : await api.refund(); setResult(event); await state.reload(); }
    catch (err) { setActionError(err instanceof Error ? err.message : "Runtime action failed"); }
    finally { setBusy(null); }
  }
  async function explain(id: string) {
    setActionError(null);
    try { setLineage(await api.lineage(id)); }
    catch (err) { setActionError(err instanceof Error ? err.message : "Lineage unavailable"); }
  }

  return <main className="page runtime-page"><header className="page-title"><div><p className="eyebrow">Live enforcement</p><h1>Runtime Monitor</h1><p>Run real agent actions through the deterministic RuntimeGateway.</p></div><div className="active-policy"><span>Active policy</span><strong>{data.candidate_policy.policy_id} v{data.deployment.active_version}</strong></div></header>
    {actionError && <div className="alert" role="alert">{actionError}<button onClick={() => setActionError(null)}>Dismiss</button></div>}
    <section className="runtime-console"><div className="action-panel"><p className="eyebrow">Choose an agent action</p><h2>Test the active control</h2><p>These actions call the real backend. The browser does not decide whether a tool is allowed to execute.</p><button className="danger-action" disabled={busy !== null} onClick={() => void run("unsafe")}>{busy === "unsafe" ? "Attempting…" : "Attempt unsafe email"}<small>Send bank data through Gmail</small></button><button className="safe-action" disabled={busy !== null} onClick={() => void run("refund")}>{busy === "refund" ? "Processing…" : "Process authorized refund"}<small>Issue an approved Stripe refund</small></button></div>
      <div className={`decision-panel ${result ? result.decision.toLowerCase() : "empty"}`} aria-live="polite">{result ? <><div className="decision-title"><span className="verdict">{result.decision === "DENY" ? "BLOCKED" : "ALLOWED"}</span><code>{result.audit_event_id}</code></div><h2>{result.agent_id} <i>→</i> {result.tool_name}</h2><p className="action-route">{result.data_classifications.join(", ") || "No sensitive classification"} <i>→</i> {result.destination_type}</p><dl><div><dt>Decision</dt><dd>{result.decision}</dd></div><div><dt>Tool executed</dt><dd>{result.tool_executed ? "YES" : "NO"}</dd></div><div><dt>Policy</dt><dd>{result.policy_id ?? "No denying policy"}</dd></div><div><dt>Purpose</dt><dd>{result.purpose}</dd></div><div className="wide"><dt>Reason</dt><dd>{result.reason}</dd></div></dl>{result.decision === "DENY" && <button className="explain-button" onClick={() => void explain(result.audit_event_id)}>Why was this blocked? ↓</button>}</> : <div className="empty-decision"><span>READY</span><h2>No action selected</h2><p>Choose an action to see the runtime decision and execution evidence here.</p></div>}</div></section>
    {lineage && <section className="lineage-section"><div className="section-heading"><div><p className="eyebrow">Audit lineage</p><h2>Why was this blocked?</h2></div><button onClick={() => setLineage(null)}>Close</button></div><div className="lineage-chain"><article><span>Runtime action</span><strong>{lineage.action.agent_id} → {lineage.action.tool_name}</strong><p>{lineage.decision.decision}: {lineage.decision.reason}</p></article><i>↓</i><article><span>Runtime policy</span><strong>{lineage.runtime_policy.policy_id} v{lineage.runtime_policy.version}</strong><p>Approved under {lineage.approved_candidate.approval_review_id}</p></article><i>↓</i><article><span>Requirement</span><strong>{lineage.requirement.requirement_id}</strong><p>{lineage.explanation}</p></article><i>↓</i><article><span>Original regulation</span><strong>{lineage.regulation.title}</strong><p>“{lineage.regulation.source_evidence}”</p></article></div></section>}
    <section className="recent-decisions"><div className="section-heading"><div><p className="eyebrow">Audit stream</p><h2>Recent runtime decisions</h2></div><span>{data.runtime.recent_decisions.length} events</span></div>{data.runtime.recent_decisions.length ? <div className="decision-table">{data.runtime.recent_decisions.slice().reverse().map(item => <article key={item.audit_event_id}><Status tone={item.decision === "DENY" ? "risk" : "good"}>{item.decision}</Status><div><strong>{item.agent_id} → {item.tool_name}</strong><small>{item.destination_type} · {item.purpose}</small></div><span>{item.policy_id ?? "No policy"}</span><time>{new Date(item.occurred_at).toLocaleTimeString()}</time></article>)}</div> : <p className="empty-list">No runtime decisions recorded yet.</p>}</section>
  </main>;
}
