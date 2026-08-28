import { useState, useEffect } from "react";
import {
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  AreaChart, Area, RadarChart, PolarGrid, PolarAngleAxis,
  PolarRadiusAxis, Radar, PieChart, Pie, Cell, BarChart, Bar,
} from "recharts";
import { CheckCircle, AlertTriangle, ChevronDown, ChevronUp, Download, ExternalLink, Upload, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { authHeaders } from "../services/apiClient";
import { useApp } from "../context/AppContext";
import { useNavigate } from "react-router-dom";
import VentureScorePanel from "../components/analysis/VentureScorePanel";

const tabs = ["Summary", "Market Validation", "Founder Analysis", "Competitor Insights"];

type ChatMessage = {
  role: "bot" | "user";
  text: string;
};

// Static chart data (market/radar/competitor stay illustrative — not company-specific)
const marketData = [
  { year: "2022", TAM: 180, SAM: 25, SOM: 5 },
  { year: "2023", TAM: 210, SAM: 30, SOM: 7 },
  { year: "2024", TAM: 250, SAM: 38, SOM: 9 },
  { year: "2025", TAM: 290, SAM: 48, SOM: 13 },
  { year: "2026", TAM: 330, SAM: 60, SOM: 18 },
  { year: "2027", TAM: 380, SAM: 72, SOM: 28 },
];

const radarData = [
  { subject: "Technical",   value: 85 },
  { subject: "Domain",      value: 80 },
  { subject: "GTM/Sales",   value: 55 },
  { subject: "Fundraising", value: 60 },
  { subject: "Operations",  value: 65 },
  { subject: "Network",     value: 70 },
];

const threatData: { name: string; value: number; color: string }[] = [];


const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: "rgba(255,255,255,0.98)", border: "1px solid rgba(15,23,42,0.09)",
      borderRadius: "12px", padding: "12px 16px",
      fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px",
      boxShadow: "0 12px 40px rgba(15,23,42,0.12)", minWidth: "130px",
    }}>
      <div style={{ color: "#94A3B8", marginBottom: "8px", fontSize: "9.5px", letterSpacing: "0.1em", textTransform: "uppercase" }}>{label}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "5px" }}>
          <div style={{ width: "5px", height: "5px", borderRadius: "50%", background: p.stroke || p.fill }} />
          <span style={{ color: "#64748B", flex: 1 }}>{p.name}</span>
          <span style={{ color: "#0B1120", fontWeight: "600" }}>${p.value}B</span>
        </div>
      ))}
    </div>
  );
};

const Panel = ({ children, style = {}, accentColor, className = "" }: any) => (
  <div className={`vf-panel ${className}`} style={{ borderLeftColor: accentColor || "transparent", ...style }}>
    {children}
  </div>
);

const SLabel = ({ children, color }: any) => (
  <div className="vf-slabel" style={{ color: color || undefined }}>{children}</div>
);

const ScoreBadge = ({ value, color, bg, border }: any) => (
  <div style={{
    display: "inline-flex", alignItems: "center", padding: "6px 14px",
    borderRadius: "8px", background: bg, border: `1px solid ${border}`,
    fontFamily: "'IBM Plex Mono', monospace", fontSize: "15px",
    fontWeight: "600", color, letterSpacing: "-0.01em",
    transition: "transform 0.2s ease, box-shadow 0.2s ease",
  }}>{value}</div>
);

// ─── CHAT PANEL ──────────────────────────────────────────────────────────────

