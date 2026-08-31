"use client";

import Link from "next/link";
import { FormEvent, useMemo, useState } from "react";
import { Status, useDashboard } from "@/components/regops";
import { api, RegOpsApiError, RegulationAnalysisPreview } from "@/lib/api";

const examples = [
  "Financial account information may only be transmitted to approved payment processors for authorized financial transactions.",
  "Customer records may only be transmitted through approved email providers for authorized customer support communications.",
];

const expectedStages = [
  ["INPUT_SCREENING", "Model Armor screening"],
  ["REGULATION_INTERPRETATION", "Gemini interpretation"],
  ["REQUIREMENT_VALIDATION", "Requirement validation"],
  ["FLEET_IMPACT_ANALYSIS", "Fleet impact"],
  ["CANDIDATE_POLICY_GENERATION", "Policy generation"],
  ["CANDIDATE_POLICY_VALIDATION", "Policy validation"],
  ["COMPLIANCE_TEST_GENERATION", "Test generation"],
  ["COMPLIANCE_TEST_VALIDATION", "Test validation"],
] as const;

const categoryOrder = ["PROHIBITED", "LEGITIMATE", "ADVERSARIAL", "EDGE_CASE"];

function errorCopy(error: unknown) {
  if (error instanceof RegOpsApiError) {
    if (error.status === 400) return { title: "Input screening rejected this text", message: error.message };
    if (error.status === 422) return { title: "The analysis could not be validated", message: error.message };
    return { title: "RegOps could not complete the analysis", message: error.message };
  }
  return { title: "Could not connect to RegOps", message: error instanceof Error ? error.message : "Check the API connection and try again." };
}

export default function AnalyzeRegulation() {
  const dashboard = useDashboard();
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RegulationAnalysisPreview | null>(null);
  const [error, setError] = useState<{ title: string; message: string } | null>(null);
  const completed = useMemo(() => new Set(result?.stages.filter(stage => stage.status === "COMPLETED").map(stage => stage.stage) ?? []), [result]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) { setError({ title: "Enter regulation text", message: "Paste or type a regulatory requirement before starting analysis." }); return; }
    setBusy(true); setError(null); setResult(null);
    try { setResult(await api.analyzeRegulation(text)); }
    catch (err) { setError(errorCopy(err)); }
    finally { setBusy(false); }
  }

  const registrySource = dashboard.data?.enterprise_fleet.registry_source ?? "Authoritative Agent Registry";
  const registeredAgents = dashboard.data?.enterprise_fleet.agents ?? [];

  return <main className="page analyze-page">
    <header className="analyze-hero"><p className="eyebrow">Live control-plane preview</p><h1>Analyze a Regulatory Change</h1><p>See how a new regulation affects your registered AI agent fleet before anything is deployed.</p><div className="preview-pill">PREVIEW ONLY · NO RUNTIME CHANGES</div></header>

    <section className="analyze-input-card">
      <aside className="connected-fleet"><p className="eyebrow">Connected context</p><h2>Enterprise Agent Fleet</h2><p>Source: <b>{registrySource}</b></p><div className="connected-agents">{registeredAgents.map(agent => <span key={`${agent.agent_id}-${agent.version}`}>{agent.name} <small>v{agent.version}</small></span>)}</div><small>Analysis uses the currently registered fleet. Agent names are not embedded in this page.</small></aside>
      <form onSubmit={submit}><label htmlFor="regulation-text">Regulation text</label><textarea id="regulation-text" value={text} onChange={event => setText(event.target.value)} placeholder="Paste a regulatory requirement here…" rows={8} disabled={busy}/><div className="example-row"><span>Try an example:</span>{examples.map((example, index) => <button type="button" key={example} onClick={() => { setText(example); setError(null); }} disabled={busy}>Example {index + 1}</button>)}</div><button className="analyze-button" type="submit" disabled={busy}>{busy ? "RegOps is analyzing this regulatory change…" : "Analyze with RegOps →"}</button></form>
    </section>

    {(busy || result) && <section className="analysis-pipeline" aria-live="polite"><div className="section-heading"><div><p className="eyebrow">Real analysis pipeline</p><h2>{busy ? "Analysis in progress" : "Analysis completed"}</h2></div>{result?.preview_only && <Status tone="warn">PREVIEW ONLY</Status>}</div><div className="live-stages">{expectedStages.map(([id,label], index) => <div key={id} className={completed.has(id) ? "stage-completed" : "stage-pending"}><span>{completed.has(id) ? "✓" : index + 1}</span><div><strong>{label}</strong><small>{completed.has(id) ? "Completed by backend" : busy ? "Awaiting backend response" : "Not confirmed"}</small></div></div>)}</div>{busy && <p className="pending-note">No stage is marked complete until the endpoint returns validated stage evidence.</p>}</section>}

    {error && <section className="analysis-error" role="alert"><div><p className="eyebrow">Analysis stopped</p><h2>{error.title}</h2><p>{error.message}</p></div><button onClick={() => setError(null)}>Dismiss</button></section>}

    {result && <AnalysisResults result={result} registrySource={registrySource}/>}
  </main>;
}

