import { useState, useEffect, useRef, type ReactNode } from "react";
import {
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  AreaChart, Area, RadarChart, PolarGrid, PolarAngleAxis,
  PolarRadiusAxis, Radar, PieChart, Pie, Cell, BarChart, Bar,
} from "recharts";
import { CheckCircle, AlertTriangle, ChevronDown, ChevronUp, Download, ExternalLink, Globe, Shield, Upload, Zap } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";
import { authHeaders, handleSignedOut } from "../services/apiClient";
import { useApp } from "../context/AppContext";
import { useNavigate } from "react-router-dom";
import ReportFilm from "../components/analysis/ReportFilm";
import type { DeckPage } from "../components/analysis/DeckSculpture";
import AskDrawer from "../components/analysis/AskDrawer";
import EvidenceGraph from "../components/analysis/EvidenceGraph";
import ScoreLedger from "../components/analysis/ScoreLedger";
import { CapabilityRadar, ClaimBreakdown } from "../components/charts/Charts";
import { Reveal, Tilt } from "../components/ui/scroll";
import ReliabilityStrip from "../components/analysis/ReliabilityStrip";
import { formatDate, formatDateTime, displayDeckId } from "../utils/format";
import { Panel, SLabel, ScoreBadge } from "../components/ui/Panel";
import { MemoText, memoPreview } from "../components/ui/MemoText";
import InsightCard, { InsightCardStyles } from "../components/ui/InsightCard";
import { Button, ButtonStyles, Chip, Disclosure, EmptyState } from "../components/ui/primitives";
import PrefsControl from "../components/ui/PrefsControl";
import SourceList, { type SourceRef } from "../components/analysis/SourceList";

const tabs = ["Summary", "Evidence", "Market Validation", "Founder Analysis", "Competitor Insights"];

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
    <div
      className="vf-card"
      style={{ display: "flex", flexDirection: "column", maxHeight: 520 }}
    >
      <div style={{ padding: "13px 16px", borderBottom: "1px solid var(--border)" }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-primary)" }}>
          Ask this deck
        </div>
        <div style={{ fontSize: 12.5, color: "var(--text-muted)", marginTop: 2 }}>
          {sessionId
            ? "Answered from the deck's own text only."
            : "Available once an analysis has run."}
        </div>
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
            <button key={s} onClick={() => send(s)} disabled={!sessionId} className="an-chat-suggestion">
              {s}
            </button>
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
          className="an-chat-input"
        
        />
        <button type="submit" disabled={!sessionId || loading || !input.trim()} className="an-chat-send">
          Send
        </button>
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
    <div style={{ marginTop: 14 }}>
      <Disclosure
        summary="Notes for the deal team"
        defaultOpen={comments.length > 0}
        meta={comments.length > 0 ? <Chip size="sm" mono>{comments.length}</Chip> : undefined}
      >
      <div style={{ display: "flex", flexDirection: "column", gap: 8, maxHeight: 220, overflowY: "auto" }}>
        {comments.length === 0 && (
          <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
            {reportId ? "Nothing noted yet. Anyone with access to this report can read what you add." : "Available once an analysis has run."}
          </div>
        )}
        {comments.map((c) => (
          <div key={c.id} style={{ fontSize: 13, color: "var(--text-secondary)" }}>
            <span style={{ fontWeight: 600, color: "var(--text-primary)" }}>{c.author_name}</span>
            <span style={{ color: "var(--text-muted)", fontSize: 12, marginLeft: 6 }}>{formatDateTime(c.created_at)}</span>
            <div style={{ marginTop: 2 }}>{c.body}</div>
          </div>
        ))}
      </div>
      <form onSubmit={submit} style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 7 }}>
        <input
          className="an-chat-input"
          value={authorName} onChange={(e) => setAuthorName(e.target.value)}
          placeholder="Your name (optional)" disabled={!reportId}
        />
        <div style={{ display: "flex", gap: 8 }}>
          <input
            className="an-chat-input"
            value={body} onChange={(e) => setBody(e.target.value)}
            placeholder={reportId ? "Add a note" : "Run analysis first"}
            disabled={!reportId || posting}
          />
          <button type="submit" disabled={!reportId || posting || !body.trim()} className="an-chat-send">
            Post
          </button>
        </div>
      </form>
      </Disclosure>
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
          <div style={{ fontFamily: "var(--font-display)", fontSize: 22, marginBottom: 8, color: "var(--text)" }}>
            Agents are running…
          </div>
          <div style={{ fontFamily: "var(--font-sans)", fontSize: 12.5, color: "#5D6B7F", marginBottom: 16 }}>
            {currentStage}
          </div>
          <div style={{ width: 240, height: 4, background: "rgba(15,23,42,0.07)", borderRadius: 4, overflow: "hidden" }}>
            <motion.div style={{ height: "100%", background: "#1D6FE8", borderRadius: 4 }}
              animate={{ width: `${progressPct}%` }} transition={{ duration: 0.5 }} />
          </div>
          <div style={{ fontFamily: "var(--font-sans)", fontSize: 11.5, color: "#5D6B7F", marginTop: 8 }}>
            {progressPct}% complete
          </div>
        </>
      ) : (
        <>
          <ButtonStyles />
          {/* Two ways out, not one. This screen is reached by clicking
              "Analysis" in the sidebar with nothing loaded, and for someone
              with twenty saved reports the useful action is usually opening
              one of them rather than running a new deck. */}
          <EmptyState
            icon={<Upload size={20} />}
            title="No report open"
            body="Open one of your saved analyses, or upload a new deck to run one."
            action={
              <div style={{ display: "flex", gap: 10, justifyContent: "center", flexWrap: "wrap" }}>
                <Button variant="primary" icon={<Upload size={15} />} onClick={() => navigate("/upload")}>
                  Upload a deck
                </Button>
                <Button onClick={() => navigate("/")}>Browse saved analyses</Button>
              </div>
            }
          />
        </>
      )}
    </div>
  );
}

