import axios from "axios";

/**
 * Where the API lives.
 *
 * `VITE_API_BASE_URL` is inlined by Vite at BUILD time, not read at runtime —
 * setting it in Vercel after a deploy changes nothing until the next build.
 *
 * The `/api` fallback is only correct for a deployment that proxies that path
 * to the backend on the same origin. This project's `vercel.json` rewrites
 * `/(.*)` to `/index.html`, so on Vercel the fallback does NOT reach the API:
 * every call returns the SPA's HTML with a 200, axios tries to parse it as
 * JSON, and the UI reports a generic "Network Error". That failure is
 * indistinguishable from the backend being down, which is why it stayed
 * confusing for so long.
 *
 * So an unset variable in a production build is treated as the configuration
 * error it is, and says so once, loudly, instead of degrading into a
 * misleading network error.
 */
const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

if (import.meta.env.PROD && !import.meta.env.VITE_API_BASE_URL) {
  console.error(
    "[VentureFlow] VITE_API_BASE_URL was not set at build time, so API calls " +
      "fall back to '/api'. On this project's Vercel config that path is " +
      "rewritten to index.html and will return HTML instead of JSON — every " +
      "request will surface as a generic network error. Set VITE_API_BASE_URL " +
      "to the absolute backend origin (e.g. https://your-api.onrender.com) in " +
      "the Vercel project's Environment Variables and redeploy.",
  );
}

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

/**
 * The signed-in session token.
 *
 * `localStorage`, not `sessionStorage` -- unlike the demo passphrase, this is a
 * real account and being signed out every time a tab closes is hostile. The
 * server-side session carries the actual expiry (30 days by default); this is
 * only where the browser keeps the token in the meantime.
 *
 * Wrapped in try/catch throughout because storage throws outright in a private
 * window with site data blocked, and a storage failure must not take down the
 * app -- it degrades to "signed out", which is recoverable.
 */
const SESSION_KEY = "vf_session_token";

export const sessionToken = {
  get(): string {
    try { return localStorage.getItem(SESSION_KEY) || ""; } catch { return ""; }
  },
  set(value: string): void {
    try { localStorage.setItem(SESSION_KEY, value); } catch { /* non-fatal */ }
  },
  clear(): void {
    try { localStorage.removeItem(SESSION_KEY); } catch { /* non-fatal */ }
  },
};

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  created_at: string | null;
  email_verified: boolean;
  email_verification_note: string;
}

export interface AuthSession {
  token: string;
  user: AuthUser;
  expires_at: string;
}

export interface WhoAmI {
  user: AuthUser | null;
  accounts_enabled: boolean;
  any_accounts_exist: boolean;
  email_verification_note: string;
  password_min_length: number;
}

/** True once the backend has answered 401, i.e. the deployment is gated. */
export let gateRequired = false;

apiClient.interceptors.request.use((config) => {
  // Two independent credentials, deliberately on two headers.
  //
  // The demo passphrase says "this deployment let me in"; the session token
  // says "I am this person". A gated deployment needs both, and putting them
  // both on Authorization would mean one silently overwriting the other.
  const demo = demoToken.get();
  if (demo) config.headers["X-Demo-Token"] = demo;
  const session = sessionToken.get();
  if (session) config.headers["Authorization"] = `Bearer ${session}`;
  return config;
});

/**
 * Two different 401s reach this client and they need opposite responses.
 *
 * The passphrase gate's 401 means "this deployment wants the shared
 * passphrase" and is answered by DemoGate's prompt. The sign-in gate's 401
 * (`code: "signin_required"`, sent in production for every non-public route)
 * means "your session is missing or no longer valid" and is answered by the
 * sign-in page. Treating both as the first -- which this interceptor used to --
 * would show an expired session a passphrase prompt that cannot help it.
 */
export function isSigninRequired(body: unknown): boolean {
  return typeof body === "object" && body !== null
    && (body as { code?: string }).code === "signin_required";
}

/** Forget the session locally and tell AuthContext, so RequireAuth redirects. */
export function signalSignedOut(): void {
  sessionToken.clear();
  window.dispatchEvent(new CustomEvent("vf:signin-required"));
}

