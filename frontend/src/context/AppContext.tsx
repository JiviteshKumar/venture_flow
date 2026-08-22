import {
  createContext,
  useContext,
  useState,
  useCallback,
  ReactNode,
} from "react";
import { api, AnalyzeResponse, UploadResponse } from "../services/apiClient";

// ─── STATE SHAPE ─────────────────────────────────────────────────────────────

export type AnalysisStatus =
  | "idle"
  | "uploading"
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

  // Company name the user typed
  companyName: string;
}

interface AppContextValue extends AppState {
  setCompanyName: (name: string) => void;
  runAnalysis: (file: File, companyName: string) => Promise<void>;
  loadSavedReport: (reportId: string) => Promise<void>;
  reset: () => void;
}

// ─── INITIAL STATE ─────────────────────────────────────────────────────────

const INITIAL: AppState = {
  status: "idle",
  currentStage: "",
  progressPct: 0,
  uploadResult: null,
  report: null,
  sessionId: null,
  error: null,
  companyName: "",
};

// ─── CONTEXT ────────────────────────────────────────────────────────────────

const AppContext = createContext<AppContextValue | null>(null);

// ─── PROVIDER ───────────────────────────────────────────────────────────────

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AppState>(INITIAL);

  const setCompanyName = useCallback((name: string) => {
    setState((s) => ({ ...s, companyName: name }));
  }, []);

  const reset = useCallback(() => {
    setState(INITIAL);
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
    async (file: File, companyName: string) => {
      const timers: ReturnType<typeof setTimeout>[] = [];

      setState((s) => ({
        ...s,
        status: "uploading",
        currentStage: "Extracting text from PDF…",
        progressPct: 5,
        error: null,
        companyName,
      }));

      try {
        // ── STEP 1: Upload PDF ──────────────────────────────────────────────
        const upload = await api.uploadPDF(file, companyName);

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
          burn_rate: null,
          runway_months: upload.runway_months,
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
        const msg =
          (err as { response?: { data?: { detail?: string } }; message?: string })
            ?.response?.data?.detail ||
          (err as { message?: string })?.message ||
          "Analysis failed — check that api.py is running";

        setState((s) => ({
          ...s,
          status: "error",
          currentStage: "",
          progressPct: 0,
          error: msg,
        }));
      }
    },
    []
  );

  return (
    <AppContext.Provider
      value={{ ...state, setCompanyName, runAnalysis, loadSavedReport, reset }}
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
