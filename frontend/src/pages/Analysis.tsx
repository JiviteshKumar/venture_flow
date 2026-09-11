import { useState, useEffect } from "react";
import {
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  AreaChart, Area, RadarChart, PolarGrid, PolarAngleAxis,
  PolarRadiusAxis, Radar, PieChart, Pie, Cell, BarChart, Bar,
} from "recharts";
import { CheckCircle, AlertTriangle, ChevronDown, ChevronUp, Download, ExternalLink, Upload, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { authHeaders, handleSignedOut } from "../services/apiClient";
import { useApp } from "../context/AppContext";
import { useNavigate } from "react-router-dom";
import VentureScorePanel from "../components/analysis/VentureScorePanel";
import VerdictHero from "../components/analysis/VerdictHero";
import { formatDate, formatDateTime, displayDeckId } from "../utils/format";
import { Panel, SLabel, ScoreBadge } from "../components/ui/Panel";
import { Reveal } from "../components/ui/Motion";
import { MemoText, memoPreview } from "../components/ui/MemoText";

const tabs = ["Summary", "Market Validation", "Founder Analysis", "Competitor Insights"];

type ChatMessage = {
  role: "bot" | "user";
  text: string;
};

// No static chart data lives in this file.
//
// It used to hold three arrays of invented numbers: a TAM/SAM/SOM growth
// curve, a six-axis founder skill radar, and a competitor threat split.
// The first two were never read by any component -- dead code that still
// stated figures no backend ever produced -- and the third was an empty
// array feeding a live donut, so the chart rendered a blank ring with a
// count in the middle and no legend.
//
// The founder radar now reads `sections.team.capabilities`, and the
// competitor table reads `sections.market_comparables` (real YC
// similarity data). Market sizing and competitor threat level have no
// backend source, so those charts are gone rather than invented: a
// missing section is honest, a fabricated one is not.
// Panel, SLabel and ScoreBadge moved to components/ui/Panel.tsx so the
// other screens can use the same surfaces instead of copying them.

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
      if (await handleSignedOut(res)) return;
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
        fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 600,
        color: "#0B1120", letterSpacing: "0.06em", textTransform: "uppercase",
      }}>
        Document Chat
        {!sessionId && <span style={{ color: "#5D6B7F", fontWeight: 400, marginLeft: 8, fontSize: 9 }}>(run analysis first)</span>}
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
              lineHeight: 1.55, fontFamily: "var(--font-sans)",
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
              fontFamily: "var(--font-mono)", color: "#64748B",
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
            fontFamily: "var(--font-sans)", color: "#0B1120", outline: "none",
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
      .then(async (res) => ((await handleSignedOut(res)) || !res.ok ? [] : res.json()))
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
      if (await handleSignedOut(res)) return;
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
        fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 600,
        color: "#0B1120", letterSpacing: "0.06em", textTransform: "uppercase",
      }}>
        Notes {!reportId && <span style={{ color: "#5D6B7F", fontWeight: 400, marginLeft: 8, fontSize: 9 }}>(run analysis first)</span>}
      </div>
      <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 8, maxHeight: 220, overflowY: "auto" }}>
        {comments.length === 0 && <div style={{ fontSize: 12, color: "#5D6B7F", fontFamily: "var(--font-sans)" }}>No notes yet.</div>}
        {comments.map((c) => (
          <div key={c.id} style={{ fontSize: 12.5, fontFamily: "var(--font-sans)", color: "#374151" }}>
            <span style={{ fontWeight: 600, color: "#0B1120" }}>{c.author_name}</span>
            <span style={{ color: "#5D6B7F", fontSize: 10.5, marginLeft: 6 }}>{formatDateTime(c.created_at)}</span>
            <div style={{ marginTop: 2 }}>{c.body}</div>
          </div>
        ))}
      </div>
      <form onSubmit={submit} style={{ padding: "10px 14px", borderTop: "1px solid rgba(15,23,42,0.08)", display: "flex", flexDirection: "column", gap: 6 }}>
        <input
          value={authorName} onChange={(e) => setAuthorName(e.target.value)}
          placeholder="Your name (optional)" disabled={!reportId}
          style={{ background: "#F7F8FA", border: "1px solid rgba(15,23,42,0.1)", borderRadius: 8, padding: "6px 10px", fontSize: 12, fontFamily: "var(--font-sans)", outline: "none" }}
        />
        <div style={{ display: "flex", gap: 8 }}>
          <input
            value={body} onChange={(e) => setBody(e.target.value)}
            placeholder={reportId ? "Add a note for the deal team…" : "Run analysis first"}
            disabled={!reportId || posting}
            style={{ flex: 1, background: "#F7F8FA", border: "1px solid rgba(15,23,42,0.1)", borderRadius: 8, padding: "8px 12px", fontSize: 12.5, fontFamily: "var(--font-sans)", outline: "none" }}
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
      padding: "40px 24px", fontFamily: "var(--font-sans)",
    }}>
      {isAnalyzing ? (
        <>
          <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1.2, ease: "linear" }} style={{ marginBottom: 24 }}>
            <Zap size={36} color="#1D6FE8" />
          </motion.div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 22, marginBottom: 8, color: "#0B1120" }}>
            Agents are running…
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#5D6B7F", marginBottom: 16 }}>
            {currentStage}
          </div>
          <div style={{ width: 240, height: 4, background: "rgba(15,23,42,0.07)", borderRadius: 4, overflow: "hidden" }}>
            <motion.div style={{ height: "100%", background: "#1D6FE8", borderRadius: 4 }}
              animate={{ width: `${progressPct}%` }} transition={{ duration: 0.5 }} />
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "#5D6B7F", marginTop: 8 }}>
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
          <div style={{ fontFamily: "var(--font-display)", fontSize: 22, marginBottom: 8, color: "#0B1120" }}>
            No analysis yet
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#5D6B7F", marginBottom: 24, maxWidth: 300 }}>
            Upload and analyse a pitch deck to see the full report here.
          </div>
          <button onClick={() => navigate("/upload")} style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            background: "#1D6FE8", color: "#fff", border: "none",
            borderRadius: 10, padding: "11px 22px", fontFamily: "var(--font-sans)",
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
  const [memoExpanded, setMemoExpanded] = useState(false);

  const [pdfExporting, setPdfExporting] = useState(false);
  const { report, sessionId } = useApp();
  const navigate = useNavigate();

  // If no report, show empty/loading
  if (!report) {
    return (
      <div className="an-root" style={{ fontFamily: "var(--font-sans)", color: "#0B1120", minHeight: "100vh", background: "#F0F2F5" }}>
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

  const today = formatDate(new Date());
  const deckId = displayDeckId(report.company);

  // Real claims from backend
  const claimsDetails = report.sections?.claims?.details ?? [];
  const market = report.sections?.market;
  const team = report.sections?.team;
  const bullCase = report.sections?.bull_case;
  // Which specialists never ran. "No positive signals identified" is a finding;
  // "the agent did not run" is not, and the two must not share a sentence.
  const degradedComponents = report.degraded_components ?? [];
  const specialistDegraded = (role: string) =>
    degradedComponents.some((d) => (d.component || "").toLowerCase().includes(role));
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
  // Present whenever the deck disclosed no team, whether or not the search then
  // succeeded. Drives the Founder Analysis empty state, which used to be a dead
  // end rather than a result.
  const founderDiscovery = report.sections?.founder_discovery;
  // Coverage lives at the top level and (for older stored reports) may be
  // absent entirely -- reports written before this existed must still render.
  const coverage = report.extraction_coverage ?? report.sections?.extraction_coverage;
  const coverageTone =
    coverage?.verdict === "HIGH" ? "#0EA66A"
      : coverage?.verdict === "PARTIAL" ? "#C47A0A"
        : "#D93025";
  const extractionProvenance =
    report.extraction_provenance ?? report.sections?.extraction_provenance;

  // The memo lives under `sections` on a freshly-run report and at the top
  // level on one reloaded from the database, so both are checked.
  const memoFull = report.sections?.ai_analysis || report.ai_analysis || "";
  const memoSummary = memoPreview(memoFull);

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
   * `sections.market_comparables` is comparables.py's cosine-similarity search,
   * which returns matches for any non-empty description. So those are the
   * primary source here and the portfolio overlap is kept as a
   * clearly-labelled secondary signal, since "have I looked at something like
   * this before" is a different and also useful question.
   *
   * The corpus is no longer Y Combinator alone. It now also covers technology
   * companies from public reference data that never went through an
   * accelerator, and results are stratified so a non-YC company is shown
   * whenever one clears the similarity floor. Every row therefore carries its
   * population, and the table shows it: a YC alum and an encyclopedia-notable
   * public company are different kinds of evidence and presenting them as one
   * undifferentiated list of peers would misrepresent both.
   */
  const marketComparables = report.sections?.market_comparables;
  const corpusComparables = (marketComparables?.available && marketComparables.comparables) || [];
  const portfolioMatches = report.similar_companies ?? [];
  const competitors = corpusComparables.length
    ? corpusComparables.map(c => ({
        name: c.name,
        domain: c.batch || (c.founded_year ? `founded ${c.founded_year}` : null),
        sector: c.industry || null,
        similarity: c.similarity,
        outcome: c.outcome ?? null,
        population: c.population_label || null,
        sourceUrl: c.source_url || null,
      }))
    : portfolioMatches.map(c => ({
        name: c.name,
        domain: c.domain ?? null,
        sector: c.sector ?? null,
        similarity: c.similarity,
        outcome: null as string | null,
        population: "Your own prior reports" as string | null,
        sourceUrl: null as string | null,
      }));

  /**
   * Whether this report was produced after the comparables corpus was widened
   * beyond Y Combinator.
   *
   * Reports are stored as they were computed, so a report from before the
   * change carries YC-only rows AND a stored caveat that says so. Rendering
   * today's "two populations" banner above that report's own "YC-ONLY
   * POPULATION" caveat puts two contradictory statements two inches apart, and
   * the older one is the true one for that report.
   *
   * So the banner follows the data. A row from the wider corpus carries its
   * population; a row from the old one does not.
   */
  const isTwoPopulationReport = corpusComparables.some(c => Boolean(c.population));
  const populations = marketComparables?.population ?? {};
  const populationSummary = Object.values(populations)
    .filter(p => typeof p?.n === "number" && p.n > 0)
    .map(p => `${p.n!.toLocaleString()} ${p.label ?? ""}`.trim())
    .join(" + ");
  const comparablesSource = corpusComparables.length
    ? (populationSummary || "Companies with a publicly recorded outcome")
    : portfolioMatches.length
      ? "Your own prior reports and portfolio (name/domain similarity)"
      : "";

  // Pulled out so the hero and the score panel below it read the same
  // fields, and cannot disagree about this report's own numbers.
  const vs = report.sections?.venture_score;
  const vsRange = vs?.score_range;

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
      if (await handleSignedOut(res)) return;
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

        :root {
          --bg: #F0F2F5;
          --surface: #FFFFFF;
          --surface-2: #F7F8FA;
          --border: rgba(15,23,42,0.08);
          --border-strong: rgba(15,23,42,0.13);
          --text-primary: #0B1120;
          --text-secondary: #4A5568;
          --text-muted: #5D6B7F;
          --blue: #1D6FE8;
          --green: #0EA66A;
          --amber: #C47A0A;
          --red: #D93025;
          --shadow-sm: 0 1px 4px rgba(15,23,42,0.06), 0 2px 12px rgba(15,23,42,0.04);
          --shadow-md: 0 4px 20px rgba(15,23,42,0.08), 0 1px 4px rgba(15,23,42,0.05);
          --radius: 14px;
        }

        .an-root { font-family: var(--font-sans); color: var(--text-primary); min-height: 100vh; background: var(--bg); }

        /* ── VentureFlow Score panel ─────────────────────────────────── */
        .vs-card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 20px 22px; margin-bottom: 18px; }
        .vs-card-muted { background: var(--surface-2); }
        .vs-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
        .vs-eyebrow { font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.09em; text-transform: uppercase; color: var(--text-secondary); margin: 0; font-weight: 600; }
        .vs-sub { font-size: 11.5px; color: var(--text-secondary); margin: 4px 0 0; }
        .vs-conf { font-family: var(--font-mono); font-size: 9.5px; font-weight: 600; padding: 5px 11px; border-radius: 20px; border: 1px solid; white-space: nowrap; }
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
        .vs-track-labels { display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 9px; color: var(--text-secondary); margin-top: 6px; }
        .vs-breakdown { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin-bottom: 14px; }
        .vs-bd-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 9px 13px; font-size: 12.5px; border-bottom: 1px solid var(--border); }
        .vs-bd-row:last-child { border-bottom: none; }
        .vs-bd-row span { color: var(--text-secondary); }
        .vs-bd-row strong { font-variant-numeric: tabular-nums; font-size: 13px; }
        .vs-bd-total { background: var(--surface-2); }
        .vs-bd-total span { color: var(--text-primary); font-weight: 600; }
        .vs-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .vs-stat { background: var(--surface-2); border: 1px solid var(--border); border-radius: 9px; padding: 9px 11px; display: flex; flex-direction: column; gap: 4px; }
        .vs-stat-k { font-family: var(--font-mono); font-size: 9px; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); }
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
        .vs-dl dt { font-family: var(--font-mono); font-size: 9.5px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-secondary); padding-top: 2px; }
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

        .an-eyebrow { font-family: var(--font-mono); font-size: 9.5px; color: var(--text-muted); letter-spacing: 0.12em; text-transform: uppercase; }

        .an-id-badge { font-family: var(--font-mono); font-size: 9.5px; color: var(--blue); letter-spacing: 0.06em; padding: 3px 10px; background: rgba(29,111,232,0.08); border: 1px solid rgba(29,111,232,0.2); border-radius: 20px; font-weight: 500; }

        .an-title { font-family: var(--font-display); font-size: 30px; font-weight: 400; letter-spacing: -0.01em; color: var(--text-primary); margin: 0 0 5px; line-height: 1; }

        .an-subtitle { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-muted); margin-bottom: 20px; }

        .an-header-actions { display: flex; align-items: center; gap: 8px; padding-top: 4px; }

        .an-export-btn { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: 12px; font-weight: 600; padding: 7px 14px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border-strong); color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease; }

        .an-export-btn:hover { background: var(--text-primary); color: #fff; border-color: var(--text-primary); }

        .an-confidence-chip { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-mono); font-size: 9.5px; color: var(--green); background: rgba(14,166,106,0.08); border: 1px solid rgba(14,166,106,0.22); padding: 6px 12px; border-radius: 20px; font-weight: 500; }

        .an-tabbar { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 32px; }
        .an-tabs { display: flex; gap: 2px; }

        .an-tab { position: relative; font-family: var(--font-sans); font-size: 13.5px; font-weight: 500; padding: 15px 20px; border: none; background: transparent; color: var(--text-muted); cursor: pointer; transition: color var(--dur-fast) var(--ease-out); white-space: nowrap; letter-spacing: -0.01em; }
        .an-tab-underline { position: absolute; left: 12px; right: 12px; bottom: -1px; height: 2.5px; border-radius: 3px 3px 0 0; background: var(--blue); }

        .an-tab:hover { color: var(--text-secondary); }
        .an-tab-active { color: var(--blue); font-weight: 600; }

        .an-body { padding: 28px 32px 48px; display: flex; flex-direction: column; gap: 20px; }

        .vf-panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 22px; box-shadow: var(--shadow-sm); border-left-width: 3px; transition: box-shadow var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out), border-color var(--dur-base) var(--ease-out); }

        .vf-panel:hover { box-shadow: var(--shadow-raised); transform: translateY(-2px); border-color: var(--border-strong); }
        .vf-panel-neutral { border-left-color: var(--border) !important; }

        .vf-slabel { font-family: var(--font-mono); font-size: 9.5px; color: var(--text-muted); letter-spacing: 0.12em; text-transform: uppercase; font-weight: 500; margin-bottom: 14px; }

        .an-case-item { display: flex; gap: 11px; align-items: flex-start; margin-bottom: 8px; padding: 11px 13px; border-radius: 9px; background: var(--surface-2); border: 1px solid var(--border); transition: border-color 0.15s ease, background 0.15s ease; cursor: default; }

        .an-case-item:hover { border-color: var(--border-strong); background: #F3F5F8; }

        .an-case-text { font-size: 13px; color: var(--text-secondary); line-height: 1.6; flex: 1; }

        .score-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow-sm); transition: transform 0.2s ease, box-shadow 0.2s ease; cursor: default; }

        .score-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }

        .an-verdict-headline { font-family: var(--font-display); font-size: 20px; color: var(--text-primary); letter-spacing: -0.02em; margin-bottom: 8px; line-height: 1.2; }

        .verdict-tag { font-family: var(--font-mono); font-size: 9.5px; padding: 5px 12px; border-radius: 20px; letter-spacing: 0.07em; font-weight: 500; cursor: default; transition: transform 0.15s ease; }

        .verdict-tag:hover { transform: translateY(-1px); }

        .dd-accordion { margin-top: 16px; border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }

        .dd-accordion-trigger { width: 100%; display: flex; align-items: center; justify-content: space-between; padding: 12px 16px; background: var(--surface-2); border: none; cursor: pointer; font-family: var(--font-sans); font-size: 13px; font-weight: 600; color: var(--text-primary); transition: background 0.14s ease; letter-spacing: -0.01em; }

        .dd-accordion-trigger:hover { background: #EEEFF2; }

        .dd-accordion-body { padding: 14px 16px; background: var(--surface); }

        .dd-question { display: flex; gap: 10px; align-items: flex-start; padding: 9px 0; border-bottom: 1px solid rgba(15,23,42,0.05); }

        .dd-question:last-child { border-bottom: none; }

        .dd-q-num { font-family: var(--font-mono); font-size: 10px; color: var(--blue); font-weight: 600; flex-shrink: 0; min-width: 22px; }

        .dd-q-text { font-size: 12.5px; color: var(--text-secondary); line-height: 1.55; }

        .mkt-stat { padding: 14px; background: var(--surface-2); border-radius: 10px; border: 1px solid var(--border); transition: border-color 0.15s ease, transform 0.15s ease; cursor: default; }

        .mkt-stat:hover { border-color: var(--border-strong); transform: translateY(-1px); }

        .claims-table { width: 100%; border-collapse: collapse; }

        .claims-th { font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); letter-spacing: 0.12em; text-transform: uppercase; text-align: left; padding: 0 12px 10px 0; border-bottom: 1px solid var(--border); }

        .claims-tr { border-bottom: 1px solid rgba(15,23,42,0.05); transition: background 0.12s ease; }

        .claims-tr:hover { background: var(--surface-2); }
        .claims-tr:last-child { border-bottom: none; }

        .claims-td { font-size: 12.5px; padding: 9px 12px 9px 0; color: var(--text-secondary); }

        .match-chip { font-family: var(--font-mono); font-size: 9px; padding: 3px 8px; border-radius: 20px; font-weight: 600; }

        .an-founder-avatar { width: 40px; height: 40px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 12px; font-weight: 600; color: var(--text-secondary); flex-shrink: 0; transition: transform 0.2s ease; }

        .vf-panel:hover .an-founder-avatar { transform: scale(1.06); }

        .an-founder-name { font-size: 13.5px; font-weight: 600; color: var(--text-primary); letter-spacing: -0.01em; }
        .an-founder-role { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); margin-top: 2px; }
        .an-founder-desc { font-size: 12.5px; color: var(--text-secondary); line-height: 1.6; margin: 0 0 12px; }

        .an-risk-pill { font-family: var(--font-mono); font-size: 9.5px; padding: 4px 10px; border-radius: 20px; letter-spacing: 0.07em; font-weight: 500; }

        .an-comp-table { width: 100%; border-collapse: collapse; }

        .an-comp-th { font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); letter-spacing: 0.12em; text-transform: uppercase; text-align: left; padding: 0 12px 12px 0; border-bottom: 1px solid var(--border); font-weight: 500; }

        .an-comp-tr { border-bottom: 1px solid rgba(15,23,42,0.05); transition: background 0.12s ease; cursor: default; }

        .an-comp-tr:hover { background: var(--surface-2); }
        .an-comp-tr:last-child { border-bottom: none; }
        .an-comp-td { font-size: 12.5px; padding: 11px 12px 11px 0; }

        .an-threat-row { display: flex; justify-content: space-between; align-items: center; padding: 7px 9px; border-radius: 7px; margin-bottom: 3px; transition: background 0.14s ease; cursor: default; }

        .an-threat-row:hover { background: var(--surface-2); }

        .tab-content-enter { animation: tab-fade-in 0.28s ease forwards; }

        @keyframes tab-fade-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

        [data-tip] { position: relative; cursor: default; }
        [data-tip]:hover::after { content: attr(data-tip); position: absolute; bottom: calc(100% + 7px); left: 50%; transform: translateX(-50%); background: rgba(11,17,32,0.92); color: #F0F2F5; padding: 5px 10px; border-radius: 6px; font-family: var(--font-mono); font-size: 9.5px; white-space: nowrap; pointer-events: none; z-index: 200; }
        [data-tip]:hover::before { content: ''; position: absolute; bottom: calc(100% + 3px); left: 50%; transform: translateX(-50%); border: 4px solid transparent; border-top-color: rgba(11,17,32,0.92); z-index: 200; pointer-events: none; }
      `}</style>

      <div className="an-root">
        {/* THE VERDICT, FIRST.
            This was a pale header whose only statement of the result was a
            12px chip in the corner reading "48/100 overall score" -- the same
            size and weight as the Export button beside it. The answer a reader
            opens the report for now leads the page, at full size, with its
            interval and base rate attached so the number is never quoted
            alone. See VerdictHero for the reasoning. */}
        <VerdictHero
          company={report.company}
          deckId={deckId}
          analyzedOn={today}
          claimsChecked={report.claims_verified}
          score={Math.round(score)}
          recommendation={report.recommendation}
          riskLevel={report.risk_level}
          low={vsRange?.[0]}
          high={vsRange?.[1]}
          baseRate={
            typeof vs?.base_rate === "number"
              ? Math.round(vs.base_rate * (vs.base_rate <= 1 ? 100 : 1))
              : undefined
          }
          modelAvailable={Boolean(vs?.available && typeof vs.venture_score === "number")}
          onExport={exportReportPdf}
          exporting={pdfExporting}
        />

        {/* Tabs sit on their own light bar below the dark band, so the break
            between "the verdict" and "the evidence" is architectural rather
            than another border. */}
        <div className="an-tabbar">
          <div className="an-tabs" role="tablist">
            {tabs.map((t) => (
              <button
                key={t}
                role="tab"
                aria-selected={activeTab === t}
                className={`an-tab${activeTab === t ? " an-tab-active" : ""}`}
                onClick={() => setActiveTab(t)}
              >
                {t}
                {/* One element that slides between tabs, rather than a border
                    that blinks on and off. layoutId is what makes it travel. */}
                {activeTab === t && (
                  <motion.span
                    layoutId="an-tab-underline"
                    className="an-tab-underline"
                    transition={{ type: "spring", stiffness: 420, damping: 34 }}
                  />
                )}
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
            {/* Verification did not run. A different sentence entirely from
                "we searched and found nothing", and the one the reader needs
                when the cause is our provider rather than the company. */}
            {report.claims_verification_degraded && (
              <div role="alert" style={{ marginBottom: 14, padding: "12px 14px", border: "1px solid #F0D9A8", borderRadius: 10, background: "#FFFBF0", color: "#7A5514", fontSize: 13, lineHeight: 1.55 }}>
                <strong>Claim verification did not run for this report.</strong> The
                language model was unavailable while this deck was analysed, so the
                claims below were never checked against public sources. This says
                nothing about the company — nothing was established either way, and
                the score has not been reduced for it. Re-run the analysis to verify
                them.
              </div>
            )}
            {/* Milder than the banner above, and deliberately worded so it
                cannot be misread as a finding: the checks ran, but on a
                narrower evidence base than usual. */}
            {report.evidence_search_degraded && !report.claims_verification_degraded && (
              <div role="status" style={{ marginBottom: 14, padding: "12px 14px", border: "1px solid #CFE0F5", borderRadius: 10, background: "#F5F9FF", color: "#1F4E8C", fontSize: 13, lineHeight: 1.55 }}>
                <strong>Claims were checked against a narrower set of sources.</strong> The
                general web index was rate-limited during this analysis, so the
                fallback providers supplied the evidence. The verdicts below are
                real and count towards the score, but an unconfirmed claim here is
                more likely to mean we could not reach the right page than that the
                claim is wrong. Re-running later will search the open web again.
              </div>
            )}
            {!report.incomplete_analysis && report.claims_unverified && !report.claims_verification_degraded && (
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
                {/* Extraction coverage sits ABOVE the score, deliberately.
                    It qualifies everything below it: if most of the deck never
                    reached a structured field, then the claims table, the
                    evidence penalty and the score derived from them are all
                    measurements of a partial reading. A reader who sees the
                    score first and the caveat later has already formed a view.
                    See extraction_coverage.py for why "we found nothing" and
                    "there was nothing to find" had to stop looking identical. */}
                {coverage?.available && (
                  <div style={{
                    border: `1px solid ${coverageTone}33`, background: `${coverageTone}0D`,
                    borderRadius: 10, padding: "12px 14px", marginBottom: 12,
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
                      <SLabel>Extraction Coverage</SLabel>
                      <span style={{
                        fontFamily: "var(--font-mono)", fontSize: 15, fontWeight: 700,
                        color: coverageTone,
                      }}>{coverage.coverage_pct}%</span>
                      <span style={{
                        fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600,
                        letterSpacing: "0.08em", color: coverageTone,
                        border: `1px solid ${coverageTone}33`, background: `${coverageTone}12`,
                        borderRadius: 5, padding: "2px 7px",
                      }}>{coverage.verdict}</span>
                      <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "#5D6B7F" }}>
                        {coverage.represented_slides} of {coverage.content_slides} content slides reached a structured field
                      </span>
                    </div>
                    <p style={{ fontSize: 12.5, color: "#4A5568", lineHeight: 1.65, margin: "8px 0 0" }}>
                      {coverage.interpretation}
                    </p>
                    {(coverage.unrepresented_slides ?? []).length > 0 && (
                      <div style={{ marginTop: 10, borderTop: "1px solid var(--border)", paddingTop: 8 }}>
                        <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "#5D6B7F", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>
                          Slides not represented below
                        </div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                          {coverage.unrepresented_slides!.slice(0, 12).map((s: { slide: number; heading: string }, i: number) => (
                            <span key={i} title={s.heading} style={{
                              fontFamily: "var(--font-mono)", fontSize: 9.5, color: "#64748B",
                              border: "1px solid var(--border)", borderRadius: 5, padding: "2px 6px",
                              background: "var(--surface-2)",
                            }}>{s.slide}. {s.heading.slice(0, 24)}</span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Which extraction path produced this report. A silent
                    fallback to regex is the defect this whole pass exists to
                    make impossible; the reader of the claims table is the
                    person who needs to know it fired. */}
                {extractionProvenance?.is_fallback && (
                  <div style={{
                    border: "1px solid rgba(217,48,37,0.28)", background: "rgba(217,48,37,0.06)",
                    borderRadius: 10, padding: "12px 14px", marginBottom: 12,
                  }}>
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "#D93025", letterSpacing: "0.12em", fontWeight: 600, textTransform: "uppercase", marginBottom: 6 }}>
                      ⚠ Degraded extraction — {extractionProvenance.method}
                    </div>
                    <p style={{ fontSize: 12.5, color: "#4A5568", lineHeight: 1.65, margin: 0 }}>
                      {extractionProvenance.warning}
                    </p>
                  </div>
                )}

                {/* The trained model's score leads the summary. It is the one
                    number on this page that came from a fitted, calibrated
                    model rather than from an LLM or a hand-tuned formula, so
                    it sits above the derived stat cards rather than among
                    them. */}
                <Reveal>
                  <VentureScorePanel
                    data={report.sections?.venture_score}
                    reportedScore={Math.round(score)}
                    incompleteAnalysis={report.incomplete_analysis}
                  />
                </Reveal>

                <div className="an-stat-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "14px" }}>
                  {[
                    { label: "Market Evidence", value: `${Math.round((market?.confidence ?? 0) * 100)}%`, color: "#0EA66A", bg: "rgba(14,166,106,0.08)", border: "rgba(14,166,106,0.2)", tip: "Evidence confidence from the market agent" },
                    {
                      label: "Claims Verified",
                      // "0/5" reads as a finding. When verification never ran,
                      // there is no ratio to report.
                      value: report.claims_verification_degraded
                        ? "Not run"
                        : `${report.claims_supported}/${report.claims_verified}`,
                      color: report.claims_verification_degraded ? "#5D6B7F" : "#1D6FE8",
                      bg: report.claims_verification_degraded ? "rgba(93,107,127,0.08)" : "rgba(29,111,232,0.08)",
                      border: report.claims_verification_degraded ? "rgba(93,107,127,0.2)" : "rgba(29,111,232,0.2)",
                      tip: report.claims_verification_degraded
                        ? "The language model was unavailable, so claims were not checked"
                        : "Web-verified claims",
                    },
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
                      <div className="an-case-item"><span className="an-case-text" style={{ color: "#5D6B7F" }}>
                        {specialistDegraded("bull")
                          ? "The bull-case agent did not run — the language model was unavailable. Nothing was established either way."
                          : "No positive signals identified."}
                      </span></div>
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
                      <div className="an-case-item"><span className="an-case-text" style={{ color: "#5D6B7F" }}>
                        {specialistDegraded("bear")
                          ? "The bear-case agent did not run — the language model was unavailable. Nothing was established either way."
                          : "No red flags identified."}
                      </span></div>
                    )}
                  </Panel>
                </div>

                <Panel className="vf-panel-neutral" accentColor="#1D6FE8">
                  <SLabel>AI Investment Verdict</SLabel>
                  <div className="an-verdict-headline">{report.recommendation}</div>
                  {/* The memo used to be shown as `.slice(0, 400) + "…"`, cut
                      mid-word, with the full text rendered nowhere else on the
                      page — so the product's main written output was readable
                      only for its first 400 characters. It is also Markdown,
                      which a plain <p> printed as literal `**` and `###`.
                      MemoText renders it and trims the collapsed preview at a
                      word boundary. */}
                  <div style={{ fontSize: "13.5px", color: "var(--text-secondary)", margin: "0 0 14px" }}>
                    {memoExpanded ? (
                      <MemoText text={memoFull} />
                    ) : (
                      <p style={{ margin: 0, lineHeight: 1.7 }}>
                        {memoSummary.preview}
                        {memoSummary.truncated && "…"}
                      </p>
                    )}

                    {(memoSummary.truncated || memoExpanded) && (
                      <button
                        type="button"
                        onClick={() => setMemoExpanded((o) => !o)}
                        aria-expanded={memoExpanded}
                        style={{
                          marginTop: 10, background: "none", border: "none", padding: 0,
                          cursor: "pointer", font: "inherit", fontSize: 12, fontWeight: 600,
                          color: "var(--accent)", display: "inline-flex", alignItems: "center", gap: 4,
                        }}
                      >
                        {memoExpanded ? "Show less" : "Read the full memo"}
                        {memoExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                      </button>
                    )}
                  </div>
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
                        <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "#1D6FE8", background: "rgba(29,111,232,0.08)", border: "1px solid rgba(29,111,232,0.2)", padding: "2px 7px", borderRadius: 20 }}>
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
                  )) : <div className="an-case-text" style={{ color: "#5D6B7F" }}>Insufficient market evidence in the submitted deck.</div>}
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
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#5D6B7F", padding: "16px 0" }}>
                        No claim verification data available.
                      </div>
                    )}
                  </Panel>

                  <Panel accentColor="#C47A0A">
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "#C47A0A", letterSpacing: "0.12em", marginBottom: "12px", fontWeight: "600", textTransform: "uppercase" }}>⚡ AI Signal</div>
                    <p style={{ fontSize: "13px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 14px" }}>
                      {market?.recommendation || "Validate market size, buyer demand, and competition with primary evidence."}
                    </p>
                    <div style={{ padding: "12px", background: "rgba(196,122,10,0.06)", borderRadius: "8px", border: "1px solid rgba(196,122,10,0.15)" }}>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "#C47A0A", marginBottom: "4px" }}>EVIDENCE GAPS</div>
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
                        <PolarAngleAxis dataKey="subject" tick={{ fill: "#64748B", fontFamily: "var(--font-mono)", fontSize: 10 }} />
                        <PolarRadiusAxis tick={false} axisLine={false} domain={[0, 100]} />
                        <Radar dataKey="value" stroke="#1D6FE8" fill="#1D6FE8" fillOpacity={0.09} strokeWidth={2.5} dot={{ fill: "#1D6FE8", r: 4, strokeWidth: 0 } as any} />
                      </RadarChart>
                    </ResponsiveContainer> : <p style={{ color: "#5D6B7F", fontSize: 13, lineHeight: 1.7 }}>
                      {/* Do not assert *why* the scores are missing. The team analyst
                          returns the same empty `capabilities` list whether the deck
                          genuinely had no team slide or the agent call failed, and
                          claiming the former when the latter happened is the kind of
                          confidently-wrong empty state this tab already had once. */}
                      The team analyst produced no capability scores for this deck.
                      {founderChecks.length > 0
                        ? " Founder names were found and checked against public web evidence — see below."
                        : founderDiscovery?.attempted
                          ? " The deck names no founders; a public search was run for them — see below."
                          : " No founder names were submitted and no public search was run."}
                      {report.incomplete_analysis
                        ? " This analysis is flagged incomplete, so the agent may not have run at all."
                        : ""}
                    </p>}
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 6, borderTop: "1px solid var(--border)", paddingTop: 12 }}>
                      {teamRadarData.map((r, i) => (
                        <div key={i} style={{ display: "flex", alignItems: "center", gap: 5, padding: "3px 8px", background: "var(--surface-2)", borderRadius: 6, border: "1px solid var(--border)" }}>
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "#5D6B7F" }}>{r.subject}</span>
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 600, color: r.value >= 70 ? "#0EA66A" : "#C47A0A" }}>{r.value}</span>
                        </div>
                      ))}
                    </div>
                  </Panel>

                  <Panel accentColor="#D93025">
                    <div style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "#D93025", letterSpacing: "0.12em", marginBottom: "12px", fontWeight: "600", textTransform: "uppercase" }}>⚠ Gap Identified</div>
                    <p style={{ fontSize: "13px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 16px" }}>
                      {team?.gaps?.[0] || "Insufficient team evidence. Verify founder credentials independently."}
                    </p>
                    <div style={{ borderTop: "1px solid var(--border)", paddingTop: "14px", marginBottom: 14 }}>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "#5D6B7F", letterSpacing: "0.12em", marginBottom: "8px", textTransform: "uppercase" }}>Recommendation</div>
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
                            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6, flexWrap: "wrap" }}>
                              <span className="an-founder-name">{check.name}</span>
                              {/* Where the NAME came from. A name the deck put in
                                  writing and a name this tool went and found are
                                  different grades of evidence, and showing them
                                  identically would credit the deck with an
                                  assertion it never made. */}
                              {check.origin && (
                                <span title={check.origin === "deck"
                                  ? "This name was printed in the uploaded deck."
                                  : "The deck named no founders. This name was found by searching public sources and appears verbatim in the cited pages."}
                                  style={{
                                    fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600,
                                    letterSpacing: "0.06em",
                                    color: check.origin === "deck" ? "#1D6FE8" : "#7A5AF8",
                                    border: `1px solid ${check.origin === "deck" ? "#1D6FE8" : "#7A5AF8"}33`,
                                    background: `${check.origin === "deck" ? "#1D6FE8" : "#7A5AF8"}12`,
                                    borderRadius: 5, padding: "2px 7px", textTransform: "uppercase",
                                  }}>
                                  {check.origin === "deck" ? "From deck" : "Found by search"}
                                </span>
                              )}
                              <span style={{
                                fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600,
                                letterSpacing: "0.08em", color: tone, border: `1px solid ${tone}33`,
                                background: `${tone}12`, borderRadius: 5, padding: "2px 7px",
                              }}>{check.assessment}</span>
                              <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "#5D6B7F" }}>
                                confidence {Math.round((check.confidence ?? 0) * 100)}%
                              </span>
                            </div>
                            <p className="an-founder-desc">{check.evidence_summary}</p>
                            {(check.sources ?? []).length > 0 && (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                {(check.sources ?? []).slice(0, 4).map((url, j) => (
                                  <a key={j} href={url} target="_blank" rel="noreferrer" style={{
                                    fontFamily: "var(--font-mono)", fontSize: 9.5,
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
                    /* The deck named nobody. That is no longer the end of the
                       road: agents/founder_research.py searches public sources
                       and this reports what it found, including the honest
                       "searched and found nothing" case. The old copy here
                       ("No founder names were submitted") described a missing
                       INPUT, which read as the user's fault for a condition
                       most real decks are in. */
                    <div style={{ margin: "10px 0 0" }}>
                      {founderDiscovery?.attempted ? (
                        <>
                          {/* Three different states, three different colours.
                              "The search could not run" and "we searched and
                              found nothing" are opposite findings -- only the
                              second says anything about the company -- and
                              rendering them in the same grey paragraph is the
                              same conflation this product removed from the
                              extraction path. */}
                          <div style={{
                            display: "inline-block", marginBottom: 8,
                            fontFamily: "var(--font-mono)", fontSize: 9, fontWeight: 600,
                            letterSpacing: "0.08em", textTransform: "uppercase",
                            borderRadius: 5, padding: "3px 8px",
                            color: founderDiscovery.search_failed || founderDiscovery.degraded ? "#D93025"
                              : founderDiscovery.searched === false ? "#64748B" : "#C47A0A",
                            border: `1px solid ${founderDiscovery.search_failed || founderDiscovery.degraded ? "#D93025"
                              : founderDiscovery.searched === false ? "#64748B" : "#C47A0A"}33`,
                            background: `${founderDiscovery.search_failed || founderDiscovery.degraded ? "#D93025"
                              : founderDiscovery.searched === false ? "#64748B" : "#C47A0A"}12`,
                          }}>
                            {founderDiscovery.search_failed
                              ? "⚠ Search failed — nothing established"
                              : founderDiscovery.degraded
                                ? "⚠ Research did not run — nothing established"
                                : founderDiscovery.searched === false
                                  ? "Search not attempted"
                                  : "Searched — no founders found"}
                          </div>
                          <p style={{ color: "#4A5568", fontSize: 13, lineHeight: 1.7, margin: 0 }}>
                            {founderDiscovery.searched === false || founderDiscovery.degraded
                              ? ""
                              : "This deck does not name its founders, so VentureFlow searched public sources for them. "}
                            {founderDiscovery.found
                              ? "Names were found but no background check completed for them."
                              : founderDiscovery.reason || "No founder name could be established."}
                          </p>
                          {(founderDiscovery.rejected_ungrounded ?? []).length > 0 && (
                            <p style={{ color: "#5D6B7F", fontSize: 12, lineHeight: 1.7, margin: "8px 0 0" }}>
                              {founderDiscovery.rejected_ungrounded!.length} candidate name(s) were
                              proposed but did not appear in any retrieved source, and were rejected
                              rather than reported as findings.
                            </p>
                          )}
                          {(founderDiscovery.sources_consulted ?? []).length > 0 && (
                            <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 10 }}>
                              {founderDiscovery.sources_consulted!.slice(0, 6).map((url, j) => (
                                <a key={j} href={url} target="_blank" rel="noreferrer" style={{
                                  fontFamily: "var(--font-mono)", fontSize: 9.5,
                                  color: "#1D6FE8", textDecoration: "none",
                                  border: "1px solid rgba(29,111,232,0.2)", borderRadius: 5, padding: "2px 6px",
                                }}>{(() => { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return "source"; } })()}</a>
                              ))}
                            </div>
                          )}
                        </>
                      ) : (
                        <p style={{ color: "#5D6B7F", fontSize: 13, lineHeight: 1.7, margin: 0 }}>
                          No founder names were submitted and no public search was run for this
                          analysis.
                        </p>
                      )}
                    </div>
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
                    {corpusComparables.length > 0 && !isTwoPopulationReport && (
                      <div style={{
                        background: "rgba(148,163,184,0.10)",
                        border: "1px solid rgba(148,163,184,0.35)",
                        borderRadius: 6, padding: "8px 10px", margin: "8px 0 12px",
                      }}>
                        <p style={{ color: "#5D6B7F", fontSize: 12, fontWeight: 600, margin: 0 }}>
                          Y Combinator companies only — this report predates the wider corpus
                        </p>
                        <p style={{ color: "#5D6B7F", fontSize: 11, lineHeight: 1.6, margin: "4px 0 0" }}>
                          It was produced when comparables were drawn from Y Combinator
                          alumni alone, so no non-YC company could have appeared in the
                          table below. Re-running the analysis searches the wider corpus.
                          The report's own caveat, shown under the table, describes the
                          run that produced it.
                        </p>
                      </div>
                    )}

                    {corpusComparables.length > 0 && isTwoPopulationReport && (
                      <div style={{
                        background: "rgba(234,179,8,0.08)",
                        border: "1px solid rgba(234,179,8,0.35)",
                        borderRadius: 6, padding: "8px 10px", margin: "8px 0 12px",
                      }}>
                        <p style={{ color: "#EAB308", fontSize: 12, fontWeight: 600, margin: 0 }}>
                          Two populations, searched separately
                        </p>
                        {/*
                          This banner used to read "Y Combinator companies only
                          -- no non-YC startups are represented". That was true
                          when the corpus was one accelerator's portfolio and is
                          false now, so it says what is actually searched.
                        */}
                        <p style={{ color: "#5D6B7F", fontSize: 11, lineHeight: 1.6, margin: "4px 0 0" }}>
                          Matched against{" "}
                          {typeof marketComparables?.population_total === "number"
                            ? `${marketComparables.population_total.toLocaleString()} companies`
                            : "companies"}{" "}
                          with a publicly recorded outcome
                          {populationSummary ? ` — ${populationSummary}` : ""}. Places are
                          reserved for each population rather than pooled, because the
                          text embedder was fitted on YC's own writing and a pooled
                          ranking returns almost only YC rows for reasons of writing
                          style rather than business similarity. These are the nearest
                          available matches, not necessarily close ones.
                        </p>
                        {/*
                          Measured, and stated because the number invites the
                          opposite reading: cosine similarity on this TF-IDF
                          embedder is LEXICAL.
                        */}
                        <p style={{ color: "#5D6B7F", fontSize: 11, lineHeight: 1.6, margin: "6px 0 0" }}>
                          The similarity percentage measures shared wording, not
                          business relevance — an unrelated company can score
                          higher than a relevant one. And the two populations are
                          not on one scale: a 62% against a market-wide company is
                          not weaker evidence than a 68% against a YC company.
                          Read the names, not the number.
                        </p>
                        {Object.entries(populations).some(([, v]) => v?.note) && (
                          <p style={{ color: "#5D6B7F", fontSize: 11, lineHeight: 1.6, margin: "6px 0 0" }}>
                            {Object.entries(populations)
                              .filter(([, v]) => v?.note)
                              .map(([key, v]) => `${v.label ?? key}: ${v.note}`)
                              .join(" ")}
                          </p>
                        )}
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
                        <p style={{ color: "#5D6B7F", fontSize: 12, lineHeight: 1.6, margin: "6px 0 0" }}>
                          The nearest company in either corpus scored{" "}
                          {typeof marketComparables.best_similarity === "number"
                            ? `${Math.round(marketComparables.best_similarity * 100)}%`
                            : "below"}{" "}
                          similarity, under the{" "}
                          {typeof marketComparables.threshold === "number"
                            ? `${Math.round(marketComparables.threshold * 100)}%`
                            : ""}{" "}
                          floor. Nothing is shown rather than presenting distant
                          matches as comparable. This is the expected result for a
                          company with no close analogue in either population.
                        </p>
                      </div>
                    )}
                    {competitors.length ? <>
                      <table className="an-comp-table">
                        <thead>
                          <tr>
                            {["Company",
                              ...(isTwoPopulationReport ? ["Population"] : []),
                              "Batch / Domain", "Sector", "Outcome", "Similarity"].map((h) => (
                              <th key={h} className="an-comp-th">{h}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {competitors.map((competitor, i) => (
                            <tr key={i} className="an-comp-tr">
                              <td className="an-comp-td" style={{ fontWeight: 600 }}>
                                {/* Market rows link to the Wikidata item the
                                    outcome was read from. That every row is
                                    checkable is the corpus's whole claim to
                                    trustworthiness, so the link belongs on the
                                    name rather than in a footnote. */}
                                {competitor.sourceUrl ? (
                                  <a
                                    href={competitor.sourceUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    style={{ color: "var(--accent)", textDecoration: "underline" }}
                                  >
                                    {competitor.name}
                                  </a>
                                ) : competitor.name}
                              </td>
                              {isTwoPopulationReport && (
                                <td className="an-comp-td" style={{ color: "#5D6B7F", fontSize: 11 }}>
                                  {competitor.population || "—"}
                                </td>
                              )}
                              <td className="an-comp-td">{competitor.domain || "—"}</td>
                              <td className="an-comp-td">{competitor.sector || "—"}</td>
                              <td className="an-comp-td" style={{ color: competitor.outcome === "Shut down" ? "#D93025" : competitor.outcome ? "#0EA66A" : "#5D6B7F" }}>{competitor.outcome || "—"}</td>
                              <td className="an-comp-td">{typeof competitor.similarity === "number" ? `${Math.round(competitor.similarity * 100)}%` : "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <p style={{ color: "#5D6B7F", fontSize: 11, lineHeight: 1.6, marginTop: 12 }}>
                        Source: {comparablesSource}
                        {marketComparables?.caveat && corpusComparables.length ? ` — ${marketComparables.caveat}` : ""}
                      </p>
                      {corpusComparables.length > 0 && portfolioMatches.length > 0 && (
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
                    {/* A "Threat Distribution" donut sat here. Its data source was a
                        hardcoded empty array, so it drew an empty ring; there is no
                        threat-level signal anywhere in AnalyzeResponse to wire it to.
                        Removed rather than back-filled with plausible-looking
                        percentages. */}

                    <Panel accentColor="#C47A0A">
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: "9px", color: "#C47A0A", letterSpacing: "0.12em", marginBottom: "10px", fontWeight: "600", textTransform: "uppercase" }}>⚡ Recommendation</div>
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