/**
 * The same check for raw fetch() calls, which bypass the axios interceptor.
 * Returns true when the response was the sign-in gate, so the caller can stop.
 */
export async function handleSignedOut(res: Response): Promise<boolean> {
  if (res.status !== 401) return false;
  try {
    if (isSigninRequired(await res.clone().json())) {
      signalSignedOut();
      return true;
    }
  } catch {
    // Not JSON: not the sign-in gate.
  }
  return false;
}

apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      if (isSigninRequired(error.response.data)) {
        signalSignedOut();
      } else {
        gateRequired = true;
        // Drop a passphrase the server rejected, so the prompt reappears rather
        // than the app retrying a known-bad value forever.
        demoToken.clear();
        window.dispatchEvent(new CustomEvent("vf:gate-required"));
      }
    }
    return Promise.reject(error);
  },
);

/**
 * Pull a displayable message, and a scope refusal, out of a failed request.
 *
 * FastAPI's `detail` is a string for most errors and an OBJECT for the
 * out-of-scope refusal, which carries the evidence the UI needs to explain
 * itself. Both callers previously did `err.response.data.detail || err.message`
 * and put the result straight into JSX -- which renders fine for a string and
 * throws "Objects are not valid as a React child" for the object, replacing a
 * clear explanation with a blank screen.
 *
 * So the shape is narrowed here, once, rather than at each call site.
 */
export function parseApiError(err: unknown, fallback: string): {
  message: string;
  scopeCheck: ScopeCheck | null;
} {
  const detail = (err as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail;

  if (detail && typeof detail === "object") {
    const body = detail as { error?: string; message?: string; scope_check?: ScopeCheck };
    if (body.error === "out_of_scope" && body.scope_check) {
      return {
        message: body.message || "This company is outside VentureFlow's scope.",
        scopeCheck: body.scope_check,
      };
    }
    return { message: body.message || fallback, scopeCheck: null };
  }

  if (typeof detail === "string" && detail) {
    return { message: detail, scopeCheck: null };
  }
  const message = (err as { message?: string })?.message;
  return { message: message || fallback, scopeCheck: null };
}

/** Headers for the raw fetch() calls that bypass apiClient (chat, history). */
export function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const headers = { ...extra };
  const demo = demoToken.get();
  if (demo) headers["X-Demo-Token"] = demo;
  const session = sessionToken.get();
  if (session) headers["Authorization"] = `Bearer ${session}`;
  return headers;
}

// ─── TYPES ─────────────────────────────────────────────────────────────────

/**
 * How much of the deck reached a structured field (extraction_coverage.py).
 *
 * The number exists to separate two situations the report used to render
 * identically: "the deck said little" and "we dropped most of what it said".
 * A LOW verdict means the reader should suspect the parser before they suspect
 * the founder, which is the opposite of what an unqualified "insufficient
 * data" implies.
 */
export interface ExtractionCoverage {
  available: boolean;
  coverage_pct?: number;
  line_coverage_pct?: number;
  content_slides?: number;
  represented_slides?: number;
  image_only_slides?: number;
  unrepresented_slides?: Array<{ slide: number; heading: string }>;
  unmapped_examples?: string[];
  verdict?: "HIGH" | "PARTIAL" | "LOW" | "EMPTY";
  interpretation?: string;
  reason?: string;
}

/**
 * Which extraction path produced a report (ventureflow_agent).
 *
 * Exists because a silent fall back to the regex extractor is the defect this
 * product spent a whole pass removing: it degraded every analysis for an
 * unknown length of time and nothing in the output said so. A reader of the
 * claims table is exactly the person who needs to know.
 */
export interface ExtractionProvenance {
  method?: string;
  is_fallback?: boolean;
  fallback_reason?: string;
  warning?: string;
}

export interface DetectedFounder {
  name: string;
  role?: string;
  background?: string;
}

