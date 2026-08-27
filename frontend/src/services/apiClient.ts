import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 300_000, // 5 minutes — analysis takes time
  headers: { "Content-Type": "application/json" },
});

/**
 * Demo passphrase handling.
 *
 * The deployed API is gated by a shared passphrase (see DEMO_ACCESS_TOKEN in
 * api.py). This is a gate, not authentication: there is no user model and no
 * per-account data isolation yet. It exists because the deployed API was
 * returning every stored report to anonymous callers over sequential integer
 * ids.
 *
 * A public bundle cannot hold a secret, so nothing is baked in at build time.
 * The user types the passphrase once and it lives in sessionStorage — tab
 * lifetime only, deliberately, so a shared or public machine does not keep a
 * demo credential lying around after the tab closes.
 *
 * Wrapped in try/catch because sessionStorage throws outright in some contexts
 * (private windows with site data blocked), and a storage failure must not
 * take down the app.
 */
const TOKEN_KEY = "vf_demo_token";

export const demoToken = {
  get(): string {
    try { return sessionStorage.getItem(TOKEN_KEY) || ""; } catch { return ""; }
  },
  set(value: string): void {
    try { sessionStorage.setItem(TOKEN_KEY, value); } catch { /* non-fatal */ }
  },
  clear(): void {
    try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* non-fatal */ }
  },
};

/** True once the backend has answered 401, i.e. the deployment is gated. */
export let gateRequired = false;

apiClient.interceptors.request.use((config) => {
  const token = demoToken.get();
  if (token) config.headers["X-Demo-Token"] = token;
  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      gateRequired = true;
      // Drop a passphrase the server rejected, so the prompt reappears rather
      // than the app retrying a known-bad value forever.
      demoToken.clear();
      window.dispatchEvent(new CustomEvent("vf:gate-required"));
    }
    return Promise.reject(error);
  },
);

/** Headers for the raw fetch() calls that bypass apiClient (chat, history). */
export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = demoToken.get();
  return token ? { ...extra, "X-Demo-Token": token } : extra;
}

// ─── TYPES ─────────────────────────────────────────────────────────────────

export interface DetectedFounder {
  name: string;
  role?: string;
  background?: string;
}

export interface UploadResponse {
  session_id: string;
  extracted_text: string;
  detected_claims: string[];
  company_description: string;
  revenue: number | null;
  runway_months: number | null;
  page_count: number;
  /** Founders read out of the deck. Shown back to the user to correct or add
   *  to before the analysis runs -- extraction is a starting point, not an
   *  authority on who founded the company. */
  detected_founders?: DetectedFounder[];
  /** Which reader ran: "PDF" | "PowerPoint" | "Word" | "plain text" | "Markdown". */
  document_format?: string;
  extraction_method?: string;
}

export interface ClaimDetail {
  claim: string;
  verdict: "SUPPORTS" | "REFUTES" | "NOT_ENOUGH_INFO";
  confidence: number;
  reasoning: string;
  key_evidence: string;
  sources: string[];
  total_sources: number;
  full_pages_read: number;
}