/**
 * One chapter of the report.
 *
 * The summary used to be eight white cards of identical weight stacked in a
 * column -- the reader had no way to tell where they were, what mattered, or
 * how much was left. A number, a title and a line of orientation cost very
 * little and turn a stack into a document.
 */
function Chapter({
  index,
  title,
  hint,
  children,
}: {
  index: string;
  title: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  /**
   * Staged, not all at once.
   *
   * The whole chapter used to be one Reveal: heading, hint and content faded
   * up together as a single block, which reads as a panel being switched on
   * rather than as a page being written. Each part now has its own observer
   * and its own delay, so scrolling into a chapter plays the order a reader
   * takes it in anyway -- number, title, subtitle, then the thing itself.
   *
   * Four observers per chapter rather than one. They are cheap, they
   * disconnect the moment they fire, and none of them is doing layout work.
   */
  return (
    <section className="an-chapter">
      <div className="an-chapter-head">
        <Reveal as="div" y={12} className="an-chapter-index-cell">
          <span className="an-chapter-index">{index}</span>
        </Reveal>
        <div style={{ minWidth: 0 }}>
          <Reveal as="div" delay={0.07} y={24}>
            <h2 className="an-chapter-title">{title}</h2>
          </Reveal>
          {hint && (
            <Reveal as="div" delay={0.15} y={16}>
              <p className="an-chapter-hint">{hint}</p>
            </Reveal>
          )}
        </div>
      </div>
      {/* Kept a column with the chapter's own gap: some chapters pass several
          children, and wrapping them in a plain div would collapse the spacing
          the section used to provide. */}
      <Reveal as="div" delay={0.22} y={28} className="an-chapter-body">
        {children}
      </Reveal>
    </section>
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
  const [tabDirection, setTabDirection] = useState<"fwd" | "back">("fwd");
  const selectTab = (next: string) => {
    setTabDirection(tabs.indexOf(next) >= tabs.indexOf(activeTab) ? "fwd" : "back");
    setActiveTab(next);
  };
  /**
   * Whether the opening chapter has scrolled away.
   *
   * A zero-height sentinel below the hero rather than a scroll listener on the
   * report: the browser reports the crossing itself, so nothing measures
   * layout on every frame of a long scroll.
   */
  const heroSentinel = useRef<HTMLDivElement>(null);
  const [heroGone, setHeroGone] = useState(false);
  const [ddOpen, setDdOpen] = useState(false);
  const [memoExpanded, setMemoExpanded] = useState(false);

  const [pdfExporting, setPdfExporting] = useState(false);

  useEffect(() => {
    const sentinel = heroSentinel.current;
    if (!sentinel || !("IntersectionObserver" in window)) return;
    const observer = new IntersectionObserver(
      ([entry]) => setHeroGone(!entry.isIntersecting && entry.boundingClientRect.top < 0),
      { threshold: 0 },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, []);
  const { report, sessionId } = useApp();
  const navigate = useNavigate();

  // If no report, show empty/loading
  if (!report) {
    return (
      <div className="an-root" style={{ fontFamily: "var(--font-sans)", color: "var(--text)", minHeight: "100vh", background: "var(--bg)" }}>
        <EmptyAnalysis />
      </div>
    );
  }

  // ── Derive display values from real report ────────────────────────────────
  const score = report.final_score;
  const scoreColor = score >= 75 ? "#0EA66A" : score >= 50 ? "#C47A0A" : "#D93025";
  /**
   * The risk level the pipeline returned -- not a number derived from it.
   *
   * This used to be `min(100, risk_signals_found * 3.5 + 10)`, bucketed into
   * High/Moderate/Low. Nothing measures that: the multiplier and the offset
   * are invented, and the result disagreed with the report's own
   * `risk_level` on screen. A deck whose pipeline returned UNKNOWN showed
   * "UNKNOWN risk" in the header and "Low" in the card six inches below it,
   * because the header read the field and the card read the formula.
   *
   * An absent level now reads as unknown, which is what it is.
   */
  const riskRaw = (report.risk_level || "").toUpperCase();
  const riskLabel = riskRaw === "HIGH" ? "High"
    : riskRaw === "MEDIUM" || riskRaw === "MODERATE" ? "Moderate"
      : riskRaw === "LOW" ? "Low"
        : "Unknown";
  const riskTone = riskLabel === "High" ? "negative" as const
    : riskLabel === "Moderate" ? "caution" as const
      : riskLabel === "Low" ? "positive" as const
        : "neutral" as const;
  const riskColor = riskLabel === "High" ? "var(--negative)"
    : riskLabel === "Moderate" ? "var(--caution)"
      : riskLabel === "Low" ? "var(--positive)"
        : "var(--text-muted)";

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

  /**
   * Every page the run opened, with what it was checking at the time.
   *
   * Three agents record sources and none of them were being shown. They are
   * merged here rather than in the component so the component stays a
   * presenter: it takes a flat list and knows nothing about report shape.
   *
   * Not a hook: this sits after the component's early returns, where a hook
   * would change the hook order between renders. It is a short loop over a
   * few arrays, and SourceList memoises the grouping that actually costs
   * something.
   */
  const sourceRefs: SourceRef[] = (() => {
    const refs: SourceRef[] = [];
    for (const d of claimsDetails) {
      for (const url of d.sources ?? []) {
        refs.push({ url, context: `Checked: ${d.claim}` });
      }
    }
    // The founder work records sources in two places, and they answer
    // different questions: `sources` is where the background evidence came
    // from, `discovery_sources` is where the NAME came from when the deck
    // disclosed none. Both were opened, so both are listed, labelled apart.
    for (const f of report.sections?.founder_verification ?? []) {
      for (const url of f.sources ?? []) {
        refs.push({ url, context: `Background check${f.name ? `: ${f.name}` : ""}` });
      }
      for (const url of f.discovery_sources ?? []) {
        refs.push({ url, context: `Searched to identify a founder${f.name ? `: ${f.name}` : ""}` });
      }
    }
    for (const url of report.sections?.founder_discovery?.sources_consulted ?? []) {
      refs.push({ url, context: "Searched for the company's founders" });
    }
    return refs;
  })();

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
  const marketConfidencePct = Math.round((market?.confidence ?? 0) * 100);

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
    // A private metric (ARR, customer counts) that public sources could not
    // settle is not "unverified" in the sense of a failed check -- no private
    // company publishes those numbers. It is labelled for what it is, and the
    // score no longer counts it against the company either.
    aiEstimate: c.verdict === "SUPPORTS" ? "Confirmed" : c.verdict === "REFUTES" ? "Disputed"
      : c.claim_kind === "internal" ? "Not publicly checkable" : "Unverified",
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
  /**
   * The deck's pages, as the extractor counted them.
   *
   * `content_slides` is the total it considered; `unrepresented_slides` are the
   * ones nothing structured came out of. Everything else is treated as read.
   * When coverage is unavailable -- older stored reports -- there are no pages,
   * and the scenes that depend on them do not render rather than guessing at a
   * page count.
   */
  const deckPages: DeckPage[] = (() => {
    const cov = report.extraction_coverage ?? report.sections?.extraction_coverage;
    const total = cov?.available ? cov.content_slides ?? 0 : 0;
    if (!total) return [];
    const dark = new Map(
      (cov?.unrepresented_slides ?? []).map((u) => [u.slide, u.heading] as const),
    );
    return Array.from({ length: Math.min(total, 60) }, (_, i) => {
      const slide = i + 1;
      return { slide, heading: dark.get(slide), read: !dark.has(slide) };
    });
  })();

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

        /* WHAT USED TO BE HERE, AND WHY IT HAD TO GO
           A :root block redefining --bg, --surface, --border,
           --text-primary and the rest as literal light-theme colours. It was
           written before the theme system existed and it beat that system on
           source order -- an injected style element lands after the stylesheet,
           and :root versus :root is decided by whichever came last. So on the
           DARK theme this page quietly forced --text-primary to #0B1120 and
           painted near-black text on a near-black page: the sticky bar's
           company name measured 1.06:1 against its backdrop, which is to say
           it was not there.

           Every name in that block already exists in styles/tokens.css and
           flips with the theme. What remains below is only the handful this
           page uses that the token system spells differently, mapped rather
           than restated, and scoped to .an-root so it cannot leak out. */
        .an-root {
          --blue:   var(--accent);
          --green:  var(--verified);
          --amber:  var(--caution);
          --red:    var(--critical);
          --shadow-sm: var(--e-1);
          --shadow-md: var(--e-2);
        }

                /* No ground of its own.
           This painted an opaque --bg across the whole report, which sits
           above the fixed ambience layer and hid it completely -- so the one
           screen a reader spends the most time scrolling was the one with no
           background motion at all. The body already carries --bg; letting it
           show through means the report is lit by the same room as every other
           page, which is the entire point of having one. */
        .an-root { font-family: var(--font-sans); color: var(--text-primary); min-height: 100vh; background: transparent; }

        /* ── VentureFlow Score panel ─────────────────────────────────── */
        .vs-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 26px 28px; margin-bottom: 0; }
        .vs-card-muted { background: var(--surface-2); }
        .vs-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap; }
        .vs-eyebrow { font-family: var(--font-sans); font-size: 11px; letter-spacing: 0.07em; text-transform: uppercase; color: var(--text-muted); margin: 0; font-weight: 600; }
        .vs-sub { font-size: 11.5px; color: var(--text-secondary); margin: 4px 0 0; }
        .vs-conf { font-family: var(--font-sans); font-size: 11.5px; font-weight: 600; padding: 4px 11px; border-radius: 20px; border: 1px solid; white-space: nowrap; }
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
        .vs-track-labels { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-muted); margin-top: 6px; }
        .vs-breakdown { border: 1px solid var(--border); border-radius: 10px; overflow: hidden; margin-bottom: 14px; }
        .vs-bd-row { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 9px 13px; font-size: 12.5px; border-bottom: 1px solid var(--border); }
        .vs-bd-row:last-child { border-bottom: none; }
        .vs-bd-row span { color: var(--text-secondary); }
        .vs-bd-row strong { font-variant-numeric: tabular-nums; font-size: 13px; }
        .vs-bd-total { background: var(--surface-2); }
        .vs-bd-total span { color: var(--text-primary); font-weight: 600; }
        .vs-stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
        .vs-stat { background: var(--surface-2); border: 1px solid var(--border); border-radius: 9px; padding: 9px 11px; display: flex; flex-direction: column; gap: 4px; }
        .vs-stat-k { font-family: var(--font-sans); font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em; font-weight: 600; color: var(--text-muted); }
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
        .vs-dl dt { font-family: var(--font-sans); font-size: 11px; text-transform: uppercase; letter-spacing: 0.07em; font-weight: 600; color: var(--text-muted); padding-top: 2px; }
        .vs-dl dd { margin: 0; line-height: 1.55; }
        .vs-caveat { font-size: 11.5px; line-height: 1.6; color: var(--text-secondary); margin: 12px 0 0; padding-top: 10px; border-top: 1px dashed var(--border); }
        .vs-meaning { margin-top: 14px; padding: 12px 14px; border-radius: 10px; background: rgba(15,23,42,0.03); border: 1px solid var(--border); font-size: 13px; line-height: 1.55; color: var(--text-primary); }
        .vs-meaning p { margin: 6px 0 0; }
        .vs-meaning-h { font-size: 12px; font-weight: 600; letter-spacing: 0.02em; margin: 0; }
        .vs-meaning-note { color: var(--text-secondary); font-size: 12px; }

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

        .an-eyebrow { font-family: var(--font-sans); font-size: 11px; color: var(--text-muted); letter-spacing: 0.07em; text-transform: uppercase; font-weight: 600; }

        .an-id-badge { font-family: var(--font-mono); font-size: 9.5px; color: var(--blue); letter-spacing: 0.06em; padding: 3px 10px; background: rgba(29,111,232,0.08); border: 1px solid rgba(29,111,232,0.2); border-radius: 20px; font-weight: 500; }

        .an-title { font-family: var(--font-display); font-size: 30px; font-weight: 400; letter-spacing: -0.01em; color: var(--text-primary); margin: 0 0 5px; line-height: 1; }

        .an-subtitle { font-family: var(--font-sans); font-size: 13px; color: var(--text-muted); margin-bottom: 20px; }

        .an-header-actions { display: flex; align-items: center; gap: 8px; padding-top: 4px; }

        .an-export-btn { display: inline-flex; align-items: center; gap: 6px; font-family: var(--font-sans); font-size: 12px; font-weight: 600; padding: 7px 14px; border-radius: 8px; background: var(--surface); border: 1px solid var(--border-strong); color: var(--text-secondary); cursor: pointer; transition: all 0.15s ease; }

        .an-export-btn:hover { background: var(--text-primary); color: #fff; border-color: var(--text-primary); }

        .an-confidence-chip { font-family: var(--font-sans); font-size: 11.5px; color: var(--positive); background: var(--positive-tint); border: 1px solid var(--positive-line); padding: 5px 12px; border-radius: 20px; font-weight: 600; }

        /* The tabs follow the reader down the document. Without this, moving
           from the memo to the claims table meant scrolling back to the top of
           a very long page to find the control that does it. */
        .an-tabbar {
          position: sticky; top: 0; z-index: 30;
          border-radius: 32px 32px 0 0;
          background: color-mix(in srgb, var(--surface-1) 82%, transparent);
          backdrop-filter: blur(16px) saturate(140%);
          border-bottom: 1px solid var(--border);
          padding: 0 var(--gutter);
          display: flex; align-items: center; gap: 24px;
          transition: box-shadow var(--dur-base) var(--ease-out);
        }
        .an-tabbar[data-stuck="true"] { box-shadow: var(--shadow-2); }

        /* The report's identity, for when the chapter that carried it has
           scrolled away. It is the only place the score is repeated, and it
           only exists while the hero is off screen. */
        .an-mini {
          display: flex; align-items: center; gap: 10px;
          opacity: 0; transform: translateY(4px); pointer-events: none;
          transition: opacity var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
          white-space: nowrap;
        }
        .an-tabbar[data-stuck="true"] .an-mini { opacity: 1; transform: none; }
        .an-mini-name { font-size: 14px; font-weight: 600; letter-spacing: -0.01em; }
        .an-mini-score {
          font-family: var(--font-display); font-size: 19px; line-height: 1;
          font-weight: 700;
        }
        @media (max-width: 720px) { .an-mini { display: none; } }

        .an-bar-btn {
          display: inline-flex; align-items: center; gap: 7px; flex-shrink: 0;
          padding: 7px 13px; border-radius: 999px; cursor: pointer;
          font-family: var(--font-sans); font-size: 12.5px; font-weight: 600;
          color: var(--text-secondary); background: var(--surface-2);
          border: 1px solid var(--border);
          transition: color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
        }
        .an-bar-btn:hover:not(:disabled) { color: var(--text-primary); border-color: var(--border-strong); }
        .an-bar-btn:disabled { opacity: 0.6; cursor: progress; }
        @media (max-width: 860px) { .an-bar-btn-label { display: none; } }

        .an-tabs { display: flex; gap: 2px; overflow-x: auto; scrollbar-width: none; }
        .an-tabs::-webkit-scrollbar { display: none; }

        .an-tab { position: relative; font-family: var(--font-sans); font-size: 13.5px; font-weight: 500; padding: 15px 20px; border: none; background: transparent; color: var(--text-2); cursor: pointer; transition: color var(--dur-fast) var(--ease-out); white-space: nowrap; letter-spacing: -0.01em; }
        .an-tab-underline { position: absolute; left: 12px; right: 12px; bottom: -1px; height: 2.5px; border-radius: 3px 3px 0 0; background: var(--blue); }

        .an-tab:hover { color: var(--text-secondary); }
        .an-tab-active { color: var(--accent-hover); font-weight: 600; }

        /* One measure, centred. The report used to run edge-to-edge in a
           column that was whatever was left after a 320px rail, so the line
           length changed with the window rather than with the content. */
        /* The documents, rising over the film.
           The rounded top edge and the shadow above it are the seam between
           the two halves of the product: everything above is the system
           speaking, everything below is the evidence, and the reader should
           feel the change of register before they read a word of it. */
        .an-stage {
          position: relative; z-index: 5;
          background: linear-gradient(180deg, var(--surface) 0%, transparent 460px);
          color: var(--text);
          border-radius: 32px 32px 0 0;
          margin-top: -32px;
        }
        .an-stage::before {
          content: ''; display: block; height: 1px;
          background: linear-gradient(90deg, transparent, var(--line-strong), transparent);
          border-radius: 32px 32px 0 0;
        }
        /* THE VERTICAL RHYTHM
           One value, used by every stack on this page, so the distance between
           two chapters is the same wherever they happen to sit in the tree.
           It was not: .an-body declared a 92px gap and had exactly TWO
           children -- one chapter, and a wrapper holding all the others. The
           gap applied once, and every chapter inside the wrapper stacked with
           no space at all, which is why a heading landed hard against the card
           above it. Anything that stacks chapters reads this. */
        .an-root { --rhythm: clamp(56px, 6.4vw, 92px); }

        .an-body {
          max-width: 1060px; margin: 0 auto;
          padding: 64px var(--gutter) 120px;
          display: flex; flex-direction: column; gap: var(--rhythm);
        }

        /* The wrapper the tabs swap. A stack in its own right, so it keeps the
           rhythm instead of collapsing it. */
        .tab-content-enter {
          display: flex; flex-direction: column; gap: var(--rhythm);
        }

        /* A chapter: a number, a title, and the thing itself. The numbers are
           the reader's position in the document, which a stack of identical
           cards never tells them. */
        .an-chapter { display: flex; flex-direction: column; gap: 26px; }
        .an-chapter-body { display: flex; flex-direction: column; gap: 26px; }
        /* The hint sits under the title inside its own reveal wrapper, so the
           margin that used to separate them moves to the wrapper. */
        .an-chapter-head .vf-reveal + .vf-reveal { margin-top: 6px; }
        /* The number hangs in the margin rather than pushing the title in.
           It was a flex sibling, so every chapter title started 34px to the
           right of the card beneath it and nothing on the page lined up with
           anything else. Pulled left by exactly its own width plus the gap,
           the title now sits flush with its content. */
        .an-chapter-head {
          display: flex; align-items: baseline; gap: 14px;
          margin-left: calc(-1 * (var(--index-w) + 14px));
        }
        .an-chapter { --index-w: 20px; }
        .an-chapter-index-cell { width: var(--index-w); flex-shrink: 0; text-align: right; }
        /* Below the width where there is a margin to hang in, it goes back
           inline -- a number half off the screen is worse than an indent. */
        @media (max-width: 1180px) {
          .an-chapter-head { margin-left: 0; }
        }
        .an-chapter-index {
          font-family: var(--font-mono); font-size: 12px; letter-spacing: 0.08em;
          color: var(--text-3); padding-top: 6px;
        }
        .an-chapter-title {
          font-family: var(--font-display); font-size: var(--display-md);
          letter-spacing: -0.02em; line-height: 1.05; margin: 0;
          color: var(--text-primary);
        }
        .an-chapter-hint {
          font-size: 14px; color: var(--text-muted); margin: 0;
          max-width: 62ch; line-height: 1.6;
        }

        @media (max-width: 720px) {
          .an-body { padding: 36px var(--gutter) 80px; }
        }

        .vf-panel { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 26px 28px; border-left-width: 3px; transition: border-color var(--dur-base) var(--ease-out); }

        .vf-panel:hover { border-color: var(--border-strong); }
        .vf-panel-neutral { border-left-color: var(--border) !important; }

        /* Inter, not mono: these are words. Matches .vf-label in
           styles/tailwind.css, which every other screen uses. */
        .vf-slabel { font-family: var(--font-sans); font-size: 11px; color: var(--text-muted); letter-spacing: 0.07em; text-transform: uppercase; font-weight: 600; margin-bottom: 14px; }

        .an-chat-suggestion {
          background: var(--surface); border: 1px solid var(--border-strong);
          border-radius: 20px; padding: 5px 11px; font-size: 12.5px;
          font-family: var(--font-sans); color: var(--text-secondary); cursor: pointer;
          transition: border-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
        }
        .an-chat-suggestion:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
        .an-chat-suggestion:disabled { cursor: not-allowed; opacity: 0.55; }

        .an-chat-input {
          flex: 1; min-width: 0; background: var(--surface-2);
          border: 1px solid var(--border-strong); border-radius: 8px;
          padding: 9px 12px; font-size: 13.5px; font-family: var(--font-sans);
          color: var(--text-primary); outline: none;
          transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
        }
        .an-chat-input:focus { border-color: var(--accent); background: var(--surface); box-shadow: 0 0 0 3px rgba(29,111,232,0.12); }

        .an-chat-send {
          background: var(--accent); border: none; border-radius: 8px;
          padding: 9px 15px; font-size: 13px; font-weight: 600; color: #fff;
          font-family: var(--font-sans); cursor: pointer;
          transition: background var(--dur-fast) var(--ease-out), opacity var(--dur-fast) var(--ease-out);
        }
        .an-chat-send:hover:not(:disabled) { background: var(--accent-strong); }
        .an-chat-send:disabled { opacity: 0.4; cursor: not-allowed; }

        /* A row, not a box. These sat as bordered, tinted cards inside an
           already-bordered panel, so a single bull point rendered as a box
           inside a box inside a card. */
        .an-case-item { display: flex; gap: 11px; align-items: flex-start; padding: 10px 0; border-bottom: 1px solid var(--border); cursor: default; }

        .an-case-item:last-child { border-bottom: none; padding-bottom: 0; }

        .an-case-text { font-size: 13px; color: var(--text-secondary); line-height: 1.6; flex: 1; }

        .score-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 20px; box-shadow: var(--shadow-sm); transition: transform 0.2s ease, box-shadow 0.2s ease; cursor: default; }

        .score-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }

        .an-verdict-headline { font-family: var(--font-display); font-size: 20px; color: var(--text-primary); letter-spacing: -0.02em; margin-bottom: 8px; line-height: 1.2; }

        .verdict-tag { font-family: var(--font-sans); font-size: 11.5px; padding: 4px 12px; border-radius: 20px; letter-spacing: 0.02em; font-weight: 600; cursor: default; transition: transform 0.15s ease; }

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

        .claims-th { font-family: var(--font-sans); font-size: 11px; color: var(--text-muted); letter-spacing: 0.07em; text-transform: uppercase; font-weight: 600; text-align: left; padding: 0 12px 10px 0; border-bottom: 1px solid var(--border); }

        .claims-tr { border-bottom: 1px solid rgba(15,23,42,0.05); transition: background 0.12s ease; }

        .claims-tr:hover { background: var(--surface-2); }
        .claims-tr:last-child { border-bottom: none; }

        .claims-td { font-size: 12.5px; padding: 9px 12px 9px 0; color: var(--text-secondary); }

        .match-chip { font-family: var(--font-sans); font-size: 11px; padding: 3px 9px; border-radius: 20px; font-weight: 600; }

        .an-founder-avatar { width: 40px; height: 40px; border-radius: 10px; background: var(--surface-2); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 12px; font-weight: 600; color: var(--text-secondary); flex-shrink: 0; transition: transform 0.2s ease; }

        .vf-panel:hover .an-founder-avatar { transform: scale(1.06); }

        .an-founder-name { font-size: 13.5px; font-weight: 600; color: var(--text-primary); letter-spacing: -0.01em; }
        .an-founder-role { font-family: var(--font-sans); font-size: 12.5px; color: var(--text-muted); margin-top: 2px; }
        .an-founder-desc { font-size: 12.5px; color: var(--text-secondary); line-height: 1.6; margin: 0 0 12px; }

        .an-risk-pill { font-family: var(--font-sans); font-size: 11.5px; padding: 4px 11px; border-radius: 20px; letter-spacing: 0.02em; font-weight: 600; }

        .an-comp-table { width: 100%; border-collapse: collapse; }

        .an-comp-th { font-family: var(--font-sans); font-size: 11px; color: var(--text-muted); letter-spacing: 0.07em; text-transform: uppercase; text-align: left; padding: 0 12px 12px 0; border-bottom: 1px solid var(--border); font-weight: 600; }

        .an-comp-tr { border-bottom: 1px solid rgba(15,23,42,0.05); transition: background 0.12s ease; cursor: default; }

        .an-comp-tr:hover { background: var(--surface-2); }
        .an-comp-tr:last-child { border-bottom: none; }
        .an-comp-td { font-size: 12.5px; padding: 11px 12px 11px 0; }

        .an-threat-row { display: flex; justify-content: space-between; align-items: center; padding: 7px 9px; border-radius: 7px; margin-bottom: 3px; transition: background 0.14s ease; cursor: default; }

        .an-threat-row:hover { background: var(--surface-2); }

        .tab-content-enter { animation: tab-slide-in 0.42s var(--ease-out) both; }
        .tab-content-enter[data-dir="back"] { animation-name: tab-slide-in-back; }
        @keyframes tab-slide-in {
          from { opacity: 0; transform: translate3d(26px, 0, 0); }
          to { opacity: 1; transform: none; }
        }
        @keyframes tab-slide-in-back {
          from { opacity: 0; transform: translate3d(-26px, 0, 0); }
          to { opacity: 1; transform: none; }
        }
        :root[data-motion="off"] .tab-content-enter, :root[data-motion="off"] .tab-content-enter[data-dir="back"] { animation: none; }
        

        @keyframes tab-fade-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }

        [data-tip] { position: relative; cursor: default; }
        [data-tip]:hover::after { content: attr(data-tip); position: absolute; bottom: calc(100% + 7px); left: 50%; transform: translateX(-50%); background: rgba(11,17,32,0.94); color: #F0F2F5; padding: 6px 11px; border-radius: 7px; font-family: var(--font-sans); font-size: 12px; white-space: nowrap; pointer-events: none; z-index: 200; }
        [data-tip]:hover::before { content: ''; position: absolute; bottom: calc(100% + 3px); left: 50%; transform: translateX(-50%); border: 4px solid transparent; border-top-color: rgba(11,17,32,0.92); z-index: 200; pointer-events: none; }
      `}</style>

      <div className="an-root">
        <InsightCardStyles />
        {/* THE VERDICT, FIRST.
            This was a pale header whose only statement of the result was a
            12px chip in the corner reading "48/100 overall score" -- the same
            size and weight as the Export button beside it. The answer a reader
            opens the report for now leads the page, at full size, with its
            interval and base rate attached so the number is never quoted
            alone. See ReportFilm for the reasoning. */}
        <ReportFilm
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
          bandKey={report.sections?.score_context?.available ? report.sections.score_context.band : undefined}
          bandLabel={report.sections?.score_context?.band_label}
          provisional={report.score_status === "provisional"}
          pages={deckPages}
          coveragePct={coverage?.available ? coverage.coverage_pct : undefined}
          readPages={coverage?.available ? coverage.represented_slides : undefined}
          totalPages={coverage?.available ? coverage.content_slides : undefined}
          /* The field in the closing scene is this report's own comparables --
             see Constellation for why it is the data rather than an ornament. */
          comparables={corpusComparables.map((c) => ({
            name: c.name,
            similarity: c.similarity,
            outcome: c.outcome,
            population: c.population,
          }))}
          bull={bullItems.map((b) => b.text)}
          bear={bearItems.map((b) => b.text)}
          /* "No signal found" and "the agent never ran" are different
             statements, and the scene says whichever one is true. */
          bullRan={!specialistDegraded("bull")}
          bearRan={!specialistDegraded("bear")}
          claims={claimsDetails.slice(0, 5).map((c) => ({
            claim: c.claim,
            verdict: c.verdict,
            confidence: c.confidence,
          }))}
          onExport={exportReportPdf}
          exporting={pdfExporting}
        />

        {/* Tabs sit on their own light bar below the dark band, so the break
            between "the verdict" and "the evidence" is architectural rather
            than another border. */}
        <div ref={heroSentinel} aria-hidden="true" />
        <div className="an-tabbar" data-stuck={heroGone}>
          <button className="an-bar-btn" onClick={() => navigate("/")} title="Back to all analyses">
            <Upload size={13} style={{ transform: "rotate(-90deg)" }} />
            <span className="an-bar-btn-label">All analyses</span>
          </button>
          <div className="an-mini" aria-hidden={!heroGone}>
            <span className="an-mini-name">{report.company}</span>
            <span className="an-mini-score" style={{ color: scoreColor }}>{Math.round(score)}</span>
          </div>
          <div className="an-tabs" role="tablist">
            {tabs.map((t) => (
              <button
                key={t}
                role="tab"
                aria-selected={activeTab === t}
                className={`an-tab${activeTab === t ? " an-tab-active" : ""}`}
                onClick={() => selectTab(t)}
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
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
          <PrefsControl compact />
          <button
            className="an-bar-btn"
            data-cursor="Export"
            onClick={exportReportPdf}
            disabled={pdfExporting}
          >
            <Download size={13} />
            <span className="an-bar-btn-label">{pdfExporting ? "Exporting…" : "Export PDF"}</span>
          </button>
          </div>
        </div>

        <div className="an-stage" data-mode="analytical">
          <div className="an-body">
            {/* Everything qualifying this report, in one collapsed panel.
                Six stacked full-width warnings stood here and in the top of
                the Summary tab; ReliabilityStrip holds all six texts, intact,
                behind their own headlines. */}
            <Chapter
              index="01"
              title="How much we could read"
              hint="Everything below rests on this."
            >
            <ReliabilityStrip
              coverage={coverage}
              provenance={extractionProvenance}
              incompleteAnalysis={report.incomplete_analysis}
              verificationDegraded={report.claims_verification_degraded}
              evidenceSearchDegraded={report.evidence_search_degraded}
              claimsUnverified={report.claims_unverified}
            />
            </Chapter>

            {/* ── SUMMARY ── */}
            {activeTab === "Summary" && (
              <div className="tab-content-enter" data-dir={tabDirection} key={activeTab}>
                {/* The trained model's score leads the summary. It is the one
                    number on this page that came from a fitted, calibrated
                    model rather than from an LLM or a hand-tuned formula, so
                    it sits above the derived stat cards rather than among
                    them. */}
                <Chapter
                  index="02"
                  title="The score"
                  hint="From a trained model, not the language model."
                >
                  <ScoreLedger
                    data={report.sections?.venture_score}
                    reportedScore={score}
                  />
                </Chapter>

                {/* Three figures, each with the working behind it.
                    These were three flat cards whose explanation lived in a
                    CSS `data-tip` hover tooltip -- unreachable on a touch
                    screen, unreadable to a screen reader, and (because the
                    tooltip fired on load) occasionally left stranded over the
                    card below. The explanation is now the back of the card. */}
                <Chapter
                  index="03"
                  title="What the run established"
                  hint="Press a card for its working."
                >
                <div className="an-stat-grid" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 16 }}>
                  <Tilt max={5}>
                  <InsightCard
                    label="Market evidence"
                    icon={<Globe size={14} />}
                    tone={marketConfidencePct >= 60 ? "positive" : marketConfidencePct > 0 ? "caution" : "neutral"}
                    value={`${marketConfidencePct}%`}
                    verdict={
                      marketConfidencePct > 0
                        ? "Confidence the market agent placed in its own evidence."
                        : "The market agent found nothing it could stand behind."
                    }
                  >
                    This is the market specialist's confidence in the evidence it
                    gathered for this deck&rsquo;s market claims &mdash; not a rating of
                    the market itself. A low figure means the supporting material was
                    thin or could not be reached, which is a statement about the
                    search, not about the opportunity.
                  </InsightCard>
                  </Tilt>

                  <Tilt max={5}>
                  <InsightCard
                    label="Claims verified"
                    icon={<CheckCircle size={14} />}
                    tone={report.claims_verification_degraded ? "neutral" : report.claims_supported > 0 ? "accent" : "caution"}
                    value={
                      /* "0/5" reads as a finding. When verification never ran,
                         there is no ratio to report. */
                      report.claims_verification_degraded
                        ? "Not run"
                        : `${report.claims_supported}/${report.claims_verified}`
                    }
                    verdict={
                      report.claims_verification_degraded
                        ? "The language model was unavailable during this run."
                        : "Deck claims corroborated by a public source."
                    }
                  >
                    {report.claims_verification_degraded
                      ? "No claim was checked, so nothing here counts for or against the company. Re-running the analysis will check them."
                      : "The deck's most checkable claims are searched against live sources; each verdict on the Market Validation tab carries the evidence and the source URL it came from. Claims that could not be settled are reported as unsettled rather than counted as failures."}
                  </InsightCard>
                  </Tilt>

                  <Tilt max={5}>
                  <InsightCard
                    label="Risk level"
                    icon={<Shield size={14} />}
                    tone={riskTone}
                    value={riskLabel}
                    verdict={
                      riskLabel === "Unknown"
                        ? "The pipeline returned no risk level for this deck."
                        : `${report.risk_signals_found} risk signal${report.risk_signals_found === 1 ? "" : "s"} detected in this deck.`
                    }
                  >
                    A blend of keyword and financial screening, a trained
                    disclosure model, and the language model&rsquo;s reading of the
                    deck. The trained part scores 0.997 AUC on SEC filings but
                    0.778 on pitch-deck wording, so treat this as a prompt for
                    diligence rather than a measurement.
                  </InsightCard>
                  </Tilt>
                </div>
                </Chapter>

                {/* Bull and bear are staged in the film above, full-bleed,
                    one side entering from each edge. Repeating them here as
                    two panels said the same thing a second time with less
                    force -- so this chapter now carries what the report was
                    actually missing: the pages the run opened, and a way to
                    go and read them. */}
                <Chapter
                  index="04"
                  title="Where this was checked"
                  hint="Every page the run opened."
                >
                {sourceRefs.length > 0 ? (
                  <SourceList sources={sourceRefs} />
                ) : (
                  <Panel className="vf-panel-neutral">
                    <p className="an-case-text" style={{ color: "var(--text-3)", margin: 0 }}>
                      No source was recorded for this run. Web verification either did
                      not run or returned nothing; the reliability notes above say
                      which.
                    </p>
                  </Panel>
                )}
                </Chapter>

                <Chapter
                  index="05"
                  title="The memo"
                  hint="Written over a score it did not compute."
                >
                <Panel className="vf-panel-neutral" accentColor="var(--accent)">
                  {/* This card was headed "AI Investment Verdict" above a
                      serif restatement of the recommendation -- the fourth
                      time the same two words appear on this screen, after the
                      header chip, the header band and the sidebar. What the
                      card actually holds is the written memo. */}
                  <SLabel>Investment memo</SLabel>
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
                  {/* A row of three chips stood here -- the recommendation,
                      the verified-claim count and the risk level -- directly
                      under a heading that already states the recommendation,
                      on a page whose header states it too and whose three
                      cards above state the other two. Five statements of the
                      same three facts within one screen. */}

                  <div className="dd-accordion">
                    <button className="dd-accordion-trigger" onClick={() => setDdOpen(o => !o)}>
                      <span style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 13 }}>📋</span>
                        Suggested Due Diligence Questions
                        <span style={{ fontFamily: "var(--font-sans)", fontSize: 12, fontWeight: 600, color: "var(--accent-hover)", background: "var(--accent-quiet)", border: "1px solid var(--accent-line)", padding: "2px 8px", borderRadius: 20 }}>
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
                </Chapter>
              </div>
            )}

            {/* ── EVIDENCE ── */}
            {activeTab === "Evidence" && (
              <div className="tab-content-enter" data-dir={tabDirection} key={activeTab}>
                <Chapter
                  index="E"
                  title="Every claim, and why"
                  hint="Select one to trace its verdict back to source."
                >
                  {!report.claims_verification_degraded && claimsDetails.length > 0 && (
                    <div style={{ marginBottom: 22 }}>
                      <ClaimBreakdown
                        supported={claimsDetails.filter((c) => c.verdict === "SUPPORTS").length}
                        refuted={claimsDetails.filter((c) => c.verdict === "REFUTES").length}
                        unsettled={claimsDetails.filter((c) => c.verdict === "NOT_ENOUGH_INFO").length}
                      />
                    </div>
                  )}
                  <EvidenceGraph
                    claims={claimsDetails}
                    degraded={Boolean(report.claims_verification_degraded)}
                  />
                </Chapter>
              </div>
            )}

            {/* ── MARKET VALIDATION ── */}
            {activeTab === "Market Validation" && (
              <div className="tab-content-enter" data-dir={tabDirection} key={activeTab}>
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

                <div>
                  <Panel accentColor="var(--caution)">
                    <SLabel color="var(--caution)">What to check next</SLabel>
                    <p style={{ fontSize: "13px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 14px" }}>
                      {market?.recommendation || "Validate market size, buyer demand, and competition with primary evidence."}
                    </p>
                    <div style={{ padding: "12px", background: "rgba(196,122,10,0.06)", borderRadius: "8px", border: "1px solid rgba(196,122,10,0.15)" }}>
                      <div style={{ fontFamily: "var(--font-sans)", fontSize: "11.5px", color: "#C47A0A", marginBottom: "4px" }}>EVIDENCE GAPS</div>
                      <div style={{ fontSize: "12.5px", color: "var(--text)", fontWeight: "600" }}>{market?.gaps?.[0] || "None identified."}</div>
                    </div>
                  </Panel>
                </div>
              </div>
            )}

            {/* ── FOUNDER ANALYSIS ── */}
            {activeTab === "Founder Analysis" && (
              <div className="tab-content-enter" data-dir={tabDirection} key={activeTab}>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 250px", gap: "12px" }}>
                  <Panel className="vf-panel-neutral" accentColor="var(--border)">
                    <SLabel>Team Capability Radar</SLabel>
                    {teamRadarData.length > 0 ? (
                      <CapabilityRadar
                        capabilities={teamRadarData.map((d) => ({ area: d.subject, score: d.value }))}
                      />
                    ) : <p style={{ color: "#5D6B7F", fontSize: 13, lineHeight: 1.7 }}>
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
                          <span style={{ fontFamily: "var(--font-sans)", fontSize: 11.5, color: "#5D6B7F" }}>{r.subject}</span>
                          <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, fontWeight: 600, color: r.value >= 70 ? "#0EA66A" : "#C47A0A" }}>{r.value}</span>
                        </div>
                      ))}
                    </div>
                  </Panel>

                  <Panel accentColor="#D93025">
                    <div style={{ fontFamily: "var(--font-sans)", fontSize: "11.5px", color: "#D93025", letterSpacing: "0.12em", marginBottom: "12px", fontWeight: "600", textTransform: "uppercase" }}>⚠ Gap Identified</div>
                    <p style={{ fontSize: "13px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 16px" }}>
                      {team?.gaps?.[0] || "Insufficient team evidence. Verify founder credentials independently."}
                    </p>
                    <div style={{ borderTop: "1px solid var(--border)", paddingTop: "14px", marginBottom: 14 }}>
                      <div style={{ fontFamily: "var(--font-sans)", fontSize: "11.5px", color: "#5D6B7F", letterSpacing: "0.12em", marginBottom: "8px", textTransform: "uppercase" }}>Recommendation</div>
                      <div style={{ fontSize: "13.5px", color: "var(--text)", fontWeight: "700", letterSpacing: "-0.01em" }}>
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
                                    fontFamily: "var(--font-sans)", fontSize: 11.5, fontWeight: 600,
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
                                fontFamily: "var(--font-sans)", fontSize: 11.5, fontWeight: 600,
                                letterSpacing: "0.08em", color: tone, border: `1px solid ${tone}33`,
                                background: `${tone}12`, borderRadius: 5, padding: "2px 7px",
                              }}>{check.assessment}</span>
                              <span style={{ fontFamily: "var(--font-sans)", fontSize: 11.5, color: "#5D6B7F" }}>
                                confidence {Math.round((check.confidence ?? 0) * 100)}%
                              </span>
                            </div>
                            <p className="an-founder-desc">{check.evidence_summary}</p>
                            {(check.sources ?? []).length > 0 && (
                              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                                {(check.sources ?? []).slice(0, 4).map((url, j) => (
                                  <a key={j} href={url} target="_blank" rel="noreferrer" style={{
                                    fontFamily: "var(--font-sans)", fontSize: 11.5,
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
                            fontFamily: "var(--font-sans)", fontSize: 11.5, fontWeight: 600,
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
                                  fontFamily: "var(--font-sans)", fontSize: 11.5,
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
              <div className="tab-content-enter" data-dir={tabDirection} key={activeTab} style={{ display: "flex", flexDirection: "column", gap: 14 }}>
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
                      <div style={{ fontFamily: "var(--font-sans)", fontSize: "11.5px", color: "#C47A0A", letterSpacing: "0.12em", marginBottom: "10px", fontWeight: "600", textTransform: "uppercase" }}>⚡ Recommendation</div>
                      <p style={{ fontSize: "13px", color: "#4A5568", lineHeight: 1.7, margin: "0 0 10px" }}>
                        {score >= 65 ? "Competitive position appears defensible. Validate specific differentiation claims." : "High competitive pressure detected. Requires clear differentiation strategy."}
                      </p>
                    </Panel>
                  </div>
                </div>

              </div>
            )}
          </div>

        </div>

        {/* Docked rather than pinned beside the report -- see AskDrawer. */}
        <AskDrawer
          chat={<ChatPanel sessionId={sessionId} />}
          notes={<CommentsPanel reportId={report.report_id ?? null} />}
        />
      </div>
    </>
  );
};

export default Analysis;
