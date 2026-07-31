import { useState } from "react";
import {
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  AreaChart, Area, RadarChart, PolarGrid, PolarAngleAxis,
  PolarRadiusAxis, Radar, PieChart, Pie, Cell, BarChart, Bar,
} from "recharts";
import { CheckCircle, AlertTriangle, ChevronDown, ChevronUp, Download, ExternalLink, Upload, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { useApp } from "../context/AppContext";
import { useNavigate } from "react-router-dom";

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

const threatData = [
  { name: "High",   value: 40, color: "#D93025" },
  { name: "Medium", value: 35, color: "#C47A0A" },
  { name: "Low",    value: 25, color: "#0EA66A" },
];

const fundingTimelineData = [
  { name: "Viz.ai",   value: 100, stage: "Series D", color: "#D93025" },
  { name: "Aidoc",    value: 110, stage: "Series C", color: "#D93025" },
  { name: "Caption",  value: 53,  stage: "Series B", color: "#C47A0A" },
  { name: "Lunit",    value: 98,  stage: "Series D", color: "#C47A0A" },
  { name: "Company",  value: 12,  stage: "Series A (ask)", color: "#1D6FE8" },
];

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
        headers: { "Content-Type": "application/json" },
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
  const [activeTab, setActiveTab] = useState("Summary");
  const [ddOpen, setDdOpen] = useState(false);
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

  // Claims table from real claim details
  const claimsTableData = claimsDetails.slice(0, 5).map(c => ({
    claim: c.claim.slice(0, 30) + (c.claim.length > 30 ? "…" : ""),
    founder: "As stated",
    aiEstimate: c.verdict === "SUPPORTS" ? "Confirmed" : c.verdict === "REFUTES" ? "Disputed" : "Unverified",
    match: c.verdict === "SUPPORTS" ? "verified" : c.verdict === "REFUTES" ? "flagged" : "close",
    delta: `${Math.round(c.confidence * 100)}%`,
  }));

  // Update company name in funding chart
  const fundingData = fundingTimelineData.map(d =>
    d.name === "Company" ? { ...d, name: report.company.slice(0, 7) } : d
  );

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
              <div className="an-confidence-chip">
                ✓ {Math.round(score)}% data confidence
              </div>
              <button className="an-export-btn" type="button" onClick={exportReport} aria-label="Export due diligence report as text">
                <Download size={12} strokeWidth={2} />
                Export
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

            {/* ── SUMMARY ── */}
            {activeTab === "Summary" && (
              <div className="tab-content-enter">
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "12px" }}>
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
                    </ResponsiveContainer> : <p style={{ color: "#94A3B8", fontSize: 13 }}>Insufficient team evidence in this deck.</p>}
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
              </div>
            )}

            {/* ── COMPETITOR INSIGHTS ── */}
            {activeTab === "Competitor Insights" && (
              <div className="tab-content-enter" style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 256px", gap: "12px" }}>
                  <Panel className="vf-panel-neutral" accentColor="var(--border)">
                    <SLabel>Competitive Landscape</SLabel>
                    <table className="an-comp-table">
                      <thead>
                        <tr>
                          {["Company", "Funding", "Stage", "Focus", "Last Round", "Threat"].map((h) => (
                            <th key={h} className="an-comp-th">{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {[
                          ["Viz.ai", "$100M", "Series D", "Stroke AI", "Mar 2023", "High", "#D93025"],
                          ["Aidoc", "$110M", "Series C", "Radiology AI", "Jan 2023", "High", "#D93025"],
                          ["Caption Health", "$53M", "Series B", "Echo AI", "Aug 2022", "Medium", "#C47A0A"],
                          ["Lunit", "$98M", "Series D", "Cancer Detection", "Nov 2022", "Medium", "#C47A0A"],
                          ["Enlitai", "$18M", "Series A", "Neuroimaging", "Feb 2024", "Low", "#0EA66A"],
                        ].map((row, i) => (
                          <tr key={i} className="an-comp-tr">
                            {row.slice(0, 6).map((cell, j) => (
                              <td key={j} className="an-comp-td" style={{
                                color: j === 0 ? "#0B1120" : j === 5 ? (row[6] as string) : "#64748B",
                                fontWeight: j === 0 ? "600" : "400",
                              }}>
                                {j === 5 ? (
                                  <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "10px", padding: "3px 9px", borderRadius: "20px", background: `${row[6]}12`, border: `1px solid ${row[6]}30`, fontWeight: "600", color: row[6] as string }}>
                                    {cell}
                                  </span>
                                ) : (
                                  <span style={{ fontFamily: j === 0 ? "'Figtree', sans-serif" : "'IBM Plex Mono', monospace", fontSize: j === 0 ? "13px" : "11px" }}>
                                    {cell}
                                  </span>
                                )}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </Panel>

                  <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
                    <Panel className="vf-panel-neutral" accentColor="var(--border)">
                      <SLabel>Threat Distribution</SLabel>
                      <div style={{ display: "flex", justifyContent: "center", marginBottom: "8px", position: "relative" }}>
                        <PieChart width={160} height={160}>
                          <Pie data={threatData} dataKey="value" innerRadius={50} outerRadius={74} strokeWidth={3} stroke="#F0F2F5" paddingAngle={2}>
                            {threatData.map((entry, i) => <Cell key={i} fill={entry.color} fillOpacity={0.85} />)}
                          </Pie>
                        </PieChart>
                        <div style={{ position: "absolute", top: "50%", left: "50%", transform: "translate(-50%, -50%)", textAlign: "center" }}>
                          <div style={{ fontFamily: "'DM Serif Display', serif", fontSize: 18, color: "#0B1120", lineHeight: 1 }}>5</div>
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
                    </Panel>

                    <Panel accentColor="#C47A0A">
                      <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "9px", color: "#C47A0A", letterSpacing: "0.12em", marginBottom: "10px", fontWeight: "600", textTransform: "uppercase" }}>⚡ Recommendation</div>
                      <p style={{ fontSize: "13px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 10px" }}>
                        {score >= 65 ? "Competitive position appears defensible. Validate specific differentiation claims." : "High competitive pressure detected. Requires clear differentiation strategy."}
                      </p>
                    </Panel>
                  </div>
                </div>

                <Panel className="vf-panel-neutral" accentColor="var(--border)">
                  <SLabel>Competitor Funding Comparison (Total Raised, $M)</SLabel>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={fundingData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }} layout="vertical">
                      <CartesianGrid stroke="rgba(15,23,42,0.05)" horizontal={false} />
                      <XAxis type="number" tick={{ fill: "#94A3B8", fontFamily: "'IBM Plex Mono', monospace", fontSize: 10 }} axisLine={false} tickLine={false} tickFormatter={(v) => `$${v}M`} />
                      <YAxis type="category" dataKey="name" tick={{ fill: "#64748B", fontFamily: "'IBM Plex Mono', monospace", fontSize: 10 }} axisLine={false} tickLine={false} width={80} />
                      <Tooltip formatter={(v: any) => [`$${v}M`, "Total Raised"]} contentStyle={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, borderRadius: 10, border: "1px solid rgba(15,23,42,0.09)" }} />
                      <Bar dataKey="value" radius={[0, 5, 5, 0]}>
                        {fundingData.map((entry, i) => (
                          <Cell key={i} fill={entry.color} fillOpacity={entry.color === "#1D6FE8" ? 1 : 0.55} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </Panel>
              </div>
            )}
          </div>

          {/* CHAT PANEL - always visible on analysis page */}
          <div style={{ borderLeft: "1px solid rgba(15,23,42,0.08)", padding: "16px", background: "#F7F8FA" }}>
            <ChatPanel sessionId={sessionId} />
          </div>
        </div>
      </div>
    </>
  );
};

export default Analysis;