/**
 * Whether the deck is a technology startup (tech_scope.py).
 *
 * VentureFlow's every number is calibrated on technology companies -- the score
 * model's features are Y Combinator's own taxonomy -- so a score for a business
 * outside that scope has no calibrated meaning. Both /upload-pdf and /analyze
 * refuse with a 422 carrying this object when `in_scope` is false.
 *
 * The backend is deliberately reluctant to refuse: it blocks only on positive
 * evidence that a company is something else, and allows anything it cannot
 * classify. So a false `in_scope` is a considered judgement, and the UI shows
 * the evidence behind it rather than a bare error.
 */
export interface ScopeCheck {
  in_scope: boolean;
  confidence: number;
  sector: string;
  reason: string;
  method: string;
  software_signals: string[];
  non_tech_signals: string[];
  scope_statement: string;
}

/**
 * Where the analysed text came from (ocr_extractor.py).
 *
 * An image-only deck used to be rejected outright. It is now read by an offline
 * OCR engine, which means some decks are analysed from text recognised out of
 * pixels rather than read from the file. OCR misreads digits more often than it
 * misreads words, and a diligence tool that presents a recognised revenue figure
 * identically to a read one is hiding the one thing a reader would want to know
 * about that number -- hence `text_source` as a first-class field.
 */
export interface OcrSummary {
  pages_read?: number;
  pages_total?: number;
  chars?: number;
  truncated?: boolean;
  truncation_note?: string;
  seconds?: number;
  engine?: string;
  provenance?: string;
  reason?: string;
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
  /**
   * Deck metadata the scoring model consumes. Each is null when the deck did
   * not say -- the extractor abstains rather than guessing, because a
   * fabricated stage would move the score 42 points on the strength of an
   * invention. `metadata_evidence` carries the matched text so the UI can show
   * its work.
   */
  burn_rate?: number | null;
  stage?: string | null;
  sector?: string | null;
  team_size?: number | null;
  github_url?: string | null;
  domain?: string | null;
  metadata_evidence?: Record<string, string>;
  /** Which reader ran: "PDF" | "PowerPoint" | "Word" | "plain text" | "Markdown". */
  document_format?: string;
  extraction_method?: string;
  /**
   * Per-slide text and the extraction provenance.
   *
   * Both were returned by /upload-pdf from the day they were built and neither
   * was declared here, so TypeScript quietly hid them from every consumer --
   * which is why the analysis request never forwarded them and every report
   * measured coverage over a single synthetic "slide".
   */
  deck_slides?: string[];
  extraction_fallback_reason?: string;
  extraction_coverage?: ExtractionCoverage;
  /**
   * "text_layer" -- text the document contained.
   * "ocr"        -- recognised from page images, because there was no text layer.
   * "hybrid"     -- a thin text layer supplemented by OCR of the slides.
   */
  text_source?: "text_layer" | "ocr" | "hybrid";
  ocr?: OcrSummary;
  scope_check?: ScopeCheck;
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
  /** market | company | internal -- see agents/claim_router.py. */
  claim_kind?: string;
  routing_reason?: string;
  /** True when this verdict was remembered from an earlier identical check. */
  cached?: boolean;
  search_mode?: string;
}

/**
 * What the headline score means, built server-side (ml/score_context.py) so the
 * UI and the PDF describe it identically. `band` is read off the model's own
 * interval against the base rate, not fixed thresholds.
 */