export interface AnalyzeResponse {
  company: string;
  final_score: number;
  recommendation: string;
  risk_level: string;
  ai_analysis: string;
  claims_verified: number;
  claims_supported: number;
  claims_refuted: number;
  claims_uncertain: number;
  risk_signals_found: number;
  key_concerns: string[];
  red_flags: string[];
  positive_factors: string[];
  session_id: string;
  report_id?: string | null;
  incomplete_analysis?: boolean;
  /** Which mechanism produced final_score: the trained model or the fallback formula. */
  score_source?: string | null;
  /**
   * Claims were extracted and checked, but nothing public corroborated them.
   * Expected for an early-stage company, and deliberately NOT the same as
   * incomplete_analysis (which means the pipeline itself failed).
   */
  claims_unverified?: boolean;
  similar_companies?: Array<{ name: string; domain?: string | null; sector?: string | null; similarity?: number }>;
  founders?: string[];
  // full nested sections from backend
  sections?: {
    claims?: {
      checked: number;
      supported: number;
      refuted: number;
      uncertain: number;
      details: ClaimDetail[];
    };
    risk?: {
      overall_score: number;
      risk_level: string;
      key_concerns: string[];
      red_flags: string[];
      positive_factors: string[];
      ai_reasoning: string;
      total_signals: number;
    };
    ai_analysis?: string;
    rag_context?: {
      reports_retrieved: number;
    };
    market?: {
      confidence: number;
      market_definition: string;
      signals: Array<{ finding: string; evidence: string }>;
      gaps: string[];
      recommendation: string;
    };
    team?: {
      confidence: number;
      overall_assessment: string;
      capabilities: Array<{ area: string; score: number; evidence: string }>;
      strengths: string[];
      gaps: string[];
      questions: string[];
    };
    /**
     * Output of agents/founder_verifier.py, one entry per founder submitted.
     * Empty until 23 Aug 2026 for a structural reason rather than a modelling
     * one: nothing ever populated DiligenceRequest.founders, so the agent
     * never ran. See the Founder Analysis tab in Analysis.tsx.
     */
    founder_verification?: Array<{
      available: boolean;
      reason?: string;
      name?: string;
      assessment?: "CONSISTENT" | "CONTRADICTS" | "NOT_ENOUGH_INFO";
      confidence?: number;
      evidence_summary?: string;
      sources?: string[];
    }>;
    /**
     * Output of comparables.py: cosine similarity over 1,560 real Y Combinator
     * companies. Distinct from `similar_companies`, which is a trigram match
     * against the user's OWN prior reports and is empty on a fresh database --
     * the Competitor Insights tab used to read only the latter, which is why
     * it reported "no comparable companies" on every analysis while this
     * section sat populated in the same response.
     */
    market_comparables?: {
      available: boolean;
      reason?: string;
      comparables?: Array<{
        name: string;
        industry?: string;
        stage?: string;
        batch?: string;
        outcome?: string;
        similarity?: number;
      }>;
      source?: string;
      caveat?: string;
      /**
       * The search population, stated as structured data rather than left in
       * prose, so the UI can show the scope above the table instead of burying
       * it in a footnote. Comparables come from Y Combinator alumni only;
       * a company with no YC analogue still gets five rows, because the search
       * returns its nearest available matches however distant they are.
       */
      population?: {
        name?: string;
        n?: number;
        universe?: string;
        labelled_available?: number;
        coverage_of_labelled?: number;
        excluded?: string;
        not_included?: string;
        why_not_broader?: string;
      };
    };
    bull_case?: { confidence: number; thesis: string; signals: Array<{ finding: string; evidence: string }>; conditions_to_invest: string[] };
    bear_case?: { confidence: number; thesis: string; signals: Array<{ finding: string; evidence: string }>; diligence_required: string[] };
    /**
     * Output of the trained VentureFlow Score model (ml/venturescore.py) --
     * the source of the headline score. Every field after `venture_score` is
     * there so the UI can show how much to trust the number, which is the
     * whole point of the model: `score_range` is the 5th-95th percentile
     * across the bootstrap ensemble, `feature_coverage` is the fraction of
     * inputs actually observed rather than imputed, and `model_only_score`
     * vs `evidence_penalty` separates the population prior from what THIS
     * report's claim verification found.
     *
     * Optional, and `available` may be false: the backend returns
     * `{available: false, reason}` when the model file is missing, and the
     * report then falls back to the legacy formula. The UI must handle that.
     */
    venture_score?: {
      available: boolean;
      reason?: string;
      venture_score?: number;
      score_range?: [number, number];
      probability_exit_or_survive?: number;
      confidence?: "low" | "medium" | "high";
      ensemble_std?: number;
      feature_coverage?: number;
      imputed_features?: string[];
      base_rate?: number;
      lift_over_base_rate?: number;
      model_only_score?: number;
      evidence_penalty?: number;
      model?: {
        family?: string;
        calibration?: string;
        cv_roc_auc?: number;
        cv_roc_auc_ci95?: [number, number];
        cv_ece?: number;
        cv_brier?: number;
        trained_n?: number;
        excluded_contaminated_features?: string[];
      };
      caveat?: string;
    };
  };
}

export interface ChatResponse {
  answer: string;
  confidence: number;
  has_data: boolean;
  sources: string[];
}

// Matches db.py's stats() — the query counts against the live Neon schema,
// not the legacy Supabase tables this type used to describe (QA-007).
export interface DBStats {
  companies: number;
  dd_reports: number;
  portfolio_investments: number;
}

/**
 * Coerce one LLM-authored value into renderable text.
 *
 * `String({finding: "x"})` yields "[object Object]", and handing the raw object
 * to JSX crashes React outright with "Objects are not valid as a React child".
 * That is not hypothetical: it took the whole application down. Stored reports
 * contain `team.gaps` as `{description, evidence}`, `team.questions` as
 * `{question, evidence}`, `team.strengths` as `{description, evidence}` and
 * `market.gaps` as `{area, evidence}` -- four different shapes for fields the
 * prompt asks for as plain lists, because nothing constrains what the model
 * returns.
 *
 * So the known text-bearing keys are unwrapped in preference order, and
 * anything unrecognised degrades to readable JSON rather than "[object
 * Object]" or a crash.
 */
