import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  ReactNode,
} from "react";
import {
  api,
  AnalyzeResponse,
  parseApiError,
  ScopeCheck,
  UploadResponse,
} from "../services/apiClient";

// ─── STATE SHAPE ─────────────────────────────────────────────────────────────

export type AnalysisStatus =
  | "idle"
  | "uploading"
  | "ready"      // deck parsed; waiting for the user to confirm and submit
  | "analyzing"
  | "done"
  | "error";

interface AppState {
  // Status
  status: AnalysisStatus;
  currentStage: string;        // human-readable progress label
  progressPct: number;         // 0–100

  // Data
  uploadResult: UploadResponse | null;
  report: AnalyzeResponse | null;
  sessionId: string | null;
  error: string | null;
  /**
   * Set when the backend refused because the company is not a technology
   * startup. Held separately from `error` because it is not a failure to
   * recover from -- there is no retry that would help -- and it needs its own
   * explanation rather than a red line of text.
   */
  outOfScope: ScopeCheck | null;

  // Company name the user typed
  companyName: string;

  /**
   * When the current run began, for the elapsed clock the progress panels
   * show. A run takes minutes and the backend's own stage labels do not carry
   * time, so without this the UI can say what it is doing but not how long it
   * has been doing it -- which is the question a waiting user actually has.
   */
  startedAt: number | null;
}

interface AppContextValue extends AppState {
  setCompanyName: (name: string) => void;
  /**
   * Parse the deck without starting the analysis.
   *
   * Upload used to be the first half of runAnalysis, which meant the user
   * never saw what had been extracted from their deck before the pipeline
   * committed to it. That is fine for claims and financials, which the report
   * shows with their evidence, and wrong for founder names: those go straight
   * into a live web search and a public-background assessment, so a name the
   * extractor got wrong becomes a background check on a stranger. Splitting
   * the two lets the form show the detected founders and let the user fix
   * them first.
   */
  prepareUpload: (file: File, companyName: string) => Promise<void>;
  runAnalysis: (file: File, companyName: string, founders?: string[]) => Promise<void>;
  loadSavedReport: (reportId: string) => Promise<void>;
  dismissOutOfScope: () => void;
  reset: () => void;
}

// ─── INITIAL STATE ─────────────────────────────────────────────────────────

const INITIAL: AppState = {
  status: "idle",
  currentStage: "",
  progressPct: 0,
  startedAt: null,
  uploadResult: null,
  report: null,
  sessionId: null,
  error: null,
  outOfScope: null,
  companyName: "",
};

// ─── CONTEXT ────────────────────────────────────────────────────────────────

const AppContext = createContext<AppContextValue | null>(null);

