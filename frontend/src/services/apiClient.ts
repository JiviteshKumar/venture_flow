import axios from "axios";

const BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api";

export const apiClient = axios.create({
  baseURL: BASE_URL,
  timeout: 300_000, // 5 minutes — analysis takes time
  headers: { "Content-Type": "application/json" },
});

// ─── TYPES ─────────────────────────────────────────────────────────────────

export interface UploadResponse {
  session_id: string;
  extracted_text: string;
  detected_claims: string[];
  company_description: string;
  revenue: number | null;
  runway_months: number | null;
  page_count: number;
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
      claims_retrieved: number;
      docs_retrieved: number;
      sentiment_retrieved: number;
    };
  };
}

export interface ChatResponse {
  answer: string;
  confidence: number;
  has_data: boolean;
  sources: string[];
}

export interface DBStats {
  documents: number;
  claims: number;
  sentiment_records: number;
  visual_assets: number;
  qa_pairs: number;
  tables_structured: number;
  summaries: number;
  contracts: number;
  total: number;
}

const asArray = (value: unknown): string[] => {
  if (Array.isArray(value)) return value.filter(Boolean).map(String);
  if (value) return [String(value)];
  return [];
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
    sections: {
      ...sections,
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

// ─── API CALLS ──────────────────────────────────────────────────────────────

export const api = {
  /** Upload a PDF pitch deck — returns extracted text + detected claims */
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
  analyze: async (payload: {
    company_name: string;
    company_description: string;
    claims: string[];
    filing_text: string;
    revenue: number | null;
    burn_rate: number | null;
    runway_months: number | null;
  }): Promise<AnalyzeResponse> => {
    const res = await apiClient.post<AnalyzeResponse>("/analyze", payload);
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