const asText = (value: unknown): string => {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(asText).filter(Boolean).join("; ");
  if (typeof value === "object") {
    const o = value as Record<string, unknown>;
    for (const key of ["finding", "description", "question", "area", "text", "title", "name", "claim", "concern", "gap", "strength"]) {
      if (typeof o[key] === "string" && o[key]) return o[key] as string;
    }
    try {
      return JSON.stringify(value);
    } catch {
      return "";
    }
  }
  return String(value);
};

const asArray = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.map(asText).filter(Boolean);
  const single = asText(value);
  return single ? [single] : [];
};

/**
 * Fields inside `sections.*` that the UI renders as plain text lists. Any
 * object arriving in one of these is a render crash, so they are flattened
 * once here, at the boundary, rather than defended at each of the ~20 render
 * sites -- which is the version of this fix that silently misses one.
 */
const TEXT_LIST_FIELDS = [
  "gaps", "questions", "strengths", "conditions_to_invest",
  "diligence_required", "key_concerns", "red_flags", "positive_factors",
];

/**
 * Single-value fields the UI renders as text. These need the same treatment as
 * the list fields and are just as unreliable: `market.market_definition` is an
 * object in 8 of the last 30 stored reports, arriving variously as
 * `{finding, evidence}` and `{evidence, assessment}`. It renders inside a
 * <p> on the Market Validation tab, which is exactly where React reported
 * "Objects are not valid as a React child (found: object with keys
 * {finding, evidence})".
 */
const TEXT_SCALAR_FIELDS = [
  "market_definition", "recommendation", "thesis", "overall_assessment",
  "ai_reasoning", "risk_level", "summary", "verdict",
];

const normalizeSections = (sections: Record<string, any>): Record<string, any> => {
  const out: Record<string, any> = {};
  for (const [name, section] of Object.entries(sections)) {
    if (!section || typeof section !== "object" || Array.isArray(section)) {
      out[name] = section;
      continue;
    }
    const copy: Record<string, any> = { ...section };
    for (const field of TEXT_LIST_FIELDS) {
      if (Array.isArray(copy[field])) copy[field] = copy[field].map(asText).filter(Boolean);
      else if (copy[field] !== undefined && copy[field] !== null) copy[field] = asArray(copy[field]);
    }
    for (const field of TEXT_SCALAR_FIELDS) {
      if (copy[field] !== undefined && copy[field] !== null && typeof copy[field] !== "string") {
        copy[field] = asText(copy[field]);
      }
    }
    // `signals` keeps its {finding, evidence} shape -- the UI reads both parts
    // deliberately (evidence becomes a tooltip) -- but each half is coerced so
    // a nested object cannot reach JSX.
    if (Array.isArray(copy.signals)) {
      copy.signals = copy.signals.map((s: any) =>
        s && typeof s === "object" && !Array.isArray(s)
          ? { finding: asText(s.finding ?? s), evidence: asText(s.evidence ?? "") }
          : { finding: asText(s), evidence: "" }
      );
    }
    if (Array.isArray(copy.capabilities)) {
      copy.capabilities = copy.capabilities.map((c: any) =>
        c && typeof c === "object" && !Array.isArray(c)
          ? { area: asText(c.area ?? c), score: Number(c.score) || 0, evidence: asText(c.evidence ?? "") }
          : { area: asText(c), score: 0, evidence: "" }
      );
    }
    out[name] = copy;
  }
  return out;
};

const asNumber = (value: unknown, fallback = 0): number => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
};

