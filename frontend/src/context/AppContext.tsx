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

        // ── STEP 2: Staged progress labels while backend runs ───────────────
        // The backend takes 2–4 minutes. We advance labels every 30s
        // so the user sees something happening on every page.
        const stages: [number, string][] = [
          [30_000, "Detecting risk signals…"],
          [60_000, "Retrieving database evidence…"],
          [90_000, "Groq AI synthesising report…"],
          [120_000, "Finalising due diligence memo…"],
        ];
        const pcts = [40, 60, 75, 90];
        stages.forEach(([delay, label], i) => {
          const t = setTimeout(() => {
            setState((s) => ({
              ...s,
              currentStage: label,
              progressPct: pcts[i],
            }));
          }, delay);
          timers.push(t);
        });

        // ── STEP 3: Call /analyze ───────────────────────────────────────────
        const report = await api.analyze({
          company_name: companyName,
          company_description: upload.company_description,
          claims: upload.detected_claims,
          filing_text: upload.extracted_text,
          revenue: upload.revenue,
          burn_rate: null,
          runway_months: upload.runway_months,
        });

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
      value={{ ...state, setCompanyName, runAnalysis, reset }}
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