function ChatPanel({ sessionId }: { sessionId: string | null }) {
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "bot" as const, text: "Ask me anything about this deck — financials, risks, team, or market details." },
  ]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  const send = async (q: string) => {
    if (!q.trim() || !sessionId || loading) return;
    setMessages(m => [...m, { role: "user" as const, text: q }]);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch(`${import.meta.env.VITE_API_BASE_URL || "/api"}/chat`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ session_id: sessionId, question: q }),
      });
      const data = await res.json();
      setMessages(m => [...m, {
        role: "bot" as const,
        text: data.has_data ? data.answer : "I don't have enough information in this document to answer that.",
      }]);
    } catch {
      setMessages(m => [...m, { role: "bot" as const, text: "Error — make sure api.py is running." }]);
    } finally {
      setLoading(false);
    }
  };

  const suggestions = ["What is the ARR?", "Who are the founders?", "What is the runway?", "Key risks?"];

  return (
    <div style={{
      background: "#fff", border: "1px solid rgba(15,23,42,0.08)",
      borderRadius: 14, display: "flex", flexDirection: "column", height: 480,
      boxShadow: "0 1px 4px rgba(15,23,42,0.06)",
    }}>
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid rgba(15,23,42,0.08)",
        fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 600,
        color: "#0B1120", letterSpacing: "0.06em", textTransform: "uppercase",
      }}>
        Document Chat
        {!sessionId && <span style={{ color: "#94A3B8", fontWeight: 400, marginLeft: 8, fontSize: 9 }}>(run analysis first)</span>}
      </div>

      <div style={{ flex: 1, overflowY: "auto", padding: "12px 14px", display: "flex", flexDirection: "column", gap: 8 }}>
        {messages.map((m, i) => (
          <div key={i} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "88%" }}>
            <div style={{
              background: m.role === "user" ? "#1D6FE8" : "#F7F8FA",
              border: m.role === "bot" ? "1px solid rgba(15,23,42,0.08)" : "none",
              borderRadius: m.role === "user" ? "12px 12px 4px 12px" : "12px 12px 12px 4px",
              padding: "9px 13px", fontSize: 12.5,
              color: m.role === "user" ? "#fff" : "#374151",
              lineHeight: 1.55, fontFamily: "'Figtree', sans-serif",
            }}>
              {m.text}
            </div>
          </div>
        ))}
        {loading && (
          <div style={{ alignSelf: "flex-start" }}>
            <div style={{
              background: "#F7F8FA", border: "1px solid rgba(15,23,42,0.08)",
              borderRadius: "12px 12px 12px 4px", padding: "9px 13px",
            }}>
              <div style={{ display: "flex", gap: 4 }}>
                {[0,1,2].map(i => (
                  <motion.div key={i} style={{ width: 5, height: 5, borderRadius: "50%", background: "#CBD5E1" }}
                    animate={{ opacity: [1, 0.3, 1] }} transition={{ repeat: Infinity, duration: 1, delay: i * 0.2 }} />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {messages.length === 1 && (
        <div style={{ padding: "0 14px 10px", display: "flex", gap: 6, flexWrap: "wrap" }}>
          {suggestions.map(s => (
            <button key={s} onClick={() => send(s)} disabled={!sessionId} style={{
              background: "transparent", border: "1px solid rgba(15,23,42,0.1)",
              borderRadius: 20, padding: "4px 10px", fontSize: 10.5,
              fontFamily: "'IBM Plex Mono', monospace", color: "#64748B",
              cursor: sessionId ? "pointer" : "not-allowed", transition: "all 0.15s ease",
            }}>{s}</button>
          ))}
        </div>
      )}

      <form onSubmit={e => { e.preventDefault(); send(input); }} style={{
        padding: "10px 14px", borderTop: "1px solid rgba(15,23,42,0.08)", display: "flex", gap: 8,
      }}>
        <input
          value={input} onChange={e => setInput(e.target.value)}
          placeholder={sessionId ? "Ask about this deck…" : "Run analysis first"}
          disabled={!sessionId || loading}
          style={{
            flex: 1, background: "#F7F8FA", border: "1px solid rgba(15,23,42,0.1)",
            borderRadius: 8, padding: "8px 12px", fontSize: 12.5,
            fontFamily: "'Figtree', sans-serif", color: "#0B1120", outline: "none",
          }}
        />
        <button type="submit" disabled={!sessionId || loading || !input.trim()} style={{
          background: "#1D6FE8", border: "none", borderRadius: 8,
          padding: "8px 14px", fontSize: 12, fontWeight: 600,
          color: "#fff", cursor: "pointer",
          opacity: (!sessionId || loading || !input.trim()) ? 0.4 : 1,
        }}>Send</button>
      </form>
    </div>
  );
}

type Comment = { id: string; author_name: string; body: string; created_at: string };

// Team collaboration on a report (p3). No accounts exist yet, so
// `authorName` is a free-text field, not a verified identity -- this is
// shared commenting on one Neon database, honestly short of real per-user
// collaboration until Section 3 (auth) of the Ship List happens.
function CommentsPanel({ reportId }: { reportId: string | null }) {
  const [comments, setComments] = useState<Comment[]>([]);
  const [authorName, setAuthorName] = useState("");
  const [body, setBody] = useState("");
  const [posting, setPosting] = useState(false);

  const refresh = () => {
    if (!reportId) return;
    fetch(`${import.meta.env.VITE_API_BASE_URL || "/api"}/reports/${reportId}/comments`, { headers: authHeaders() })
      .then((res) => (res.ok ? res.json() : []))
      .then(setComments)
      .catch(() => setComments([]));
  };

  useEffect(refresh, [reportId]);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reportId || !body.trim() || posting) return;
    setPosting(true);
    try {
      const res = await fetch(`${import.meta.env.VITE_API_BASE_URL || "/api"}/reports/${reportId}/comments`, {
        method: "POST",
        headers: authHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ author_name: authorName || "Anonymous", body }),
      });
      if (res.ok) {
        setBody("");
        refresh();
      }
    } finally {
      setPosting(false);
    }
  };

  return (
    <div style={{
      background: "#fff", border: "1px solid rgba(15,23,42,0.08)",
      borderRadius: 14, marginTop: 14, boxShadow: "0 1px 4px rgba(15,23,42,0.06)",
    }}>
      <div style={{
        padding: "12px 16px", borderBottom: "1px solid rgba(15,23,42,0.08)",
        fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 600,
        color: "#0B1120", letterSpacing: "0.06em", textTransform: "uppercase",
      }}>
        Notes {!reportId && <span style={{ color: "#94A3B8", fontWeight: 400, marginLeft: 8, fontSize: 9 }}>(run analysis first)</span>}
      </div>
      <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 8, maxHeight: 220, overflowY: "auto" }}>
        {comments.length === 0 && <div style={{ fontSize: 12, color: "#94A3B8", fontFamily: "'Figtree', sans-serif" }}>No notes yet.</div>}
        {comments.map((c) => (
          <div key={c.id} style={{ fontSize: 12.5, fontFamily: "'Figtree', sans-serif", color: "#374151" }}>
            <span style={{ fontWeight: 600, color: "#0B1120" }}>{c.author_name}</span>
            <span style={{ color: "#94A3B8", fontSize: 10.5, marginLeft: 6 }}>{new Date(c.created_at).toLocaleString()}</span>
            <div style={{ marginTop: 2 }}>{c.body}</div>
          </div>
        ))}
      </div>
      <form onSubmit={submit} style={{ padding: "10px 14px", borderTop: "1px solid rgba(15,23,42,0.08)", display: "flex", flexDirection: "column", gap: 6 }}>
        <input
          value={authorName} onChange={(e) => setAuthorName(e.target.value)}
          placeholder="Your name (optional)" disabled={!reportId}
          style={{ background: "#F7F8FA", border: "1px solid rgba(15,23,42,0.1)", borderRadius: 8, padding: "6px 10px", fontSize: 12, fontFamily: "'Figtree', sans-serif", outline: "none" }}
        />
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={body} onChange={(e) => setBody(e.target.value)}
            placeholder={reportId ? "Add a note for the deal team…" : "Run analysis first"}
            disabled={!reportId || posting}
            style={{ flex: 1, background: "#F7F8FA", border: "1px solid rgba(15,23,42,0.1)", borderRadius: 8, padding: "8px 12px", fontSize: 12.5, fontFamily: "'Figtree', sans-serif", outline: "none" }}
          />
          <button type="submit" disabled={!reportId || posting || !body.trim()} style={{
            background: "#1D6FE8", border: "none", borderRadius: 8, padding: "8px 14px",
            fontSize: 12, fontWeight: 600, color: "#fff", cursor: "pointer",
            opacity: (!reportId || posting || !body.trim()) ? 0.4 : 1,
          }}>Post</button>
        </div>
      </form>
    </div>
  );
}

// ─── EMPTY STATE ─────────────────────────────────────────────────────────────

function EmptyAnalysis() {
  const navigate = useNavigate();
  const { status, currentStage, progressPct } = useApp();
  const isAnalyzing = status === "uploading" || status === "analyzing";

  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", minHeight: "60vh", textAlign: "center",
      padding: "40px 24px", fontFamily: "'Figtree', sans-serif",
    }}>
      {isAnalyzing ? (
        <>
          <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1.2, ease: "linear" }} style={{ marginBottom: 24 }}>
            <Zap size={36} color="#1D6FE8" />
          </motion.div>
          <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 22, marginBottom: 8, color: "#0B1120" }}>
            Agents are running…
          </div>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#94A3B8", marginBottom: 16 }}>
            {currentStage}
          </div>
          <div style={{ width: 240, height: 4, background: "rgba(15,23,42,0.07)", borderRadius: 4, overflow: "hidden" }}>
            <motion.div style={{ height: "100%", background: "#1D6FE8", borderRadius: 4 }}
              animate={{ width: `${progressPct}%` }} transition={{ duration: 0.5 }} />
          </div>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#94A3B8", marginTop: 8 }}>
            {progressPct}% complete
          </div>
        </>
      ) : (
        <>
          <div style={{
            width: 64, height: 64, borderRadius: 18,
            background: "rgba(29,111,232,0.08)", border: "1px solid rgba(29,111,232,0.18)",
            display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20,
          }}>
            <Upload size={28} color="#1D6FE8" strokeWidth={1.5} />
          </div>
          <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 22, marginBottom: 8, color: "#0B1120" }}>
            No analysis yet
          </div>
          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#94A3B8", marginBottom: 24, maxWidth: 300 }}>
            Upload and analyse a pitch deck to see the full report here.
          </div>
          <button onClick={() => navigate("/upload")} style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            background: "#1D6FE8", color: "#fff", border: "none",
            borderRadius: 10, padding: "11px 22px", fontFamily: "'Figtree', sans-serif",
            fontSize: 14, fontWeight: 600, cursor: "pointer",
          }}>
            <Upload size={15} /> Upload a Deck
          </button>
        </>
      )}
    </div>
  );
}

// ─── MAIN COMPONENT ───────────────────────────────────────────────────────────