export interface ScoreContext {
  available: boolean;
  score?: number;
  band?: "above" | "within" | "below";
  band_label?: string;
  band_reason?: string;
  measures?: string;
  base_rate?: number | null;
  base_rate_note?: string;
  comparable_mix?: { n: number; counts: Record<string, number>; sentence: string };
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
  /**
   * How much of the deck reached a structured field, and which extraction path
   * produced this report. Both are optional because reports stored before
   * these existed must still render -- the UI hides the panels when absent
   * rather than showing a zero, which would read as "we captured nothing".
   */
  extraction_coverage?: ExtractionCoverage;
  extraction_provenance?: ExtractionProvenance;
  /** Which mechanism produced final_score: the trained model or the fallback formula. */
  score_source?: string | null;
  /**
   * Claims were extracted and checked, but nothing public corroborated them.
   * Expected for an early-stage company, and deliberately NOT the same as
   * incomplete_analysis (which means the pipeline itself failed).
   */
  claims_unverified?: boolean;
  /**
   * True when claim verification never RAN -- a provider failure -- as
   * opposed to running and settling nothing. Rendering the second as the
   * first is how a report told a reader that public sources had nothing
   * on Uber.
   */
  claims_verification_degraded?: boolean;
  /**
   * Whether any component fell back because the language model was
   * unreachable, and which ones.
   *
   * Computed and stored by the backend since the degradation work, but never
   * declared on the API response model, so it never reached here -- which is
   * why bull and bear agents that never ran rendered as "No positive signals
   * identified", a statement about the company.
   */
  provider_degraded?: boolean;
  degraded_components?: Array<{ component: string; reason: string }>;
  /**
   * A distinct, milder state from `provider_degraded`. The language model DID
   * run and the verdicts below are real; what failed was the general web index
   * (DuckDuckGo rate-limited), so the claims were checked against the fallback
   * providers alone. On real deck claims the share of on-topic sources runs
   * about 94% with the general index and about 32% without it -- a weaker
   * check, not a stronger finding, and the reader needs to know which one they
   * are looking at.
   */
  evidence_search_degraded?: boolean;
  evidence_search_note?: string;
  /**
   * "provisional" when a component that moves the score did not run, so
   * this number is built from less evidence than a complete report's and is
   * not comparable with one. The note names what was missing.
   */
  score_status?: "final" | "provisional";
  score_status_note?: string;
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
      /**
       * Where the NAME came from, which is a different question from where the
       * background evidence came from. "deck" means the deck disclosed it;
       * "external_research" means the deck named nobody and agents/
       * founder_research.py searched public sources for it. These must stay
       * visually distinct in the UI -- a name this tool found is weaker
       * evidence than a name the founder put in writing, and blending them
       * would hand the reader a fact the deck never asserted.
       */
      origin?: "deck" | "external_research";
      origin_label?: string;
      discovery_sources?: string[];
    }>;
    /**
     * Output of agents/founder_research.py. Present whenever the deck named no
     * founders, whether or not the search then found any -- a confirmed "we
     * searched and found nothing" is a real diligence result and the tab shows
     * it rather than the old dead end ("No founder names were submitted").
     */
    founder_discovery?: {
      attempted?: boolean;
      found?: boolean;
      reason?: string;
      sources_consulted?: string[];
      rejected_ungrounded?: string[];
      /**
       * Four distinct states that must never render alike:
       *   searched=false, search_failed=true  -> the search could not run
       *   searched=false, search_failed unset -> research was disabled
       *   searched=true,  degraded=true       -> sources retrieved, but the
       *                                          model that reads them did not
       *                                          run (a provider outage)
       *   searched=true,  found=false         -> we looked and found nothing
       * Only the LAST is evidence about the company.
       *
       * The third was missing, and its absence is why a report said "Searched
       * 14 public source(s) for the founders of Uber. No founder name could be
       * established from them" while holding Garrett Camp's Wikipedia page.
       */
      degraded?: boolean;
      searched?: boolean;
      search_failed?: boolean;
      queries_failed?: number;
      possible_same_person?: Array<{ names: string[]; reason: string }>;
    };
    extraction_provenance?: ExtractionProvenance;
    /**
     * Output of extraction_coverage.py: how much of the deck reached a
     * structured field. Distinct from `data_quality`, which measures whether
     * the analysis INPUTS arrived. See that module's docstring for why the two
     * must never be shown as one number.
     */
    extraction_coverage?: ExtractionCoverage;
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
        founded_year?: number | null;
        outcome?: string;
        /** Why that outcome is recorded -- "listed on a stock exchange (P414)",
         *  "acquired in 2012, 7 years after founding". Empty for YC rows. */
        outcome_basis?: string;
        similarity?: number;
        /** Which corpus the row came from. */
        population?: "yc" | "market";
        population_label?: string;
        /** Wikidata permalink, on market rows only. YC rows have no per-company
         *  permalink in the dataset and inventing one would be worse than
         *  omitting it. */
        source_url?: string;
      }>;
      caveat?: string;
      /** True when nothing cleared the similarity floor, so zero rows are shown. */
      no_close_matches?: boolean;
      best_similarity?: number;
      threshold?: number;
      population_total?: number;
      /** The same rows grouped by corpus, for a UI that wants to show them
       *  side by side rather than in one ranked table. */
      by_population?: Record<string, Array<{ name: string; similarity?: number }>>;
      /**
       * The search populations, stated as structured data rather than left in
       * prose, so the UI can show the scope above the table instead of burying
       * it in a footnote.
       *
       * There are now two. The corpus used to be Y Combinator alone, and this
       * block said so; it now also covers technology companies from public
       * reference data that never went through an accelerator. Results are
       * stratified rather than pooled -- see comparables.py for the measurement
       * that forced that (a pooled ranking returned 24 of 25 rows from YC, for
       * reasons of writing style rather than business similarity).
       */
      population?: Record<string, {
        label?: string;
        n?: number;
        source?: string;
        url?: string;
        note?: string;
        matches_above_floor?: number;
        best_similarity?: number;
      }>;
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
    score_context?: ScoreContext;
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
    claims_verification_degraded: Boolean(raw?.claims_verification_degraded),
    provider_degraded: Boolean(raw?.provider_degraded),
    degraded_components: Array.isArray(raw?.degraded_components) ? raw.degraded_components : [],
    evidence_search_degraded: Boolean(raw?.evidence_search_degraded),
    evidence_search_note: String(raw?.evidence_search_note ?? ""),
    score_status: raw?.score_status === "provisional" ? "provisional" : "final",
    score_status_note: String(raw?.score_status_note ?? ""),
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
  /**
   * True when this report has no owner.
   *
   * Reports written before accounts existed carry `owner_user_id IS NULL`, and
   * are readable by every signed-in user. They are not retro-assigned to
   * whoever registered first -- inventing an owner for a report that never had
   * one is a worse answer than admitting it has none -- so the UI labels them
   * instead of quietly presenting them as the reader's own work.
   */
  shared?: boolean;
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
  /** Create an account and sign in. There is no email verification step --
   *  this deployment has no email provider, and the API says so in
   *  `email_verification_note` rather than implying otherwise. */
  register: async (email: string, password: string, displayName = ""): Promise<AuthSession> => {
    const res = await apiClient.post<AuthSession>("/auth/register", {
      email, password, display_name: displayName,
    });
    sessionToken.set(res.data.token);
    return res.data;
  },

  login: async (email: string, password: string): Promise<AuthSession> => {
    const res = await apiClient.post<AuthSession>("/auth/login", { email, password });
    sessionToken.set(res.data.token);
    return res.data;
  },

  /** Ends the session server-side, then forgets the token locally.
   *  The local clear runs even if the request fails: a token the server still
   *  knows about is worse kept than dropped. */
  logout: async (): Promise<void> => {
    try {
      await apiClient.post("/auth/logout");
    } finally {
      sessionToken.clear();
    }
  },

  whoAmI: async (): Promise<WhoAmI> => {
    const res = await apiClient.get<WhoAmI>("/auth/me");
    return res.data;
  },

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
    stage?: string;
    sector?: string;
    team_size?: number | null;
    github_url?: string;
    domain?: string;
    deck_date?: string;
    /**
     * Per-slide text, so extraction coverage can be measured at the
     * granularity the failure actually occurs at: whole slides contributing
     * nothing. `filing_text` is the pages joined with newlines, which destroys
     * the boundaries -- and without them coverage collapses to a single
     * "slide" that is either 0% or 100%.
     *
     * The backend has accepted this field all along and the upload response
     * has always returned it; the frontend simply never passed it on, so every
     * report in production read "1 of 1 content slides reached a structured
     * field" regardless of how many slides the deck had.
     */
    deck_slides?: string[];
    /** Which extraction path produced the claims, so the report can say when
     *  it was built by the degraded regex fallback. Also never sent before,
     *  which is why stored reports show a provenance method of "unknown". */
    extraction_method?: string;
    extraction_fallback_reason?: string;
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