const normalizeAnalyzeResponse = (raw: any): AnalyzeResponse => {
  const sections = raw?.sections && typeof raw.sections === "object" ? raw.sections : {};
  const risk = sections.risk && typeof sections.risk === "object" ? sections.risk : {};
  const claims = sections.claims && typeof sections.claims === "object" ? sections.claims : {};
  const riskLevel = raw?.risk_level || risk.risk_level || risk.overall_risk_level || "UNKNOWN";

  return {
    company: String(raw?.company || "Unknown Company"),
    final_score: asNumber(raw?.final_score),
    recommendation: String(raw?.recommendation || "NEEDS MORE DILIGENCE"),
    risk_level: String(riskLevel),
    ai_analysis: String(raw?.ai_analysis || sections.ai_analysis || ""),
    claims_verified: asNumber(raw?.claims_verified ?? claims.checked),
    claims_supported: asNumber(raw?.claims_supported ?? claims.supported),
    claims_refuted: asNumber(raw?.claims_refuted ?? claims.refuted),
    claims_uncertain: asNumber(raw?.claims_uncertain ?? claims.uncertain),
    risk_signals_found: asNumber(raw?.risk_signals_found ?? risk.total_signals),
    key_concerns: asArray(raw?.key_concerns ?? risk.key_concerns),
    red_flags: asArray(raw?.red_flags ?? risk.red_flags),
    positive_factors: asArray(raw?.positive_factors ?? risk.positive_factors),
    session_id: String(raw?.session_id || ""),
    report_id: raw?.report_id ? String(raw.report_id) : null,
    incomplete_analysis: Boolean(raw?.incomplete_analysis),
    claims_unverified: Boolean(raw?.claims_unverified),
    score_source: raw?.score_source ? String(raw.score_source) : null,
    similar_companies: Array.isArray(raw?.similar_companies) ? raw.similar_companies : [],
    founders: Array.isArray(raw?.founders) ? raw.founders.map(asText).filter(Boolean) : [],
    sections: {
      // Flatten LLM-shaped values before anything renders them. See asText().
      ...normalizeSections(sections),
      claims: {
        checked: asNumber(claims.checked),
        supported: asNumber(claims.supported),
        refuted: asNumber(claims.refuted),
        uncertain: asNumber(claims.uncertain),
        details: Array.isArray(claims.details) ? claims.details : [],
      },
      risk: {
        overall_score: asNumber(risk.overall_score, 30),
        risk_level: String(riskLevel),
        key_concerns: asArray(risk.key_concerns),
        red_flags: asArray(risk.red_flags),
        positive_factors: asArray(risk.positive_factors),
        ai_reasoning: String(risk.ai_reasoning || "Risk analysis completed from available evidence."),
        total_signals: asNumber(risk.total_signals),
      },
      ai_analysis: String(sections.ai_analysis || raw?.ai_analysis || ""),
      rag_context: sections.rag_context,
    },
  };
};

export interface ReportSummary {
  report_id: string;
  company: string;
  final_score: number;
  recommendation: string;
  created_at: string;
}

export interface AnalysisJob {
  job_id: string;
  status: "pending" | "running" | "complete" | "failed";
  report?: AnalyzeResponse | null;
  error?: string | null;
  /**
   * The pipeline step the backend is actually executing right now, e.g.
   * "Verifying claims against live web search". Drives the progress display,
   * which previously advanced on a fixed timer unrelated to real work.
   * Null for queued jobs and for jobs created before stage tracking existed.
   */
  stage?: string | null;
}

// ─── API CALLS ──────────────────────────────────────────────────────────────

export const api = {
  /** Upload a pitch deck in any supported format (PDF / PPTX / DOCX / TXT / MD)
   *  — returns extracted text, detected claims and detected founders.
   *  Still posts to /upload-pdf: the route kept its name for compatibility
   *  and now accepts every format document_extractor.py can read. */
  uploadPDF: async (file: File, companyName: string): Promise<UploadResponse> => {
    const form = new FormData();
    form.append("file", file);
    form.append("company_name", companyName);
    const res = await apiClient.post<UploadResponse>("/upload-pdf", form, {
      headers: { "Content-Type": "multipart/form-data" },
    });
    return res.data;
  },

  /** Run full due diligence pipeline — claim verify + risk + RAG + Groq */
  startAnalysis: async (payload: {
    company_name: string;
    company_description: string;
    claims: string[];
    filing_text: string;
    revenue: number | null;
    burn_rate: number | null;
    runway_months: number | null;
    founders?: string[];
  }): Promise<AnalysisJob> => {
    const res = await apiClient.post<AnalysisJob>("/analyze", payload, { timeout: 30_000 });
    return res.data;
  },

  getAnalysisStatus: async (jobId: string): Promise<AnalysisJob> => {
    const res = await apiClient.get<AnalysisJob>(`/analyze/status/${jobId}`, { timeout: 30_000 });
    return { ...res.data, report: res.data.report ? normalizeAnalyzeResponse(res.data.report) : null };
  },

  listReports: async (): Promise<ReportSummary[]> => {
    const res = await apiClient.get<ReportSummary[]>("/reports");
    if (!Array.isArray(res.data)) {
      throw new Error("Saved reports response was not a list.");
    }
    return res.data;
  },

  getReport: async (reportId: string): Promise<AnalyzeResponse> => {
    const res = await apiClient.get<AnalyzeResponse>(`/reports/${reportId}`);
    return normalizeAnalyzeResponse(res.data);
  },

  /** Chat with the uploaded document using session_id */
  chat: async (sessionId: string, question: string): Promise<ChatResponse> => {
    const res = await apiClient.post<ChatResponse>("/chat", {
      session_id: sessionId,
      question,
    });
    return res.data;
  },

  /** Database row counts */
  getStats: async (): Promise<DBStats> => {
    const res = await apiClient.get<DBStats>("/database/stats");
    return res.data;
  },

  /** Health check */
  health: async (): Promise<boolean> => {
    try {
      await apiClient.get("/health");
      return true;
    } catch {
      return false;
    }
  },
};
