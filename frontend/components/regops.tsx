"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, DashboardData } from "@/lib/api";

type DashboardState = { data: DashboardData | null; error: string | null; reload: () => Promise<void> };
const DashboardContext = createContext<DashboardState | null>(null);

export function DashboardProvider({ children }: { children: React.ReactNode }) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(async () => {
    setError(null);
    try { setData(await api.dashboard()); }
    catch (err) { setError(err instanceof Error ? err.message : "Dashboard unavailable"); }
  }, []);
  useEffect(() => {
    let active = true;
    api.dashboard().then(
      dashboard => { if (active) setData(dashboard); },
      (err: unknown) => { if (active) setError(err instanceof Error ? err.message : "Dashboard unavailable"); },
    );
    return () => { active = false; };
  }, []);
  return <DashboardContext.Provider value={{ data, error, reload }}>{children}</DashboardContext.Provider>;
}

export function useDashboard() {
  const value = useContext(DashboardContext);
  if (!value) throw new Error("useDashboard must be used within DashboardProvider");
  return value;
}

const nav = [["/", "Overview"], ["/analyze", "Analyze Regulation"], ["/case", "Compliance Case"], ["/runtime", "Runtime"], ["/fleet", "Agent Fleet"]];

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { data } = useDashboard();
  return <div className="app-shell">
    <header className="global-header">
      <Link href="/" className="brand"><span className="brand-mark">R</span><span><b>RegOps</b><small>Agent compliance</small></span></Link>
      <nav aria-label="Primary navigation">{nav.map(([href, label]) => <Link key={href} href={href} className={`${path === href ? "active " : ""}${href === "/analyze" ? "analyze-nav" : ""}`.trim()}>{label}</Link>)}</nav>
      <div className="cloud-status"><span/><div><small>Environment</small><b>{data?.infrastructure.environment ?? "connecting"}</b></div></div>
    </header>
    {children}
    <footer className="site-footer"><span>RegOps</span><span>Deterministic compliance enforcement</span><Link href="/evidence">Technical evidence</Link></footer>
  </div>;
}

export function PageState({ error, retry }: { error: string | null; retry: () => Promise<void> }) {
  return <main className="page state-page">{error ? <div className="state-card error-state"><p className="eyebrow">Connection error</p><h1>RegOps API is unavailable</h1><p>{error}</p><button className="primary-button" onClick={() => void retry()}>Try again</button></div> : <div className="state-card loading-state"><span className="loader"/><h1>Loading RegOps state</h1><p>Reading authoritative compliance evidence…</p></div>}</main>;
}

export function Status({ children, tone = "neutral" }: { children: React.ReactNode; tone?: "good" | "risk" | "warn" | "neutral" }) {
  return <span className={`status status-${tone}`}>{children}</span>;
}

export const percent = (value: number) => `${Math.round(value * 100)}%`;
export const shortHash = (value: string) => `${value.slice(0, 12)}…${value.slice(-6)}`;