// ─── PROVIDER ───────────────────────────────────────────────────────────────

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>(INITIAL);
  // Mirrors state.uploadResult for the callbacks below, which are declared
  // with an empty dependency list and would otherwise close over the upload
  // from the first render forever.
  const uploadRef = useRef<UploadResponse | null>(null);
  const uploadedFileRef = useRef<File | null>(null);

  const setCompanyName = useCallback((name: string) => {
    setState((s) => ({ ...s, companyName: name }));
  }, []);

  const reset = useCallback(() => {
    uploadRef.current = null;
    uploadedFileRef.current = null;
    setState(INITIAL);
  }, []);

  const prepareUpload = useCallback(async (file: File, companyName: string) => {
    setState((s) => ({
      ...s,
      status: "uploading",
      currentStage: "Reading the deck…",
      progressPct: 5,
      // The clock starts here, not at "Run AI Analysis": reading the deck is
      // where an image-only deck spends two minutes in OCR, which is exactly
      // the wait a user needs to see.
      startedAt: Date.now(),
      error: null,
      outOfScope: null,
      companyName,
      report: null,
    }));
    try {
      const upload = await api.uploadPDF(file, companyName);
      uploadRef.current = upload;
      uploadedFileRef.current = file;
      setState((s) => ({
        ...s,
        uploadResult: upload,
        status: "ready",
        currentStage: "Deck parsed — review and start the analysis",
        progressPct: 15,
      }));
    } catch (err: unknown) {
      uploadRef.current = null;
      uploadedFileRef.current = null;
      const { message, scopeCheck } = parseApiError(
        err,
        "Could not read that file — check that api.py is running",
      );
      setState((s) => ({
        ...s, status: "error", currentStage: "", progressPct: 0,
        error: message, outOfScope: scopeCheck,
      }));
    }
  }, []);

  const dismissOutOfScope = useCallback(() => {
    setState((s) => ({ ...s, outOfScope: null }));
  }, []);

  const loadSavedReport = useCallback(async (reportId: string) => {
    const report = await api.getReport(reportId);
    setState((s) => ({ ...s, status: "done", report, sessionId: report.session_id || null, companyName: report.company, error: null }));
  }, []);

  /**
   * Full pipeline:
   *  1. Upload PDF → /upload-pdf
   *  2. Analyze    → /analyze
   * Progress stages update so every page can show status.
   */
  const runAnalysis = useCallback(
    async (file: File, companyName: string, founders: string[] = []) => {
      const timers: ReturnType<typeof setTimeout>[] = [];

      setState((s) => ({
        ...s,
        status: "uploading",
        currentStage: "Reading the deck…",
        progressPct: 5,
        error: null,
        outOfScope: null,
        companyName,
        startedAt: Date.now(),
      }));

      try {
        // ── STEP 1: Reuse the parse from prepareUpload when it is the same
        // file, so confirming the founders does not re-upload and re-run the
        // extraction LLM call for nothing.
        const upload =
          uploadRef.current && uploadedFileRef.current === file
            ? uploadRef.current
            : await api.uploadPDF(file, companyName);
        uploadRef.current = upload;
        uploadedFileRef.current = file;

        setState((s) => ({
          ...s,
          uploadResult: upload,
          status: "analyzing",
          currentStage: "Verifying claims with web search…",
          progressPct: 20,
        }));

        // ── STEP 2: Call /analyze ───────────────────────────────────────────
        // There is deliberately no timer-driven stage ladder here any more.
        // It used to advance labels on fixed 30/60/90/120s setTimeouts that
        // had nothing to do with what the backend was doing, so a genuinely
        // slow analysis and a hung one looked identical -- and the label on
        // screen was frequently just wrong about the current step. The
        // backend now reports its real stage on the job row, and the polling
        // loop below reads it.
        const job = await api.startAnalysis({
          company_name: companyName,
          company_description: upload.company_description,
          claims: upload.detected_claims,
          filing_text: upload.extracted_text,
          revenue: upload.revenue,
          // Was hardcoded `null`. The regex extractor has always produced a
          // burn rate; the upload response model simply did not declare the
          // field, so Pydantic dropped it, and this line then wrote null over
          // the hole. Two independent layers of the same defect meant burn rate
          // never once reached the pipeline from a real upload, which silently
          // cost a third of evidence_fusion.financial_disclosure and both of
          // deck_financials' burn-multiple and runway signals.
          burn_rate: upload.burn_rate ?? null,
          runway_months: upload.runway_months,
          // Deck metadata the score model consumes. `stage` alone is worth 42
          // points of range and `sector` 24; both were "unknown" on every
          // analysis this product has ever run. Undefined when the deck did not
          // say -- the extractor abstains rather than guessing.
          stage: upload.stage ?? undefined,
          sector: upload.sector ?? undefined,
          team_size: upload.team_size ?? null,
          github_url: upload.github_url ?? undefined,
          domain: upload.domain ?? undefined,
          // What the user confirmed on the form, falling back to whatever the
          // extractor found. Empty is a legitimate answer -- most decks have
          // no team slide -- and the Founder Analysis tab now says so instead
          // of showing an all-zero radar with no explanation.
          founders:
            founders.length > 0
              ? founders
              : (upload.detected_founders || []).map((f) => f.name).filter(Boolean),
          // Slide boundaries and extraction provenance.
          //
          // Both have been returned by /upload-pdf and accepted by /analyze
          // since they were built, and neither was ever passed between the
          // two. The consequences were visible in every report: coverage said
          // "1 of 1 content slides reached a structured field" for a 25-slide
          // deck, because without boundaries the whole deck is one slide; and
          // the extraction-provenance block recorded its method as "unknown",
          // so a report built by the degraded regex fallback could not say so.
          deck_slides: upload.deck_slides ?? [],
          extraction_method: upload.extraction_method ?? "",
          extraction_fallback_reason: upload.extraction_fallback_reason ?? "",
        });

        // Percentages are derived from which real stage the backend reports,
        // so the bar only moves when the pipeline actually moves. They are
        // ordinal markers, not a time estimate -- the steps take very
        // different amounts of time, and pretending otherwise is what the
        // old timer did.
        const STAGE_PROGRESS: Array<[string, number]> = [
          ["Verifying claims", 30],
          ["Detecting risk signals", 45],
          ["Running market", 60],
          ["Retrieving evidence", 75],
          ["Writing the investment memo", 88],
        ];
        const progressForStage = (stage: string | null | undefined): number => {
          if (!stage) return 20;
          const hit = STAGE_PROGRESS.find(([prefix]) => stage.startsWith(prefix));
          return hit ? hit[1] : 20;
        };

        let jobStatus = job;
        let elapsed = 0;
        while (jobStatus.status === "pending" || jobStatus.status === "running") {
          const queued = jobStatus.status === "pending";
          const label = queued
            ? "Queued — waiting for a worker…"
            : jobStatus.stage
              ? `${jobStatus.stage}…`
              : "Starting analysis…";
          setState((s) => ({
            ...s,
            // Elapsed time is shown because this legitimately takes minutes.
            // Telling the user how long it has actually been running is more
            // useful, and more honest, than an invented percentage.
            currentStage: elapsed > 20 ? `${label} (${Math.floor(elapsed)}s elapsed)` : label,
            progressPct: queued ? 10 : progressForStage(jobStatus.stage),
          }));
          await new Promise((resolve) => setTimeout(resolve, 3_000));
          elapsed += 3;
          jobStatus = await api.getAnalysisStatus(job.job_id);
        }
        if (jobStatus.status !== "complete" || !jobStatus.report) {
          throw new Error(jobStatus.error || "Analysis could not be completed. Please retry.");
        }
        const report = jobStatus.report;

        // Clear pending stage timers
        timers.forEach(clearTimeout);

        setState((s) => ({
          ...s,
          status: "done",
          currentStage: "Analysis complete",
          progressPct: 100,
          report,
          sessionId: report.session_id,
        }));
      } catch (err: unknown) {
        timers.forEach(clearTimeout);
        const { message, scopeCheck } = parseApiError(
          err,
          "Analysis failed — check that api.py is running",
        );

        setState((s) => ({
          ...s,
          status: "error",
          currentStage: "",
          progressPct: 0,
          error: message,
          outOfScope: scopeCheck,
        }));
      }
    },
    []
  );

  return (
    <AppContext.Provider
      value={{ ...state, setCompanyName, prepareUpload, runAnalysis, loadSavedReport, dismissOutOfScope, reset }}
    >
      {children}
    </AppContext.Provider>
  );
}

// ─── HOOK ────────────────────────────────────────────────────────────────────

export function useApp() {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error("useApp must be used inside <AppProvider>");
  return ctx;
}
