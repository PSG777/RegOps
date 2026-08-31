export interface CapabilityPath {
  data_classification: string;
  agent_id: string;
  agent_version: string;
  tool_name: string;
  action_type: string;
  destination_type: string;
}

export interface AgentImpact {
  agent_id: string;
  agent_name: string;
  agent_version: string;
  status: string;
  severity: string;
  relevant_data_classifications: string[];
  risky_tools: string[];
  capability_paths: CapabilityPath[];
  reasons: string[];
}

export interface RuntimeDecision {
  audit_event_id: string;
  occurred_at: string;
  agent_id: string;
  agent_version: string;
  tool_name: string;
  data_classifications: string[];
  destination_type: string;
  purpose: string;
  decision: "ALLOW" | "DENY";
  policy_id: string | null;
  reason: string;
  tool_executed: boolean;
  execution_status: string;
}

export interface TestCase {
  test_id: string;
  category: string;
  scenario: string;
  agent_id: string;
  tool_name: string;
  expected_decision: string;
}

export interface PreviewComplianceTest extends TestCase {
  requirement_id: string;
  policy_id: string;
  agent_version: string;
  data_classifications: string[];
  purpose: string;
  expected_reason: string;
  tags: string[];
  status: "READY";
}

export interface PreviewTestIssue {
  source_index: number;
  status: "NEEDS_REVIEW" | "REJECTED";
  category: string | null;
  agent_id: string | null;
  tool_name: string | null;
  scenario: string | null;
  reason: string;
}

export interface RegulationAnalysisPreview {
  preview_only: true;
  regulation: {
    regulation_id: string;
    title: string;
    source_text: string;
    version: string;
  };
  requirement: {
    requirement_id: string;
    regulation_id: string;
    source_excerpt: string;
    data_classification: string;
    governed_action: string;
    allowed_destination: string;
    required_purpose: string;
    confidence: number;
  };
  input_screening: {
    status: "PASSED" | "BLOCKED";
    provider: string;
    findings: string[];
  };
  analyzed_agent_count: number;
  affected_agent_count: number;
  affected_agents: string[];
  unaffected_agents: string[];
  needs_review_agents: string[];
  agent_impacts: AgentImpact[];
  candidate_policy: {
    policy_id: string;
    version: number;
    requirement_id: string;
    regulation_id: string;
    description: string;
    effect: string;
    protected_classification: string;
    governed_action: string;
    allowed_destination: string;
    required_purpose: string;
    status: string;
    affected_agent_ids: string[];
  };
  candidate_validation_status: "VALIDATED";
  compliance_tests: {
    suite_id: string;
    requirement_id: string;
    policy_id: string;
    candidate_policy_version: number;
    affected_agent_ids: string[];
    test_cases: PreviewComplianceTest[];
    needs_review: PreviewTestIssue[];
    rejected: PreviewTestIssue[];
    coverage: {
      total_test_count: number;
      prohibited_count: number;
      legitimate_count: number;
      adversarial_count: number;
      edge_case_count: number;
      affected_agents_covered: string[];
      risky_tools_covered: string[];
      known_destinations_covered: string[];
    };
  };
  stages: {
    stage: "INPUT_SCREENING" | "REGULATION_INTERPRETATION" | "REQUIREMENT_VALIDATION" | "FLEET_IMPACT_ANALYSIS" | "CANDIDATE_POLICY_GENERATION" | "CANDIDATE_POLICY_VALIDATION" | "COMPLIANCE_TEST_GENERATION" | "COMPLIANCE_TEST_VALIDATION";
    status: "COMPLETED";
  }[];
}

export interface DashboardData {
  case_id: string;
  infrastructure: {
    environment: string;
    firestore: string;
    pubsub: string;
    agent_registry: string;
    model_armor: string;
    vertex: string;
    runtime: string;
    registry_source: string;
    input_screening: string;
  };
  enterprise_fleet: {
    registry_source: string;
    agents: { agent_id: string; name: string; version: string; status: string }[];
  };
  pipeline: { stage: string; status: string }[];
  regulation: {
    regulation_id: string;
    title: string;
    source_text: string;
    version: string;
    requirement: {
      requirement_id: string;
      source_excerpt: string;
      data_classification: string;
      governed_action: string;
      allowed_destination: string;
      required_purpose: string;
      confidence: number;
    };
  };
  impact: { analyzed_agent_count: number; affected_agent_count: number; agents: AgentImpact[] };
  candidate_policy: {
    policy_id: string;
    version: number;
    description: string;
    status: string;
    runtime_status: string;
    fingerprint: string;
    protected_classification: string;
    governed_action: string;
    allowed_destination: string;
    required_purpose: string;
    requirement_id: string;
  };
  tests: {
    total_count: number;
    category_counts: Record<string, number>;
    ready_count: number;
    needs_review_count: number;
    representative_cases: TestCase[];
  };
  evaluation: {
    evaluation_id: string;
    compliance: ScorePair;
    utility: ScorePair;
    adversarial: ScorePair;
    critical_violations: ScorePair;
    blast_radius: number;
    status: string;
    replay: {
      total_actions: number;
      newly_denied: number;
      newly_allowed: number;
      unchanged: number;
      change_rate: number;
      affected_agents: string[];
      affected_tools: string[];
    };
  };
  review: {
    review_id: string;
    policy_version: number;
    policy_fingerprint: string;
    decision: string;
    reviewed_at: string;
    reviewer: { display_name: string; role: string };
  };
  deployment: {
    deployment_id: string;
    status: string;
    environment: string;
    active_version: number;
    rollback_available: boolean;
    activated_at: string;
  };
  runtime: { recent_decisions: RuntimeDecision[] };
  activity: { kind: string; message: string; timestamp: string | null }[];
}

interface ScorePair { baseline: number; candidate: number }

export interface LineageData {
  audit_event_id: string;
  action: { agent_id: string; tool_name: string; destination_type: string; purpose: string };
  decision: { decision: string; reason: string };
  runtime_policy: { policy_id: string; version: number };
  approved_candidate: { fingerprint: string; approval_review_id: string };
  requirement: { requirement_id: string; source_excerpt: string };
  regulation: { regulation_id: string; title: string; source_evidence: string };
  explanation: string;
}

const API_URL = process.env.NEXT_PUBLIC_REGOPS_API_URL ?? "http://localhost:8000";

export class RegOpsApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "RegOpsApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { Accept: "application/json", ...init?.headers },
    cache: "no-store",
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new RegOpsApiError(body?.detail ?? `RegOps API returned ${response.status}`, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  dashboard: () => request<DashboardData>("/api/demo/dashboard"),
  unsafeEmail: () => request<RuntimeDecision>("/api/demo/runtime/unsafe-email", { method: "POST" }),
  refund: () => request<RuntimeDecision>("/api/demo/runtime/refund", { method: "POST" }),
  lineage: (auditId: string) => request<LineageData>(`/api/demo/lineage/${auditId}`),
  analyzeRegulation: (text: string) => request<RegulationAnalysisPreview>("/api/regulations/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  }),
};
