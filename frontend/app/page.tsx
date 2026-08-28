"use client";

import { useCallback, useEffect, useState } from "react";
import { api, DashboardData, LineageData, RuntimeDecision } from "@/lib/api";

const percent = (value: number) => `${Math.round(value * 100)}%`;
const shortHash = (value: string) => `${value.slice(0, 12)}…${value.slice(-6)}`;

function Status({ children, tone = "neutral" }: { children: React.ReactNode; tone?: string }) {
  return <span className={`status status-${tone}`}>{children}</span>;
}

function Score({ label, baseline, candidate, percentValue = true }: { label: string; baseline: number; candidate: number; percentValue?: boolean }) {
  const format = (value: number) => percentValue ? percent(value) : value;
  return (
    <div className="score">
      <span>{label}</span>
      <strong><del>{format(baseline)}</del><i aria-hidden="true">→</i>{format(candidate)}</strong>
    </div>
  );
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [result, setResult] = useState<RuntimeDecision | null>(null);
  const [lineage, setLineage] = useState<LineageData | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try { setData(await api.dashboard()); }
    catch (err) { setError(err instanceof Error ? err.message : "Dashboard unavailable"); }
  }, []);

  useEffect(() => {
    let active = true;
    api.dashboard().then(
      (dashboard) => { if (active) setData(dashboard); },
      (err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : "Dashboard unavailable");
      },
    );
    return () => { active = false; };
  }, []);

  async function run(kind: "unsafe" | "refund") {
    setBusy(kind); setError(null); setLineage(null);
    try {
      const event = kind === "unsafe" ? await api.unsafeEmail() : await api.refund();
      setResult(event); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Action failed"); }
    finally { setBusy(null); }
  }

  async function reset() {
    setBusy("reset"); setResult(null); setLineage(null); setError(null);
    try { await api.reset(); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Reset failed"); }
    finally { setBusy(null); }
  }

  async function showLineage(auditId: string) {
    setError(null);
    try { setLineage(await api.lineage(auditId)); }
    catch (err) { setError(err instanceof Error ? err.message : "Lineage unavailable"); }
  }

  if (!data && !error) return <main className="loading"><p>Loading authoritative RegOps state…</p></main>;
  if (!data) return <main className="loading"><div className="error"><strong>API connection failed</strong><p>{error}</p><button onClick={() => void load()}>Retry</button></div></main>;

  const p = data.candidate_policy;
  const replay = data.evaluation.replay;
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand"><span className="mark">RO</span><div><b>RegOps</b><small>Regulatory operations control room</small></div></div>
        <div className="topmeta"><span className="live-dot" /> {data.infrastructure.environment} deterministic runtime <button className="text-button" onClick={() => void reset()} disabled={busy !== null || data.infrastructure.environment === "cloud"}>Reset demo</button></div>
      </header>

      <main>
        {error && <div className="error banner" role="alert"><strong>Request failed:</strong> {error} <button onClick={() => setError(null)}>Dismiss</button></div>}
        <section className="brief">
          <div><p className="eyebrow">Case {data.case_id}</p><h1>Financial data transmission control</h1><p>One changing rule. Three enterprise agents. A policy promoted only after evidence, simulation, and human approval.</p></div>
          <div className="brief-stats"><div><span>Affected fleet</span><strong>{data.impact.affected_agent_count}<small> / {data.impact.analyzed_agent_count}</small></strong></div><div><span>Evaluation</span><strong className="good">{data.evaluation.status}</strong></div><div><span>Runtime</span><strong>{data.deployment.status}</strong></div></div>
        </section>

        <nav className="pipeline" aria-label="Compliance delivery pipeline">
          {data.pipeline.map((item, index) => <div key={item.stage} className="pipeline-step"><span>{String(index + 1).padStart(2, "0")}</span><b>{item.stage}</b><small>{item.status}</small></div>)}
        </nav>

        <section className="metrics" aria-label="Evaluation scorecard">
          <Score label="Compliance" {...data.evaluation.compliance} />
          <Score label="Utility retained" {...data.evaluation.utility} />
          <Score label="Adversarial robustness" {...data.evaluation.adversarial} />
          <Score label="Critical violations" {...data.evaluation.critical_violations} percentValue={false} />
          <div className="score blast"><span>Operational blast radius</span><strong>{percent(data.evaluation.blast_radius)}</strong><small>{replay.newly_denied} of {replay.total_actions} historical actions change</small></div>
        </section>

        <section className="panel infrastructure">
          <header><div><p className="eyebrow">Production infrastructure</p><h2>Cloud readiness & enterprise fleet</h2></div><Status tone="good">{data.infrastructure.environment.toUpperCase()}</Status></header>
          <div className="infra-grid">{[
            ["Vertex AI", data.infrastructure.vertex],
            ["Firestore", data.infrastructure.firestore],
            ["Pub/Sub", data.infrastructure.pubsub],
            ["Agent Registry", data.infrastructure.agent_registry],
            ["Model Armor", data.infrastructure.model_armor],
            ["Runtime", data.infrastructure.runtime],
          ].map(([name, status]) => <div key={name}><span>{name}</span><strong>{status}</strong></div>)}</div>
          <div className="fleet-evidence"><p>Registry source: <b>{data.enterprise_fleet.registry_source}</b> · Input screening: <b>{data.infrastructure.input_screening}</b></p>{data.enterprise_fleet.agents.map(agent => <code key={`${agent.agent_id}-${agent.version}`}>{agent.name} v{agent.version} {agent.status}</code>)}</div>
        </section>

        <div className="grid-main">
          <section className="panel regulation-panel">
            <header><div><p className="eyebrow">01 / Source authority</p><h2>{data.regulation.title}</h2></div><code>{data.regulation.regulation_id} · v{data.regulation.version}</code></header>
            <blockquote>“{data.regulation.source_text}”</blockquote>
            <div className="requirement-grid"><div><span>Protected data</span><b>{data.regulation.requirement.data_classification}</b></div><div><span>Governed action</span><b>{data.regulation.requirement.governed_action}</b></div><div><span>Allowed destination</span><b>{data.regulation.requirement.allowed_destination}</b></div><div><span>Required purpose</span><b>{data.regulation.requirement.required_purpose}</b></div></div>
          </section>

          <section className="panel policy-panel">
            <header><div><p className="eyebrow">03 / Enforceable artifact</p><h2>Candidate policy</h2></div><Status tone="good">{p.runtime_status}</Status></header>
            <div className="policy-id"><code>{p.policy_id} v{p.version}</code><small title={p.fingerprint}>{shortHash(p.fingerprint)}</small></div>
            <div className="policy-rule"><span>PROTECT</span><strong>{p.protected_classification}</strong><span>WHEN</span><strong>{p.governed_action}</strong><span>ALLOW ONLY WHEN</span><strong>destination = {p.allowed_destination}<br />purpose = {p.required_purpose}</strong><span>OTHERWISE</span><strong className="deny">DENY</strong></div>
            <p className="artifact-chain">AI generated <b>→</b> Python validated <b>→</b> Simulation passed <b>→</b> Human approved <b>→</b> Deployed</p>
          </section>
        </div>

        <section className="panel fleet">
          <header><div><p className="eyebrow">02 / Regulatory blast surface</p><h2>Agent fleet impact</h2></div><span>{data.impact.analyzed_agent_count} registered agents</span></header>
          <div className="agent-grid">{data.impact.agents.map(agent => <article key={agent.agent_id} className={agent.status === "AFFECTED" ? "agent affected" : "agent"}><div className="agent-title"><div><h3>{agent.agent_name}</h3><code>{agent.agent_id}@{agent.agent_version}</code></div><Status tone={agent.status === "AFFECTED" ? "risk" : agent.status === "NEEDS_REVIEW" ? "warn" : "neutral"}>{agent.status}</Status></div><p><b>{agent.severity}</b> severity · {agent.relevant_data_classifications.join(", ") || "No governed data"}</p>{agent.capability_paths.map(path => <div className="capability" key={path.tool_name}><span>{path.data_classification}</span><i>→</i><span>{agent.agent_name}</span><i>→</i><span>{path.tool_name}</span><i>→</i><span>{path.destination_type}</span></div>)}<small>{agent.reasons[0]}</small></article>)}</div>
        </section>

        <div className="grid-main lower">
          <section className="panel tests-panel"><header><div><p className="eyebrow">04 / Generated evidence</p><h2>Compliance test suite</h2></div><div><Status tone="good">{data.tests.ready_count} READY</Status> <Status tone="warn">{data.tests.needs_review_count} REVIEW</Status></div></header><div className="test-counts">{Object.entries(data.tests.category_counts).map(([name, count]) => <div key={name}><strong>{count}</strong><span>{name}</span></div>)}</div><div className="test-list">{data.tests.representative_cases.map(test => <article key={test.test_id}><Status tone={test.expected_decision === "DENY" ? "risk" : "good"}>{test.expected_decision}</Status><div><code>{test.test_id} · {test.category}</code><p>{test.scenario}</p><small>{test.agent_id} → {test.tool_name}</small></div></article>)}</div></section>

          <section className="panel evidence-panel"><header><div><p className="eyebrow">05–07 / Governance evidence</p><h2>Approval & deployment</h2></div><Status tone="good">BOUND</Status></header><dl><div><dt>Human reviewer</dt><dd>{data.review.reviewer.display_name}<small>{data.review.reviewer.role}</small></dd></div><div><dt>Decision</dt><dd className="good">{data.review.decision}<small>{new Date(data.review.reviewed_at).toLocaleString()}</small></dd></div><div><dt>Evaluated artifact</dt><dd><code>{p.policy_id} v{data.review.policy_version}</code><small>{shortHash(data.review.policy_fingerprint)}</small></dd></div><div><dt>Deployment</dt><dd>{data.deployment.status}<small>{data.deployment.environment} · active v{data.deployment.active_version}</small></dd></div></dl><div className="proof"><span>Fingerprint verification</span><strong>EXACT MATCH</strong></div></section>
        </div>

        <section className="runtime-lab">
          <div className="runtime-copy"><p className="eyebrow">08 / Live deterministic enforcement</p><h2>Put the policy in the path</h2><p>These controls call the actual RefundAgent through RuntimeGateway. The browser never decides ALLOW or DENY.</p><div className="actions"><button className="danger-button" onClick={() => void run("unsafe")} disabled={busy !== null}>{busy === "unsafe" ? "Attempting…" : "Attempt unsafe email"}</button><button className="safe-button" onClick={() => void run("refund")} disabled={busy !== null}>{busy === "refund" ? "Processing…" : "Process authorized refund"}</button></div></div>
          <div className={`runtime-result ${result?.decision === "DENY" ? "blocked" : result ? "allowed" : "idle"}`} aria-live="polite">{result ? <><div className="verdict"><span>{result.decision === "DENY" ? "BLOCKED" : "ALLOWED"}</span><code>{result.audit_event_id.slice(0, 13)}</code></div><h3>{result.agent_id} <i>→</i> {result.tool_name}</h3><p>{result.data_classifications.join(", ")} <i>→</i> {result.destination_type}</p><dl><div><dt>Policy</dt><dd>{result.policy_id ?? "No denying policy"}</dd></div><div><dt>Tool executed</dt><dd>{result.tool_executed ? "YES" : "NO"}</dd></div><div><dt>Reason</dt><dd>{result.reason}</dd></div></dl>{result.decision === "DENY" && <button className="lineage-button" onClick={() => void showLineage(result.audit_event_id)}>Why was this blocked?</button>}</> : <><span className="scope">READY</span><h3>Choose a runtime action</h3><p>The resulting audit event will appear here.</p></>}</div>
        </section>

        {lineage && <section className="panel lineage"><header><div><p className="eyebrow">Audit lineage / {lineage.audit_event_id}</p><h2>Why was this blocked?</h2></div><button className="text-button" onClick={() => setLineage(null)}>Close</button></header><div className="lineage-flow"><article><span>Runtime action</span><b>{lineage.action.agent_id} → {lineage.action.tool_name}</b><small>{lineage.decision.decision}: {lineage.decision.reason}</small></article><i>↑</i><article><span>Runtime policy</span><b>{lineage.runtime_policy.policy_id} v{lineage.runtime_policy.version}</b><small>Approved under {lineage.approved_candidate.approval_review_id}</small></article><i>↑</i><article><span>Requirement</span><b>{lineage.requirement.requirement_id}</b><small>{lineage.explanation}</small></article><i>↑</i><article><span>Regulation evidence</span><b>{lineage.regulation.title}</b><small>“{lineage.regulation.source_evidence}”</small></article></div></section>}

        <div className="grid-main final-row"><section className="panel replay"><header><div><p className="eyebrow">Historical replay</p><h2>Operational blast radius</h2></div><strong>{percent(replay.change_rate)}</strong></header><div className="replay-bar"><span style={{ width: `${replay.unchanged / replay.total_actions * 100}%` }} /><i style={{ width: `${replay.newly_denied / replay.total_actions * 100}%` }} /></div><div className="replay-grid"><div><strong>{replay.total_actions}</strong><span>Analyzed</span></div><div><strong>{replay.unchanged}</strong><span>Unchanged</span></div><div><strong>{replay.newly_denied}</strong><span>Newly denied</span></div><div><strong>{replay.newly_allowed}</strong><span>Newly allowed</span></div></div><p>Decision change measures operational impact—not whether every changed action was malicious.</p><small>Affected: {replay.affected_agents.join(", ")} · {replay.affected_tools.join(", ")}</small></section><section className="panel activity"><header><div><p className="eyebrow">Evidence stream</p><h2>Recent activity</h2></div></header><ol>{data.activity.slice(-8).reverse().map((item, index) => <li key={`${item.kind}-${index}`}><span>{item.kind}</span><p>{item.message}</p><time>{item.timestamp ? new Date(item.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "evidence"}</time></li>)}</ol></section></div>
      </main>
      <footer><span>RegOps / {data.infrastructure.environment} deterministic demonstration</span><code>{data.evaluation.evaluation_id}</code></footer>
    </div>
  );
}
