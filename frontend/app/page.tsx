"use client";

import Link from "next/link";
import { PageState, Status, useDashboard } from "@/components/regops";

export default function Overview() {
  const state = useDashboard();
  if (!state.data) return <PageState error={state.error} retry={state.reload} />;
  const { data } = state;
  const policy = data.candidate_policy;

  return <main className="page overview-page">
    <section className="hero">
      <p className="eyebrow">AI agent governance</p>
      <h1>Compliance infrastructure for AI agent fleets</h1>
      <p className="hero-copy">Turn changing regulations into tested, approved, enforceable controls across your AI agents.</p>
    </section>

    <section className="analyze-cta">
      <div><p className="eyebrow">Live regulatory change analysis</p><h2>Bring your own regulation</h2><p>Screen, interpret, and assess any regulatory text against your connected agent fleet—without changing active controls.</p></div>
      <Link className="primary-button" href="/analyze">Analyze a regulation <span>→</span></Link>
    </section>

    <section className="overview-grid">
      <article className="feature-card case-card">
        <div className="card-heading"><div><p className="eyebrow">Current compliance case</p><h2>{data.regulation.title}</h2></div><Status tone="good">{data.evaluation.status}</Status></div>
        <p className="subtle">Case {data.case_id}</p>
        <div className="summary-stats">
          <div><span>Agent impact</span><strong>{data.impact.affected_agent_count} <small>of {data.impact.analyzed_agent_count}</small></strong><p>agents affected</p></div>
          <div><span>Candidate control</span><strong>{policy.policy_id}</strong><p>version {policy.version}</p></div>
          <div><span>Runtime status</span><strong className="positive">{data.deployment.status}</strong><p>{data.deployment.environment}</p></div>
        </div>
        <Link className="primary-button" href="/case">Open compliance case <span>→</span></Link>
      </article>

      <article className="feature-card runtime-summary">
        <div><p className="eyebrow">Runtime enforcement</p><h2>Controls are active</h2><p>The approved policy is protecting agent actions at the gateway.</p></div>
        <div className="runtime-health"><span className="health-pulse"/><div><strong>System healthy</strong><small>{data.infrastructure.runtime}</small></div></div>
        <dl><div><dt>Active policies</dt><dd>1</dd></div><div><dt>Current policy</dt><dd>{policy.policy_id} v{data.deployment.active_version}</dd></div><div><dt>Recent decisions</dt><dd>{data.runtime.recent_decisions.length}</dd></div></dl>
        <Link className="secondary-button" href="/runtime">Open runtime monitor <span>→</span></Link>
      </article>
    </section>
  </main>;
}