const Analysis = () => {
  // EVERY hook must be declared here, above the `if (!report)` early return
  // below. React identifies hooks by call order, so a hook declared after a
  // conditional return is called on some renders and not others.
  //
  // `pdfExporting` used to live ~85 lines further down, next to the export
  // handler that uses it. That read tidily and crashed the whole application:
  // with a report loaded this component called five hooks, and the moment
  // `report` became null -- which happens when the sidebar's Settings button
  // fires reset(), among other paths -- the early return fired first and only
  // four ran. React then threw "Rendered fewer hooks than expected", which is
  // unrecoverable, so the root ErrorBoundary replaced the entire UI with
  // "Something went wrong". It presented as random breakage while navigating
  // between pages, because what actually mattered was the report going away
  // underneath a mounted Analysis page.
  const [activeTab, setActiveTab] = useState("Summary");
  const [ddOpen, setDdOpen] = useState(false);
  const [pdfExporting, setPdfExporting] = useState(false);
  const { report, sessionId } = useApp();
  const navigate = useNavigate();

  // If no report, show empty/loading
  if (!report) {
    return (
      <div className="an-root" style={{ fontFamily: "'Figtree', sans-serif", color: "#0B1120", minHeight: "100vh", background: "#F0F2F5" }}>
        <EmptyAnalysis />
      </div>
    );
  }

  // ── Derive display values from real report ────────────────────────────────
  const score = report.final_score;
  const scoreColor = score >= 75 ? "#0EA66A" : score >= 50 ? "#C47A0A" : "#D93025";
  const riskValue = Math.min(100, Math.round(report.risk_signals_found * 3.5 + 10));
  const riskLabel = riskValue >= 70 ? "High" : riskValue >= 40 ? "Moderate" : "Low";
  const riskColor = riskValue >= 70 ? "#D93025" : riskValue >= 40 ? "#C47A0A" : "#0EA66A";

  const today = new Date().toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  const deckId = `#${report.company.slice(0, 3).toUpperCase()}-${new Date().getFullYear()}-001`;

  // Real claims from backend
  const claimsDetails = report.sections?.claims?.details ?? [];
  const market = report.sections?.market;
  const team = report.sections?.team;
  const bullCase = report.sections?.bull_case;
  const bearCase = report.sections?.bear_case;

  // DD questions generated from key concerns
  const ddQuestions = [
    ...(report.key_concerns.slice(0, 3).map(c => `Please clarify: ${c}`)),
    "What is the current enterprise sales pipeline depth and average contract value?",
    "Can you provide documentation to support all verified claims?",
  ];

  // Bull & Bear from real report
  const bullItems = (bullCase?.signals ?? report.positive_factors.map(f => ({ finding: f, evidence: "Risk analysis" }))).slice(0, 3).map(item => ({ text: item.finding, tip: item.evidence }));
  const bearItems = (bearCase?.signals ?? report.red_flags.map(f => ({ finding: f, evidence: "Risk analysis" }))).slice(0, 3).map(item => ({ text: item.finding, tip: item.evidence }));
  const teamRadarData = team?.capabilities?.length
    ? team.capabilities.map(item => ({ subject: item.area, value: Math.max(0, Math.min(100, Number(item.score) || 0)), evidence: item.evidence }))
    : [];
  /**
   * Founder background checks (agents/founder_verifier.py).
   *
   * This is the other half of why the Founder Analysis tab was empty. The
   * radar is driven by the team specialist agent, which only ever saw the deck
   * text -- and most decks have no team slide, so it correctly returned no
   * capabilities and the chart drew every axis at zero with no explanation.
   * The verifier that *would* have had something to say never ran at all,
   * because nothing populated DiligenceRequest.founders until the upload form
   * gained a founders field and structured_extractor started reading the team
   * slide.
   */
  const founderChecks = (report.sections?.founder_verification ?? []).filter(f => f?.available);

  // Claims table from real claim details
  const claimsTableData = claimsDetails.slice(0, 5).map(c => ({
    claim: c.claim.slice(0, 30) + (c.claim.length > 30 ? "…" : ""),
    founder: "As stated",
    aiEstimate: c.verdict === "SUPPORTS" ? "Confirmed" : c.verdict === "REFUTES" ? "Disputed" : "Unverified",
    match: c.verdict === "SUPPORTS" ? "verified" : c.verdict === "REFUTES" ? "flagged" : "close",
    delta: `${Math.round(c.confidence * 100)}%`,
  }));

  /**
   * Comparable companies.
   *
   * This tab reported "No comparable companies were found" on every single
   * analysis, and the cause was not the similarity search -- that works.
   * `report.similar_companies` is `db.find_similar_companies()`, a trigram
   * match over the *user's own* companies table restricted to rows that
   * already have a report or a portfolio investment. On a fresh single-user
   * database analysing a different company each time it correctly returns
   * nothing, every time.
   *
   * The real comparables were being computed all along and never rendered:
   * `sections.market_comparables` is comparables.py's cosine-similarity search
   * over 1,560 real Y Combinator companies, which returns five matches for any
   * non-empty description. So the YC comps are the primary source here and the
   * portfolio overlap is kept as a clearly-labelled secondary signal, since
   * "have I looked at something like this before" is a different and also
   * useful question.
   */
  const marketComparables = report.sections?.market_comparables;
  const ycComparables = (marketComparables?.available && marketComparables.comparables) || [];
  const portfolioMatches = report.similar_companies ?? [];
  const competitors = ycComparables.length
    ? ycComparables.map(c => ({
        name: c.name,
        domain: c.batch ?? null,
        sector: c.industry ?? null,
        similarity: c.similarity,
        outcome: c.outcome ?? null,
      }))
    : portfolioMatches.map(c => ({
        name: c.name,
        domain: c.domain ?? null,
        sector: c.sector ?? null,
        similarity: c.similarity,
        outcome: null as string | null,
      }));
  const comparablesSource = ycComparables.length
    ? (marketComparables?.source ?? "Y Combinator comparable companies")
    : portfolioMatches.length
      ? "Your own prior reports and portfolio (name/domain similarity)"
      : "";

  const exportReport = () => {
    const lines = [
      `VentureFlow Due Diligence Report`,
      `Company: ${report.company}`,
      `Generated: ${today}`,
      `Overall score: ${score}/100`,
      `Recommendation: ${report.recommendation}`,
      `Risk level: ${report.risk_level}`,
      `Claims checked: ${report.claims_verified}`,
      `Claims supported: ${report.claims_supported}`,
      `Claims refuted: ${report.claims_refuted}`,
      `Claims uncertain: ${report.claims_uncertain}`,
      "",
      "AI INVESTMENT MEMO",
      report.ai_analysis || "No AI memo was generated.",
      "",
      "KEY CONCERNS",
      ...(report.key_concerns.length ? report.key_concerns.map((item) => `- ${item}`) : ["- None identified."]),
      "",
      "RED FLAGS",
      ...(report.red_flags.length ? report.red_flags.map((item) => `- ${item}`) : ["- None identified."]),
      "",
      "POSITIVE FACTORS",
      ...(report.positive_factors.length ? report.positive_factors.map((item) => `- ${item}`) : ["- None identified."]),
    ];
    const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${report.company.replace(/[^a-z0-9]+/gi, "-").replace(/(^-|-$)/g, "").toLowerCase() || "ventureflow"}-due-diligence.txt`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  };

  const exportReportPdf = async () => {
    if (!report.report_id) return;
    setPdfExporting(true);
    try {
      const res = await fetch(`${import.meta.env.VITE_API_BASE_URL || "/api"}/reports/${report.report_id}/pdf`, { headers: authHeaders() });
      if (!res.ok) throw new Error("PDF export failed");
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${report.company.replace(/[^a-z0-9]+/gi, "-").replace(/(^-|-$)/g, "").toLowerCase() || "ventureflow"}-due-diligence.pdf`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
    } catch {
      exportReport(); // fall back to the plain-text export if the PDF endpoint is unavailable
    } finally {
      setPdfExporting(false);
    }
  };

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=IBM+Plex+Mono:wght@300;400;500;600&family=Figtree:wght@300;400;500;600;700&display=swap');

        :root {
          --bg: #F0F2F5;
          --surface: #FFFFFF;
          --surface-2: #F7F8FA;
          --border: rgba(15,23,42,0.08);
          --border-strong: rgba(15,23,42,0.13);
          --text-primary: #0B1120;
          --text-secondary: #4A5568;
          --text-muted: #94A3B8;
          --blue: #1D6FE8;
          --green: #0EA66A;
          --amber: #C47A0A;
          --red: #D93025;
          --shadow-sm: 0 1px 4px rgba(15,23,42,0.06), 0 2px 12px rgba(15,23,42,0.04);
          --shadow-md: 0 4px 20px rgba(15,23,42,0.08), 0 1px 4px rgba(15,23,42,0.05);
          --radius: 14px;
        }

        .an-root { font-family: 'Figtree', sans-serif; color: var(--text-primary); min-height: 100vh; background: var(--bg); }

        /* ── VentureFlow Score panel ─────────────────────────────────── */
        .vs-card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 20px 22px; margin-bottom: 18px; }
        .vs-card-muted { background: var(--surface-2); }
        .vs-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
        .vs-eyebrow { font-family: 'IBM Plex Mono', monospace; font-size: 10px; letter-spacing: 0.09em; text-transform: uppercase; color: var(--text-secondary); margin: 0; font-weight: 600; }
        .vs-sub { font-size: 11.5px; color: var(--text-secondary); margin: 4px 0 0; }
        .vs-conf { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; font-weight: 600; padding: 5px 11px; border-radius: 20px; border: 1px solid; white-space: nowrap; }
        .vs-score-row { display: flex; align-items: baseline; gap: 18px; margin: 16px 0 6px; flex-wrap: wrap; }
        .vs-score-main { display: flex; align-items: baseline; gap: 3px; }
        .vs-score { font-size: 46px; font-weight: 700; letter-spacing: -0.02em; line-height: 1; font-variant-numeric: tabular-nums; }
        .vs-score-of { font-size: 15px; color: var(--text-secondary); font-weight: 500; }
        .vs-score-meta { display: flex; flex-direction: column; gap: 3px; }
        .vs-range { font-size: 12.5px; color: var(--text-secondary); }
        .vs-range strong { color: var(--text-primary); font-variant-numeric: tabular-nums; }
        .vs-band { font-size: 11.5px; font-weight: 600; }
        .vs-track { margin: 14px 0 18px; }
        .vs-track-bar { position: relative; height: 7px; background: var(--surface-2); border-radius: 4px; border: 1px solid var(--border); }
        .vs-track-range { position: absolute; top: 0; bottom: 0; background: rgba(29,111,232,0.16); border-radius: 4px; }
        .vs-track-base { position: absolute; top: -4px; bottom: -4px; width: 2px; background: var(--text-secondary); opacity: 0.5; }
        .vs-track-point { position: absolute; top: 50%; width: 12px; height: 12px; border-radius: 50%; transform: translate(-50%, -50%); border: 2px solid var(--surface); box-shadow: 0 1px 4px rgba(0,0,0,0.18); }
        .vs-track-labels { display: flex; justify-content: space-between; font-family: 'IBM Plex Mono', monospace; font-size: 9px; color: var(--text-secondary); margin-top: 6px; }
        .vs-breakdown { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin-bottom: 14px; }
        .vs-bd-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 9px 13px; font-size: 12.5px; border-bottom: 1px solid var(--border); }
        .vs-bd-row:last-child { border-bottom: none; }
        .vs-bd-row span { color: var(--text-secondary); }
        .vs-bd-row strong { font-variant-numeric: tabular-nums; font-size: 13px; }
        .vs-bd-total { background: var(--surface-2); }
        .vs-bd-total span { color: var(--text-primary); font-weight: 600; }
        .vs-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .vs-stat { background: var(--surface-2); border: 1px solid var(--border); border-radius: 9px; padding: 9px 11px; display: flex; flex-direction: column; gap: 4px; }
        .vs-stat-k { font-family: 'IBM Plex Mono', monospace; font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); }
        .vs-stat-v { font-size: 12.5px; font-weight: 600; display: inline-flex; align-items: center; gap: 4px; font-variant-numeric: tabular-nums; }
        .vs-warn { display: flex; align-items: flex-start; gap: 7px; font-size: 12px; line-height: 1.5; color: #8A2018; background: rgba(217,48,37,0.06); border: 1px solid rgba(217,48,37,0.18); border-radius: 9px; padding: 10px 12px; margin: 14px 0 0; }
        .vs-unavailable { display: flex; align-items: flex-start; gap: 9px; margin-top: 12px; font-size: 12.5px; color: var(--text-secondary); }
        .vs-unavailable strong { color: var(--text-primary); display: block; margin-bottom: 3px; font-size: 13px; }
        .vs-unavailable p { margin: 0; line-height: 1.5; }
        .vs-details { margin-top: 14px; border-top: 1px solid var(--border); padding-top: 12px; }
        .vs-details summary { cursor: pointer; font-size: 11.5px; color: var(--text-secondary); display: inline-flex; align-items: center; gap: 5px; user-select: none; }
        .vs-details summary:hover { color: var(--text-primary); }
        .vs-details summary:focus-visible { outline: 2px solid var(--accent, #1D6FE8); outline-offset: 3px; border-radius: 4px; }
        .vs-dl { margin: 11px 0 0; display: flex; flex-direction: column; gap: 8px; }
        .vs-dl > div { display: grid; grid-template-columns: 148px 1fr; gap: 12px; font-size: 12px; }
        .vs-dl dt { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); padding-top: 2px; }
        .vs-dl dd { margin: 0; line-height: 1.55; }
        .vs-caveat { font-size: 11.5px; line-height: 1.6; color: var(--text-secondary); margin: 12px 0 0; padding-top: 10px; border-top: 1px dashed var(--border); }

        @media (max-width: 720px) {
          .vs-stats { grid-template-columns: 1fr; }
          .vs-dl > div { grid-template-columns: 1fr; gap: 2px; }
          .vs-score { font-size: 38px; }
        }

        .an-header { padding: 22px 32px 0; background: var(--surface); border-bottom: 1px solid var(--border); position: relative; overflow: hidden; }

        .an-header::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px; background: linear-gradient(90deg, var(--blue), var(--green), var(--amber), var(--blue)); background-size: 300% 100%; animation: hdr-shimmer 5s linear infinite; }

        @keyframes hdr-shimmer { 0% { background-position: 300% 0; } 100% { background-position: -300% 0; } }

        .an-header-top { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 0; }

        .an-meta-row { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }

        .an-eyebrow { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: var(--text-muted); letter-spacing: 0.12em; text-transform: uppercase; }

        .an-id-badge { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: var(--blue); letter-spacing: 0.06em; padding: 3px 10px; background: rgba(29,111,232,0.08); border: 1px solid rgba(29,111,232,0.2); border-radius: 20px; font-weight: 500; }

        .an-title { font-family: 'DM Serif Display', serif; font-size: 30px; font-weight: 400; letter-spacing: -0.01em; color: var(--text-primary); margin: 0 0 5px; line-height: 1; }

        .an-subtitle { font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; color: var(--text-muted); margin-bottom: 20px; }

        .an-header-actions { display: flex; align-items: center; gap: 8px; padding-top: 4px; }

        .an-export-btn { display: inline-flex; align-items: center; gap: 6px; font-family: 'Figtree', sans-serif; font-size: 12px; font-weight: 600; padding: 7px 14px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border-strong); color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease; }

        .an-export-btn:hover { background: var(--text-primary); color: #fff; border-color: var(--text-primary); }

        .an-confidence-chip { display: inline-flex; align-items: center; gap: 6px; font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: var(--green); background: rgba(14,166,106,0.08); border: 1px solid rgba(14,166,106,0.22); padding: 6px 12px; border-radius: 20px; font-weight: 500; }

        .an-tabs { display: flex; gap: 2px; }

        .an-tab { font-family: 'Figtree', sans-serif; font-size: 13px; font-weight: 500; padding: 13px 20px; border: none; border-bottom: 2.5px solid transparent; background: transparent; color: var(--text-muted); cursor: pointer; transition: color 0.15s ease, border-color 0.15s ease; white-space: nowrap; letter-spacing: -0.01em; }

        .an-tab:hover { color: var(--text-secondary); }
        .an-tab-active { color: var(--blue); border-bottom-color: var(--blue); }

        .an-body { padding: 16px; display: flex; flex-direction: column; gap: 14px; }

        .vf-panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 22px; box-shadow: var(--shadow-sm); border-left-width: 3px; transition: box-shadow 0.2s ease, transform 0.2s ease; }

        .vf-panel:hover { box-shadow: var(--shadow-md); transform: translateY(-1px); }
        .vf-panel-neutral { border-left-color: var(--border) !important; }

        .vf-slabel { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: var(--text-muted); letter-spacing: 0.12em; text-transform: uppercase; font-weight: 500; margin-bottom: 14px; }

        .an-case-item { display: flex; gap: 11px; align-items: flex-start; margin-bottom: 8px; padding: 11px 13px; border-radius: 9px; background: var(--surface-2); border: 1px solid var(--border); transition: border-color 0.15s ease, background 0.15s ease; cursor: default; }

        .an-case-item:hover { border-color: var(--border-strong); background: #F3F5F8; }

        .an-case-text { font-size: 13px; color: var(--text-secondary); line-height: 1.6; flex: 1; }

        .score-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow-sm); transition: transform 0.2s ease, box-shadow 0.2s ease; cursor: default; }

        .score-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }

        .an-verdict-headline { font-family: 'DM Serif Display', serif; font-size: 20px; color: var(--text-primary); letter-spacing: -0.02em; margin-bottom: 8px; line-height: 1.2; }

        .verdict-tag { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; padding: 5px 12px; border-radius: 20px; letter-spacing: 0.07em; font-weight: 500; cursor: default; transition: transform 0.15s ease; }

        .verdict-tag:hover { transform: translateY(-1px); }

        .dd-accordion { margin-top: 16px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }

        .dd-accordion-trigger { width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: var(--surface-2); border: none; cursor: pointer; font-family: 'Figtree', sans-serif; font-size: 13px; font-weight: 600; color: var(--text-primary); transition: background 0.14s ease; letter-spacing: -0.01em; }

        .dd-accordion-trigger:hover { background: #EEEFF2; }

        .dd-accordion-body { padding: 14px 16px; background: var(--surface); }

        .dd-question { display: flex; gap: 10px; align-items: flex-start; padding: 9px 0; border-bottom: 1px solid rgba(15,23,42,0.05); }

        .dd-question:last-child { border-bottom: none; }

        .dd-q-num { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--blue); font-weight: 600; flex-shrink: 0; min-width: 22px; }

        .dd-q-text { font-size: 12.5px; color: var(--text-secondary); line-height: 1.55; }

        .mkt-stat { padding: 14px; background: var(--surface-2); border-radius: 10px; border: 1px solid var(--border); transition: border-color 0.15s ease, transform 0.15s ease; cursor: default; }

        .mkt-stat:hover { border-color: var(--border-strong); transform: translateY(-1px); }

        .claims-table { width: 100%; border-collapse: collapse; }

        .claims-th { font-family: 'IBM Plex Mono', monospace; font-size: 9px; color: var(--text-muted); letter-spacing: 0.12em; text-transform: uppercase; text-align: left; padding: 0 12px 10px 0; border-bottom: 1px solid var(--border); }

        .claims-tr { border-bottom: 1px solid rgba(15,23,42,0.05); transition: background 0.12s ease; }

        .claims-tr:hover { background: var(--surface-2); }
        .claims-tr:last-child { border-bottom: none; }

        .claims-td { font-size: 12.5px; padding: 9px 12px 9px 0; color: var(--text-secondary); }

        .match-chip { font-family: 'IBM Plex Mono', monospace; font-size: 9px; padding: 3px 8px; border-radius: 20px; font-weight: 600; }

        .an-founder-avatar { width: 40px; height: 40px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-size: 12px; font-weight: 600; color: var(--text-secondary); flex-shrink: 0; transition: transform 0.2s ease; }

        .vf-panel:hover .an-founder-avatar { transform: scale(1.06); }

        .an-founder-name { font-size: 13.5px; font-weight: 600; color: var(--text-primary); letter-spacing: -0.01em; }
        .an-founder-role { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--text-muted); margin-top: 2px; }
        .an-founder-desc { font-size: 12.5px; color: var(--text-secondary); line-height: 1.6; margin: 0 0 12px; }

        .an-risk-pill { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; padding: 4px 10px; border-radius: 20px; letter-spacing: 0.07em; font-weight: 500; }

        .an-comp-table { width: 100%; border-collapse: collapse; }

        .an-comp-th { font-family: 'IBM Plex Mono', monospace; font-size: 9px; color: var(--text-muted); letter-spacing: 0.12em; text-transform: uppercase; text-align: left; padding: 0 12px 12px 0; border-bottom: 1px solid var(--border); font-weight: 500; }

        .an-comp-tr { border-bottom: 1px solid rgba(15,23,42,0.05); transition: background 0.12s ease; cursor: default; }

        .an-comp-tr:hover { background: var(--surface-2); }
        .an-comp-tr:last-child { border-bottom: none; }
        .an-comp-td { font-size: 12.5px; padding: 11px 12px 11px 0; }

        .an-threat-row { display: flex; justify-content: space-between; align-items: center; padding: 7px 9px; border-radius: 7px; margin-bottom: 3px; transition: background 0.14s ease; cursor: default; }

        .an-threat-row:hover { background: var(--surface-2); }

        .tab-content-enter { animation: tab-fade-in 0.28s ease forwards; }

        @keyframes tab-fade-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

        [data-tip] { position: relative; cursor: default; }
        [data-tip]:hover::after { content: attr(data-tip); position: absolute; bottom: calc(100% + 7px); left: 50%; transform: translateX(-50%); background: rgba(11,17,32,0.92); color: #F0F2F5; padding: 5px 10px; border-radius: 6px; font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; white-space: nowrap; pointer-events: none; z-index: 200; }
        [data-tip]:hover::before { content: ''; position: absolute; bottom: calc(100% + 3px); left: 50%; transform: translateX(-50%); border: 4px solid transparent; border-top-color: rgba(11,17,32,0.92); z-index: 200; pointer-events: none; }
      `}</style>

      <div className="an-root">
        {/* HEADER */}
        <div className="an-header">
          <div className="an-header-top">
            <div>
              <div className="an-meta-row">
                <span className="an-eyebrow">Analysis Report</span>
                <span className="an-id-badge">{deckId}</span>
              </div>
              <h1 className="an-title">{report.company}</h1>
              <p className="an-subtitle">Analyzed {today} · {report.claims_verified} claims checked</p>
            </div>
            <div className="an-header-actions">
              {/* This chip rendered the final score but labelled it "data
                  confidence", which are different quantities -- a 30/100
                  investment score was being presented as "30% data
                  confidence". Label it as what it actually is. */}
              <div className="an-confidence-chip">
                {Math.round(score)}/100 overall score
              </div>
              <button className="an-export-btn" type="button" onClick={exportReportPdf} disabled={pdfExporting} aria-label="Export due diligence report as PDF">
                <Download size={12} strokeWidth={2} />
                {pdfExporting ? "Exporting…" : "Export PDF"}
              </button>
            </div>
          </div>

          <div className="an-tabs">
            {tabs.map((t) => (
              <button key={t} className={`an-tab${activeTab === t ? " an-tab-active" : ""}`} onClick={() => setActiveTab(t)}>
                {t}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 0 }}>
          <div className="an-body">
            {/* Two different situations that used to share one alarming
                message. A pipeline failure and "this company is too early for
                anyone to have written about it" call for very different
                reactions from an investor, so they say different things. */}
            {report.incomplete_analysis && (
              <div role="alert" style={{ marginBottom: 14, padding: "12px 14px", border: "1px solid #F5C2C2", borderRadius: 10, background: "#FFF5F5", color: "#9B1C1C", fontSize: 13 }}>
                Analysis is incomplete: key verification or specialist-agent results were unavailable. The score is capped and should not be used as an investment recommendation.
              </div>
            )}
            {!report.incomplete_analysis && report.claims_unverified && (
              <div role="status" style={{ marginBottom: 14, padding: "12px 14px", border: "1px solid #F0D9A8", borderRadius: 10, background: "#FFFBF0", color: "#7A5514", fontSize: 13, lineHeight: 1.55 }}>
                <strong>No deck claim could be independently corroborated.</strong> Every claim was
                searched, but public sources had nothing specific enough to confirm or contradict
                it — normal for a company this early, and not a sign the analysis failed. The score
                already reflects this, and an INVEST verdict is withheld until at least two claims
                verify. Treat the numbers below as founder-reported.
              </div>
            )}

            {/* ── SUMMARY ── */}
            {activeTab === "Summary" && (
              <div className="tab-content-enter">
                {/* The trained model's score leads the summary. It is the one
                    number on this page that came from a fitted, calibrated
                    model rather than from an LLM or a hand-tuned formula, so
                    it sits above the derived stat cards rather than among
                    them. */}
                <VentureScorePanel
                  data={report.sections?.venture_score}
                  reportedScore={Math.round(score)}
                  incompleteAnalysis={report.incomplete_analysis}
                />

                <div className="an-stat-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px" }}>
                  {[
                    { label: "Overall Score", value: `${Math.round(score)} / 100`, color: scoreColor, bg: `${scoreColor}14`, border: `${scoreColor}30`, tip: "Composite investment readiness" },
                    { label: "Market Evidence", value: `${Math.round((market?.confidence ?? 0) * 100)}%`, color: "#0EA66A", bg: "rgba(14,166,106,0.08)", border: "rgba(14,166,106,0.2)", tip: "Evidence confidence from the market agent" },
                    { label: "Claims Verified", value: `${report.claims_supported}/${report.claims_verified}`, color: "#1D6FE8", bg: "rgba(29,111,232,0.08)", border: "rgba(29,111,232,0.2)", tip: "Web-verified claims" },
                    { label: "Risk Level", value: riskLabel, color: riskColor, bg: `${riskColor}14`, border: `${riskColor}30`, tip: "Blended risk assessment" },
                  ].map((s, i) => (
                    <motion.div key={i} className="score-card" data-tip={s.tip}
                      initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: i * 0.07, duration: 0.35, ease: [0.22, 1, 0.36, 1] }}>
                      <SLabel>{s.label}</SLabel>
                      <ScoreBadge value={s.value} color={s.color} bg={s.bg} border={s.border} />
                    </motion.div>
                  ))}
                </div>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "12px" }}>
                  <Panel accentColor="#0EA66A">
                    <SLabel color="#0EA66A">▲ Bull Case</SLabel>
                    {bullItems.length > 0 ? bullItems.map((item, i) => (
                      <div key={i} className="an-case-item" data-tip={item.tip}>
                        <CheckCircle size={14} color="#0EA66A" style={{ marginTop: "2px", flexShrink: 0 }} strokeWidth={2.2} />
                        <span className="an-case-text">{item.text}</span>
                      </div>
                    )) : (
                      <div className="an-case-item"><span className="an-case-text" style={{ color: "#94A3B8" }}>No positive signals identified.</span></div>
                    )}
                  </Panel>

                  <Panel accentColor="#C47A0A">
                    <SLabel color="#C47A0A">▼ Bear Case</SLabel>
                    {bearItems.length > 0 ? bearItems.map((item, i) => (
                      <div key={i} className="an-case-item" data-tip={item.tip}>
                        <AlertTriangle size={14} color="#C47A0A" style={{ marginTop: "2px", flexShrink: 0 }} strokeWidth={2.2} />
                        <span className="an-case-text">{item.text}</span>
                      </div>
                    )) : (
                      <div className="an-case-item"><span className="an-case-text" style={{ color: "#94A3B8" }}>No red flags identified.</span></div>
                    )}
                  </Panel>
                </div>

                <Panel className="vf-panel-neutral" accentColor="#1D6FE8">
                  <SLabel>AI Investment Verdict</SLabel>
                  <div className="an-verdict-headline">{report.recommendation}</div>
                  <p style={{ fontSize: "13.5px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 14px" }}>
                    {report.sections?.ai_analysis
                      ? report.sections.ai_analysis.slice(0, 400) + "…"
                      : report.ai_analysis?.slice(0, 400) + "…"}
                  </p>
                  <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginBottom: "16px" }}>
                    {[
                      { label: report.recommendation, color: scoreColor, bg: `${scoreColor}14`, border: `${scoreColor}30` },
                      { label: `${report.claims_supported} CLAIMS VERIFIED`, color: "#0EA66A", bg: "rgba(14,166,106,0.08)", border: "rgba(14,166,106,0.2)" },
                      { label: `${riskLabel.toUpperCase()} RISK`, color: riskColor, bg: `${riskColor}12`, border: `${riskColor}28` },
                    ].map((b, i) => (
                      <span key={i} className="verdict-tag" style={{ color: b.color, background: b.bg, border: `1px solid ${b.border}` }}>
                        {b.label}
                      </span>
                    ))}
                  </div>

                  <div className="dd-accordion">
                    <button className="dd-accordion-trigger" onClick={() => setDdOpen(o => !o)}>
                      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 13 }}>📋</span>
                        Suggested Due Diligence Questions
                        <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: "#1D6FE8", background: "rgba(29,111,232,0.08)", border: "1px solid rgba(29,111,232,0.2)", padding: "2px 7px", borderRadius: 20 }}>
                          {ddQuestions.length} questions
                        </span>
                      </span>
                      {ddOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                    <AnimatePresence>
                      {ddOpen && (
                        <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }}
                          exit={{ height: 0, opacity: 0 }} transition={{ duration: 0.25 }}
                          style={{ overflow: "hidden" }}>
                          <div className="dd-accordion-body">
                            {ddQuestions.map((q, i) => (
                              <div key={i} className="dd-question">
                                <span className="dd-q-num">Q{i + 1}</span>
                                <span className="dd-q-text">{q}</span>
                              </div>
                            ))}
                          </div>
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </Panel>
              </div>
            )}

            {/* ── MARKET VALIDATION ── */}
            {activeTab === "Market Validation" && (
              <div className="tab-content-enter">
                <Panel className="vf-panel-neutral" accentColor="var(--border)">
                  <SLabel>Market Validation — Evidence-Grounded</SLabel>
                  <p style={{ fontSize: "13.5px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 14px" }}>
                    {market?.market_definition || "No market assessment was returned for this report."}
                  </p>
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
                    <span className="verdict-tag" style={{ color: "#0EA66A", background: "rgba(14,166,106,0.08)", border: "1px solid rgba(14,166,106,0.2)" }}>
                      {Math.round((market?.confidence ?? 0) * 100)}% EVIDENCE CONFIDENCE
                    </span>
                  </div>
                  {(market?.signals ?? []).length > 0 ? market!.signals.map((signal, i) => (
                    <div key={i} className="an-case-item" data-tip={signal.evidence}>
                      <CheckCircle size={14} color="#0EA66A" style={{ marginTop: 2, flexShrink: 0 }} />
                      <span className="an-case-text">{signal.finding}</span>
                    </div>
                  )) : <div className="an-case-text" style={{ color: "#94A3B8" }}>Insufficient market evidence in the submitted deck.</div>}
                </Panel>

                <div style={{ display: "grid", gridTemplateColumns: "1fr 220px", gap: "12px" }}>
                  <Panel className="vf-panel-neutral" accentColor="var(--border)">
                    <SLabel>Claim Verification Table</SLabel>
                    {claimsTableData.length > 0 ? (
                      <table className="claims-table">
                        <thead>
                          <tr>
                            {["Claim", "Founder Said", "AI Estimate", "Status"].map(h => (
                              <th key={h} className="claims-th">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {claimsTableData.map((row, i) => {
                            const matchConfig: Record<string, { color: string; bg: string; border: string; label: string }> = {
                              verified: { color: "#0EA66A", bg: "rgba(14,166,106,0.08)", border: "rgba(14,166,106,0.2)", label: "Verified" },
                              close: { color: "#1D6FE8", bg: "rgba(29,111,232,0.08)", border: "rgba(29,111,232,0.2)", label: "Close" },
                              flagged: { color: "#D93025", bg: "rgba(217,48,37,0.07)", border: "rgba(217,48,37,0.16)", label: "Flagged" },
                            };
                            const mc = matchConfig[row.match];
                            return (
                              <tr key={i} className="claims-tr">
                                <td className="claims-td" style={{ fontWeight: 600, color: "#0B1120" }}>{row.claim}</td>
                                <td className="claims-td">{row.founder}</td>
                                <td className="claims-td">{row.aiEstimate}</td>
                                <td className="claims-td">
                                  <span className="match-chip" style={{ color: mc.color, background: mc.bg, border: `1px solid ${mc.border}` }}>{mc.label}</span>
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    ) : (
                      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, color: "#94A3B8", padding: "16px 0" }}>
                        No claim verification data available.
                      </div>
                    )}
                  </Panel>

                  <Panel accentColor="#C47A0A">
                    <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "9px", color: "#C47A0A", letterSpacing: "0.12em", marginBottom: "12px", fontWeight: "600", textTransform: "uppercase" }}>⚡ AI Signal</div>
                    <p style={{ fontSize: "13px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 14px" }}>
                      {market?.recommendation || "Validate market size, buyer demand, and competition with primary evidence."}
                    </p>
                    <div style={{ padding: "12px", background: "rgba(196,122,10,0.06)", borderRadius: "8px", border: "1px solid rgba(196,122,10,0.15)" }}>
                      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "9px", color: "#C47A0A", marginBottom: "4px" }}>EVIDENCE GAPS</div>
                      <div style={{ fontSize: "12.5px", color: "#0B1120", fontWeight: "600" }}>{market?.gaps?.[0] || "None identified."}</div>
                    </div>
                  </Panel>
                </div>
              </div>
            )}

            {/* ── FOUNDER ANALYSIS ── */}
            {activeTab === "Founder Analysis" && (
              <div className="tab-content-enter">
                <div style={{ display: "grid", gridTemplateColumns: "1fr 250px", gap: "12px" }}>
                  <Panel className="vf-panel-neutral" accentColor="var(--border)">
                    <SLabel>Team Capability Radar</SLabel>
                    {teamRadarData.length > 0 ? <ResponsiveContainer width="100%" height={280}>
                      <RadarChart data={teamRadarData}>
                        <PolarGrid stroke="rgba(15,23,42,0.07)" />
                        <PolarAngleAxis dataKey="subject" tick={{ fill: "#64748B", fontFamily: "'IBM Plex Mono', monospace", fontSize: 10 }} />
                        <PolarRadiusAxis tick={false} axisLine={false} domain={[0, 100]} />
                        <Radar dataKey="value" stroke="#1D6FE8" fill="#1D6FE8" fillOpacity={0.09} strokeWidth={2.5} dot={{ fill: "#1D6FE8", r: 4, strokeWidth: 0 } as any} />
                      </RadarChart>
                    </ResponsiveContainer> : <p style={{ color: "#94A3B8", fontSize: 13, lineHeight: 1.7 }}>
                      {/* Do not assert *why* the scores are missing. The team analyst
                          returns the same empty `capabilities` list whether the deck
                          genuinely had no team slide or the agent call failed, and
                          claiming the former when the latter happened is the kind of
                          confidently-wrong empty state this tab already had once. */}
                      The team analyst produced no capability scores for this deck.
                      {founderChecks.length > 0
                        ? " Founder names were found and checked against public web evidence — see below."
                        : " No founder names were submitted; add them on the upload form to run a public-background check."}
                      {report.incomplete_analysis
                        ? " This analysis is flagged incomplete, so the agent may not have run at all."
                        : ""}
                    </p>}
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                      {teamRadarData.map((r, i) => (
                        <div key={i} style={{ display: "flex", alignItems: "center", gap: 5, padding: "3px 8px", background: "var(--surface-2)", borderRadius: 6, border: "1px solid var(--border)" }}>
                          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: "#94A3B8" }}>{r.subject}</span>
                          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, fontWeight: 600, color: r.value >= 70 ? "#0EA66A" : "#C47A0A" }}>{r.value}</span>
                        </div>
                      ))}
                    </div>
                  </Panel>

                  <Panel accentColor="#D93025">
                    <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "9px", color: "#D93025", letterSpacing: "0.12em", marginBottom: "12px", fontWeight: "600", textTransform: "uppercase" }}>⚠ Gap Identified</div>
                    <p style={{ fontSize: "13px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 16px" }}>
                      {team?.gaps?.[0] || "Insufficient team evidence. Verify founder credentials independently."}
                    </p>
                    <div style={{ borderTop: "1px solid var(--border)", paddingTop: "14px", marginBottom: 14 }}>
                      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "9px", color: "#94A3B8", letterSpacing: "0.12em", marginBottom: "8px", textTransform: "uppercase" }}>Recommendation</div>
                      <div style={{ fontSize: "13.5px", color: "#0B1120", fontWeight: "700", letterSpacing: "-0.01em" }}>
                        {team?.questions?.[0] || (report.recommendation === "INVEST" ? "Proceed with reference checks" : "Verify team credentials before proceeding")}
                      </div>
                    </div>
                  </Panel>
                </div>

                {/* Founder background checks — the output of the agent that
                    could never run before the upload form had a founders
                    field. */}
                <Panel className="vf-panel-neutral" accentColor="var(--border)" style={{ marginTop: 12 }}>
                  <SLabel>Founder Background Checks</SLabel>
                  {founderChecks.length ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      {founderChecks.map((check, i) => {
                        const tone = check.assessment === "CONSISTENT" ? "#0EA66A"
                          : check.assessment === "CONTRADICTS" ? "#D93025" : "#C47A0A";
                        return (
                          <div key={i} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "12px 14px", background: "var(--surface-2)" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
                              <span className="an-founder-name">{check.name}</span>
                              <span style={{
                                fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, fontWeight: 600,
                                letterSpacing: "0.08em", color: tone, border: `1px solid ${tone}33`,
                                background: `${tone}12`, borderRadius: 5, padding: "2px 7px",
                              }}>{check.assessment}</span>
                              <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 10, color: "#94A3B8" }}>
                                confidence {Math.round((check.confidence ?? 0) * 100)}%
                              </span>
                            </div>
                            <p className="an-founder-desc">{check.evidence_summary}</p>
                            {(check.sources ?? []).length > 0 && (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                {(check.sources ?? []).slice(0, 4).map((url, j) => (
                                  <a key={j} href={url} target="_blank" rel="noreferrer" style={{
                                    fontFamily: "'IBM Plex Mono', monospace", fontSize: 9.5,
                                    color: "#1D6FE8", textDecoration: "none",
                                    border: "1px solid rgba(29,111,232,0.2)", borderRadius: 5, padding: "2px 6px",
                                  }}>{(() => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return "source"; } })()}</a>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <p style={{ color: "#94A3B8", fontSize: 13, lineHeight: 1.7, margin: "10px 0 0" }}>
                      No founder names were submitted with this analysis, so no background check ran.
                      Re-run from the upload page with founder names filled in — they are read from the
                      deck's team slide automatically when it has one.
                    </p>
                  )}
                </Panel>
              </div>
            )}

            {/* ── COMPETITOR INSIGHTS ── */}
            {activeTab === "Competitor Insights" && (
              <div className="tab-content-enter" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 256px", gap: "12px" }}>
                  <Panel className="vf-panel-neutral" accentColor="var(--border)">
                    <SLabel>Competitive Landscape</SLabel>
                    {/*
                      The population scope is stated ABOVE the table, not in an
                      11px footnote below it.

                      "Why these five companies" has an honest answer -- they are
                      the nearest matches inside one accelerator's portfolio --
                      and a reader who does not see that will read the table as
                      "these are this company's competitors", which it is not. A
                      startup with no YC analogue still gets five rows, because
                      the search always returns its closest available matches
                      however distant they are.

                      Broadening the population is a budget item, not an
                      engineering one: Crunchbase's API returns 401 without a
                      paid licence. Until that changes, a correctly-scoped
                      feature beats a silently-overclaimed one.
                    */}
                    {ycComparables.length > 0 && (
                      <div style={{
                        background: "rgba(234,179,8,0.08)",
                        border: "1px solid rgba(234,179,8,0.35)",
                        borderRadius: 6, padding: "8px 10px", margin: "8px 0 12px",
                      }}>
                        <p style={{ color: "#EAB308", fontSize: 12, fontWeight: 600, margin: 0 }}>
                          Y Combinator companies only
                        </p>
                        <p style={{ color: "#94A3B8", fontSize: 11, lineHeight: 1.6, margin: "4px 0 0" }}>
                          Matched against{" "}
                          {marketComparables?.population?.n?.toLocaleString?.() ?? "1,560"}{" "}
                          YC alumni with a recorded outcome — not against the market.
                          No non-YC startups are represented. These are the nearest
                          available matches, not necessarily close ones: treat them as
                          leads to investigate, not as validated comparables.
                        </p>
                        {/*
                          Measured, and stated because the number invites the
                          opposite reading: cosine similarity on this TF-IDF
                          embedder is LEXICAL. "A commercial laundry servicing
                          hotels" scores 0.83 against this corpus while "an AI
                          developer tools platform" scores 0.76. A high
                          percentage means shared wording, not that two
                          businesses are alike.
                        */}
                        <p style={{ color: "#94A3B8", fontSize: 11, lineHeight: 1.6, margin: "6px 0 0" }}>
                          The similarity percentage measures shared wording, not
                          business relevance — an unrelated company can score
                          higher than a relevant one. Read the names, not the number.
                        </p>
                      </div>
                    )}

                    {/*
                      The honest empty state. This tab used to return exactly
                      five rows for every query however distant, presenting "the
                      nearest things in a 1,560-company corpus" as though it
                      meant "these are comparable companies".
                    */}
                    {marketComparables?.no_close_matches && (
                      <div style={{
                        background: "rgba(148,163,184,0.08)",
                        border: "1px solid rgba(148,163,184,0.3)",
                        borderRadius: 6, padding: "12px 14px", margin: "8px 0 12px",
                      }}>
                        <p style={{ color: "#CBD5E1", fontSize: 13, fontWeight: 600, margin: 0 }}>
                          No close comparables found
                        </p>
                        <p style={{ color: "#94A3B8", fontSize: 12, lineHeight: 1.6, margin: "6px 0 0" }}>
                          The nearest company in the Y Combinator corpus scored{" "}
                          {typeof marketComparables.best_similarity === "number"
                            ? `${Math.round(marketComparables.best_similarity * 100)}%`
                            : "below"}{" "}
                          similarity, under the{" "}
                          {typeof marketComparables.threshold === "number"
                            ? `${Math.round(marketComparables.threshold * 100)}%`
                            : ""}{" "}
                          floor. Nothing is shown rather than presenting distant
                          matches as comparable. This is the expected result for a
                          company with no YC analogue.
                        </p>
                      </div>
                    )}
                    {competitors.length ? <>
                      <table className="an-comp-table">
                        <thead>
                          <tr>
                            {["Company", "Batch / Domain", "Sector", "Outcome", "Similarity"].map((h) => (
                              <th key={h} className="an-comp-th">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {competitors.map((competitor, i) => (
                            <tr key={i} className="an-comp-tr">
                              <td className="an-comp-td" style={{ fontWeight: 600 }}>{competitor.name}</td>
                              <td className="an-comp-td">{competitor.domain || "—"}</td>
                              <td className="an-comp-td">{competitor.sector || "—"}</td>
                              <td className="an-comp-td" style={{ color: competitor.outcome === "Shut down" ? "#D93025" : competitor.outcome ? "#0EA66A" : "#94A3B8" }}>{competitor.outcome || "—"}</td>
                              <td className="an-comp-td">{typeof competitor.similarity === "number" ? `${Math.round(competitor.similarity * 100)}%` : "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <p style={{ color: "#94A3B8", fontSize: 11, lineHeight: 1.6, marginTop: 12 }}>
                        Source: {comparablesSource}
                        {marketComparables?.caveat && ycComparables.length ? ` — ${marketComparables.caveat}` : ""}
                      </p>
                      {ycComparables.length > 0 && portfolioMatches.length > 0 && (
                        <p style={{ color: "#64748B", fontSize: 12, marginTop: 8 }}>
                          Also matched in your own history: {portfolioMatches.map(m => m.name).join(", ")}.
                        </p>
                      )}
                    </> : <p style={{ color: "#64748B", fontSize: 13, margin: "16px 0" }}>
                      {marketComparables && !marketComparables.available
                        ? `Comparable-company search was unavailable: ${marketComparables.reason ?? "no reason recorded"}.`
                        : "No comparable companies were found for this analysis."}
                    </p>}
                  </Panel>

                  <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                    {competitors.length > 0 && <Panel className="vf-panel-neutral" accentColor="var(--border)">
                      <SLabel>Threat Distribution</SLabel>
                      <div style={{ display: "flex", justifyContent: "center", marginBottom: "8px", position: "relative" }}>
                        <PieChart width={160} height={160}>
                          <Pie data={threatData} dataKey="value" innerRadius={50} outerRadius={74} strokeWidth={3} stroke="#F0F2F5" paddingAngle={2}>
                            {threatData.map((entry, i) => <Cell key={i} fill={entry.color} fillOpacity={0.85} />)}
                          </Pie>
                        </PieChart>
                        <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)", textAlign: "center" }}>
                          <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 18, color: "#0B1120", lineHeight: 1 }}>{competitors.length}</div>
                          <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 8, color: "#94A3B8" }}>competitors</div>
                        </div>
                      </div>
                      {threatData.map((d, i) => (
                        <div key={i} className="an-threat-row">
                          <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                            <div style={{ width: "8px", height: "8px", borderRadius: "3px", background: d.color }} />
                            <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", color: "#64748B" }}>{d.name} Threat</span>
                          </div>
                          <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "11px", color: d.color, fontWeight: "600" }}>{d.value}%</span>
                        </div>
                      ))}
                    </Panel>}

                    <Panel accentColor="#C47A0A">
                      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "9px", color: "#C47A0A", letterSpacing: "0.12em", marginBottom: "10px", fontWeight: "600", textTransform: "uppercase" }}>⚡ Recommendation</div>
                      <p style={{ fontSize: "13px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 10px" }}>
                        {score >= 65 ? "Competitive position appears defensible. Validate specific differentiation claims." : "High competitive pressure detected. Requires clear differentiation strategy."}
                      </p>
                    </Panel>
                  </div>
                </div>

              </div>
            )}
          </div>

          {/* CHAT PANEL - always visible on analysis page */}
          <div style={{ borderLeft: "1px solid rgba(15,23,42,0.08)", padding: "16px", background: "#F7F8FA" }}>
            <ChatPanel sessionId={sessionId} />
            <CommentsPanel reportId={report.report_id ?? null} />
          </div>
        </div>
      </div>
    </>
  );
};

export default Analysis;