function AnalysisResults({ result, registrySource }: { result: RegulationAnalysisPreview; registrySource: string }) {
  const requirement = result.requirement;
  const policy = result.candidate_policy;
  const suite = result.compliance_tests;
  const coverage = suite.coverage;
  return <div className="analysis-results">
    <section className="analysis-section interpretation-result"><header><span>01</span><div><p className="eyebrow">Regulation interpretation</p><h2>From source text to typed requirement</h2></div></header><blockquote>“{result.regulation.source_text}”</blockquote><div className="trust-transform"><span><b>Model Armor</b><small>{result.input_screening.provider} · {result.input_screening.status}</small></span><i>→</i><span><b>Gemini</b><small>Structured interpretation</small></span><i>→</i><span><b>Deterministic validation</b><small>Typed requirement accepted</small></span></div><div className="interpretation-facts"><div><span>Data classification</span><strong>{requirement.data_classification}</strong></div><div><span>Governed action</span><strong>{requirement.governed_action}</strong></div><div><span>Allowed destination</span><strong>{requirement.allowed_destination}</strong></div><div><span>Required purpose</span><strong>{requirement.required_purpose}</strong></div><div><span>Confidence</span><strong>{Math.round(requirement.confidence * 100)}%</strong></div></div></section>

    <div className="result-arrow">↓</div>
    <section className="analysis-section impact-result"><header><span>02</span><div><p className="eyebrow">Fleet impact</p><h2>{result.analyzed_agent_count} agents analyzed · {result.affected_agent_count} affected</h2><p>Authoritative source: {registrySource}</p></div></header><div className="live-impact-list">{result.agent_impacts.map(agent => <article key={`${agent.agent_id}-${agent.agent_version}`} className={agent.status === "AFFECTED" ? "affected" : ""}><div className="impact-heading"><div><h3>{agent.agent_name}</h3><code>{agent.agent_id} · v{agent.agent_version}</code></div><div><Status tone={agent.status === "AFFECTED" ? "risk" : agent.status === "NEEDS_REVIEW" ? "warn" : "neutral"}>{agent.status}</Status><span className="severity">{agent.severity} severity</span></div></div><ul>{agent.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul>{agent.capability_paths.map((path,index) => <div className="capability-path" key={`${path.tool_name}-${index}`}><span>{path.data_classification}</span><i>→</i><span>{agent.agent_name}</span><i>→</i><span>{path.tool_name}</span><i>→</i><span>{path.destination_type}</span></div>)}</article>)}</div></section>

    <div className="result-arrow">↓</div>
    <section className="analysis-section candidate-result"><header><span>03</span><div><p className="eyebrow">Candidate policy</p><h2>{policy.policy_id} <small>v{policy.version}</small></h2></div><Status tone="warn">NOT ACTIVE</Status></header><div className="proposal-chain"><b>AI PROPOSED</b><i>→</i><b>DETERMINISTICALLY VALIDATED</b><Status tone="good">{result.candidate_validation_status}</Status></div><p className="policy-description">{policy.description}</p><div className="candidate-rule"><span>PROTECT</span><strong>{policy.protected_classification}</strong><span>WHEN</span><strong>{policy.governed_action}</strong><span>ALLOW ONLY</span><strong>{policy.allowed_destination} · {policy.required_purpose}</strong><span>OTHERWISE</span><strong className="deny-text">{policy.effect}</strong></div><div className="affected-policy-agents"><span>Affected agent IDs</span>{policy.affected_agent_ids.map(id => <code key={id}>{id}</code>)}</div></section>

    <div className="result-arrow">↓</div>
    <section className="analysis-section tests-result"><header><span>04</span><div><p className="eyebrow">Generated tests</p><h2>AI proposals filtered by deterministic validation</h2></div></header><div className="test-status-summary"><div className="ready"><strong>{suite.test_cases.length}</strong><span>READY tests</span></div><div className="review"><strong>{suite.needs_review.length}</strong><span>NEEDS_REVIEW proposals</span></div><div className="rejected"><strong>{suite.rejected.length}</strong><span>REJECTED proposals</span></div></div>{categoryOrder.map(category => { const tests = suite.test_cases.filter(test => test.category === category); if (!tests.length) return null; return <div className="test-category" key={category}><h3>{category} <span>{tests.length}</span></h3>{tests.map(test => <article key={test.test_id}><Status tone={test.expected_decision === "DENY" ? "risk" : "good"}>{test.expected_decision}</Status><div><strong>{test.scenario}</strong><p>{test.agent_id} → {test.tool_name} · {test.purpose}</p>{test.tags.length > 0 && <div className="tag-row">{test.tags.map(tag => <span key={tag}>{tag}</span>)}</div>}</div></article>)}</div>})}{suite.needs_review.length > 0 && <IssueList title="Needs review" tone="review" issues={suite.needs_review}/>} {suite.rejected.length > 0 && <IssueList title="Rejected proposals" tone="rejected" issues={suite.rejected}/>}<div className="coverage-panel"><h3>Coverage summary</h3><div><span>Total ready tests<strong>{coverage.total_test_count}</strong></span><span>Prohibited<strong>{coverage.prohibited_count}</strong></span><span>Legitimate<strong>{coverage.legitimate_count}</strong></span><span>Adversarial<strong>{coverage.adversarial_count}</strong></span><span>Edge case<strong>{coverage.edge_case_count}</strong></span></div><dl><div><dt>Affected agents covered</dt><dd>{coverage.affected_agents_covered.join(", ") || "None"}</dd></div><div><dt>Risky tools covered</dt><dd>{coverage.risky_tools_covered.join(", ") || "None"}</dd></div><div><dt>Known destinations covered</dt><dd>{coverage.known_destinations_covered.join(", ") || "None"}</dd></div></dl></div></section>

    <section className="preview-boundary"><div className="preview-warning"><span>PREVIEW ONLY</span><h2>This analysis has not changed the active runtime policy.</h2><p>No candidate has been approved, deployed, or activated.</p></div><div className="boundary-flow"><span>AI interprets and proposes</span><i>↓</i><span>Deterministic software validates</span><i>↓</i><span>Human approval required</span><i>↓</i><span>Deployment required</span><i>↓</i><span>Runtime enforcement</span></div><Link className="secondary-button" href="/case">View validated deployment →</Link></section>
  </div>;
}

function IssueList({ title, tone, issues }: { title: string; tone: string; issues: RegulationAnalysisPreview["compliance_tests"]["needs_review"] }) {
  return <div className={`issue-list ${tone}`}><h3>{title} <span>{issues.length}</span></h3>{issues.map(issue => <article key={`${issue.source_index}-${issue.reason}`}><Status tone={tone === "review" ? "warn" : "risk"}>{issue.status}</Status><div><strong>{issue.scenario ?? "Generated proposal"}</strong><p>{issue.reason}</p><small>{[issue.category, issue.agent_id, issue.tool_name].filter(Boolean).join(" · ")}</small></div></article>)}</div>;
}
