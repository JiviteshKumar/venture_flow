import { useEffect, useState } from "react";
import { Lift, Stagger, StaggerItem } from "../components/ui/Motion";
import {
  XAxis, YAxis, Tooltip, ResponsiveContainer,
  CartesianGrid, AreaChart, Area,
} from "recharts";
import { motion } from "framer-motion";
import {
  TrendingUp, TrendingDown, DollarSign, Activity, Shield,
  Download, Zap, AlertCircle, CheckCircle2,
  BarChart2, Users, Upload,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import { useNavigate } from "react-router-dom";
import { api, authHeaders, ReportSummary } from "../services/apiClient";
import { formatDate, formatDateShort, displayDeckId } from "../utils/format";
import { ChartTooltip } from "../components/charts/ChartTooltip";

// ─── HELPERS ─────────────────────────────────────────────────────────────────

const MiniSparkline = ({ data, color }: { data: number[]; color: string }) => {
  const min = Math.min(...data), max = Math.max(...data);
  const w = 52, h = 22;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / (max - min || 1)) * h;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: "block" }} aria-hidden="true">
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.7" />
      <circle cx={parseFloat(pts.split(" ").pop()!.split(",")[0])} cy={parseFloat(pts.split(" ").pop()!.split(",")[1])} r="2" fill={color} />
    </svg>
  );
};

// ─── EMPTY STATE ─────────────────────────────────────────────────────────────

const EmptyDashboard = () => {
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
          <motion.div
            animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1.2, ease: "linear" }}
            style={{ marginBottom: 24 }}>
            <Zap size={36} color="#1D6FE8" />
          </motion.div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 22, marginBottom: 8, color: "#0B1120" }}>
            Analysis in progress…
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#5D6B7F", marginBottom: 16 }}>
            {currentStage}
          </div>
          <div style={{ width: 240, height: 4, background: "rgba(15,23,42,0.07)", borderRadius: 4, overflow: "hidden" }}>
            <motion.div style={{ height: "100%", background: "#1D6FE8", borderRadius: 4 }}
              animate={{ width: `${progressPct}%` }} transition={{ duration: 0.5 }} />
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "#5D6B7F", marginTop: 8 }}>
            {progressPct}% complete · stay on this tab
          </div>
        </>
      ) : (
        <>
          <div style={{
            width: 64, height: 64, borderRadius: 18,
            background: "rgba(29,111,232,0.08)", border: "1px solid rgba(29,111,232,0.18)",
            display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20,
          }}>
            <BarChart2 size={28} color="#1D6FE8" strokeWidth={1.5} />
          </div>
          <div style={{ fontFamily: "var(--font-display)", fontSize: 22, marginBottom: 8, color: "#0B1120" }}>
            No analysis yet
          </div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#5D6B7F", marginBottom: 24, maxWidth: 320 }}>
            Upload a pitch deck to see your AI investment dashboard with live risk scores, claim verification, and comparable deals.
          </div>
          <button onClick={() => navigate("/upload")} style={{
            display: "inline-flex", alignItems: "center", gap: 8,
            background: "#1D6FE8", color: "#fff", border: "none",
            borderRadius: 10, padding: "11px 22px", fontFamily: "var(--font-sans)",
            fontSize: 14, fontWeight: 600, cursor: "pointer",
            boxShadow: "0 2px 8px rgba(29,111,232,0.28)",
          }}>
            <Upload size={15} /> Upload a Deck
          </button>
        </>
      )}
    </div>
  );
};

const PastAnalyses = () => {
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const { loadSavedReport } = useApp();
  const navigate = useNavigate();

  useEffect(() => {
    api.listReports().then(setReports).catch(() => setReports([])).finally(() => setLoading(false));
  }, []);

  if (loading || !reports.length) return null;
  return (
    <div style={{ width: "min(620px, 100%)", marginTop: 28, textAlign: "left" }}>
      <div style={{
        fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-muted)",
        letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8,
      }}>
        Past analyses
      </div>
      <Stagger gap={0.04}>
        {reports.map((saved) => (
          <StaggerItem key={saved.report_id}>
            <Lift>
              <button
                type="button"
                className="db-past-row"
                onClick={async () => {
                  await loadSavedReport(saved.report_id);
                  navigate("/analysis");
                }}
              >
                <span className="db-past-name">
                  {saved.company}
                  {/* Reports that predate accounts belong to nobody and are
                      visible to everyone. Saying so is the difference between
                      a shared record and one the reader assumes is private. */}
                  {saved.shared && <span className="db-past-shared">shared</span>}
                </span>
                <span className="db-past-meta">
                  {Math.round(saved.final_score)}/100 · {saved.recommendation}
                </span>
              </button>
            </Lift>
          </StaggerItem>
        ))}
      </Stagger>
      <style>{`
        .db-past-row {
          width: 100%; display: flex; align-items: center; justify-content: space-between;
          gap: 12px; text-align: left; font-family: var(--font-sans);
          border: 1px solid var(--border); background: var(--surface);
          border-radius: 9px; margin-bottom: 6px; padding: 11px 13px; cursor: pointer;
          transition: border-color var(--dur-fast) var(--ease-out),
                      box-shadow var(--dur-base) var(--ease-out);
        }
        .db-past-row:hover { border-color: var(--border-strong); box-shadow: var(--shadow-raised); }
        .db-past-name {
          font-weight: 600; font-size: 13.5px; color: var(--text-primary);
          display: flex; align-items: center; gap: 8px; min-width: 0;
        }
        .db-past-shared {
          font-family: var(--font-mono); font-size: 8.5px; font-weight: 600;
          letter-spacing: 0.09em; text-transform: uppercase;
          color: var(--text-muted); background: var(--surface-2);
          border: 1px solid var(--border); border-radius: 20px; padding: 2px 7px;
        }
        .db-past-meta {
          font-family: var(--font-mono); font-size: 11.5px;
          color: var(--text-muted); white-space: nowrap;
        }
      `}</style>
    </div>
  );
};

// ─── DASHBOARD ────────────────────────────────────────────────────────────────

type ScoreHistoryPoint = { date: string; score: number; recommendation: string };

const Dashboard = () => {
  const { report, status, currentStage, progressPct } = useApp();
  const [scoreHistory, setScoreHistory] = useState<ScoreHistoryPoint[]>([]);

  // Real per-company score history (p2 on the Ship List) -- hook must run
  // unconditionally, before the early-return below, per the Rules of Hooks.
  useEffect(() => {
    if (!report?.company) {
      setScoreHistory([]);
      return;
    }
    fetch(`${import.meta.env.VITE_API_BASE_URL || "/api"}/companies/${encodeURIComponent(report.company)}/history`, { headers: authHeaders() })
      .then((res) => (res.ok ? res.json() : { history: [] }))
      .then((data) => setScoreHistory(data.history || []))
      .catch(() => setScoreHistory([]));
  }, [report?.company]);

  // If no report yet, show empty / analyzing state
  if (!report) return (
    <div className="db-root" style={{ fontFamily: "var(--font-sans)", color: "#0B1120", minHeight: "100vh", background: "#F0F2F5" }}>
      <div className="db-header" style={{ padding: "22px 32px 20px", background: "#fff", borderBottom: "1px solid rgba(15,23,42,0.08)", display: "flex", alignItems: "flex-end", justifyContent: "space-between", position: "relative", overflow: "hidden" }}>
        <div>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 9.5, color: "#5D6B7F", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>Dashboard</div>
          <h1 style={{ fontFamily: "var(--font-display)", fontSize: 28, fontWeight: 400, margin: 0, color: "#0B1120" }}>AI Investment Dashboard</h1>
        </div>
      </div>
      <EmptyDashboard />
      <div style={{ display: "flex", justifyContent: "center", padding: "0 24px 40px" }}><PastAnalyses /></div>
    </div>
  );

  // ── Derive live data from the real report ──────────────────────────────────
  const score = report.final_score;
  const riskValue = report.risk_signals_found
    ? Math.min(100, Math.round(report.risk_signals_found * 3.5 + 10))
    : Math.round(score * 0.7);

  const riskColor = riskValue >= 70 ? "#D93025" : riskValue >= 40 ? "#C47A0A" : "#0EA66A";
  const riskLabel = riskValue >= 70 ? "High Risk" : riskValue >= 40 ? "Moderate Risk" : "Low Risk";
  const scoreColor = score >= 75 ? "#0EA66A" : score >= 50 ? "#C47A0A" : "#D93025";

  // A `revenueM` value was computed here as
  //     (claims_supported / claims_verified) * 2.8
  // and labelled revenue in millions. That number is not revenue: it is a
  // claim-verification ratio multiplied by a constant nobody can source. It
  // was never rendered, so it misled no user, but it is exactly the kind of
  // plausible-looking figure this product must not manufacture. Revenue is
  // available honestly on `report.sections.financial_state` when the deck
  // states it; anything that wants to show revenue should read that and show
  // nothing when it is absent.

  // Real history once this company has been analyzed 2+ times
  // (GET /companies/{name}/history, backed by every persisted dd_reports
  // row for it) -- a single point still shows the honest "first analysis"
  // state below, same as before this was wired up.
  const hasHistory = scoreHistory.length >= 2;
  const trendData = scoreHistory.map((point) => ({
    name: formatDateShort(point.date),
    value: point.score,
  }));

  const metrics = [
    {
      label: "Overall Score", value: `${Math.round(score)} / 100`,
      sub: report.recommendation, icon: TrendingUp,
      color: scoreColor, bg: `${scoreColor}14`, border: `${scoreColor}30`, trend: null,
    },
    {
      label: "Claims Verified", value: `${report.claims_supported}/${report.claims_verified}`,
      sub: `${report.claims_refuted} refuted · ${report.claims_uncertain} uncertain`,
      icon: CheckCircle2, color: "#0EA66A", bg: "rgba(14,166,106,0.08)", border: "rgba(14,166,106,0.18)", trend: null,
    },
    {
      label: "Risk Score", value: `${riskValue} / 100`,
      sub: riskLabel, icon: Shield,
      color: riskColor, bg: `${riskColor}12`, border: `${riskColor}28`, trend: null,
    },
    {
      label: "Risk Signals", value: String(report.risk_signals_found),
      sub: "Detected across categories", icon: AlertCircle,
      color: "#C47A0A", bg: "rgba(196,122,10,0.08)", border: "rgba(196,122,10,0.18)", trend: null,
    },
  ];

  const bullSignals = report.positive_factors.slice(0, 4).map(f => ({
    label: f.length > 22 ? f.slice(0, 22) + "…" : f, value: "✓", dot: "#0EA66A", up: true as const
  }));
  const bearSignals = report.red_flags.slice(0, 4).map(f => ({
    label: f.length > 22 ? f.slice(0, 22) + "…" : f, value: "⚠", dot: "#D93025", up: false as const
  }));
  const signals = [...bullSignals, ...bearSignals];

  // Grounded in the actual counts of independently-detected positive factors
  // vs. red flags for this report — not a rescaling of the single final score.
  const totalConvictionSignals = report.positive_factors.length + report.red_flags.length;
  const bullScore = totalConvictionSignals
    ? Math.round((report.positive_factors.length / totalConvictionSignals) * 100)
    : 50;
  const bearScore = totalConvictionSignals
    ? Math.round((report.red_flags.length / totalConvictionSignals) * 100)
    : 50;

  const today = formatDate(new Date());
  const deckId = displayDeckId(report.company);

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
          --radius-sm: 8px;
          --radius-md: 12px;
          --radius-lg: 16px;
        }

        .db-root {
          font-family: var(--font-sans);
          color: var(--text-primary);
          min-height: 100vh;
          background: var(--bg);
          background-image:
            radial-gradient(ellipse 80% 60% at 10% -10%, rgba(29,111,232,0.05) 0%, transparent 60%),
            radial-gradient(ellipse 60% 40% at 90% 100%, rgba(14,166,106,0.04) 0%, transparent 50%);
        }

        .db-header {
          padding: 22px 32px 20px;
          background: var(--surface);
          border-bottom: 1px solid var(--border);
          display: flex;
          align-items: flex-end;
          justify-content: space-between;
          position: relative;
          overflow: hidden;
        }

        .db-header::before {
          content: '';
          position: absolute;
          top: 0; left: 0; right: 0;
          height: 2px;
          background: linear-gradient(90deg, var(--blue), var(--green), var(--blue));
          background-size: 200% 100%;
          animation: shimmer-line 4s linear infinite;
        }

        @keyframes shimmer-line {
          0% { background-position: 200% 0; }
          100% { background-position: -200% 0; }
        }

        .db-badge {
          display: inline-flex;
          align-items: center;
          gap: 7px;
          font-family: var(--font-mono);
          font-size: 9.5px;
          color: var(--green);
          background: rgba(14,166,106,0.09);
          border: 1px solid rgba(14,166,106,0.22);
          padding: 4px 12px;
          border-radius: 20px;
          letter-spacing: 0.07em;
          text-transform: uppercase;
          margin-bottom: 12px;
        }

        .live-dot {
          width: 5px; height: 5px;
          background: var(--green);
          border-radius: 50%;
          animation: live-pulse 1.8s ease-in-out infinite;
        }

        @keyframes live-pulse {
          0%, 100% { box-shadow: 0 0 0 0 rgba(14,166,106,0.5); }
          50% { box-shadow: 0 0 0 5px rgba(14,166,106,0); }
        }

        .db-title {
          font-family: var(--font-display);
          font-size: 28px;
          font-weight: 400;
          letter-spacing: -0.01em;
          color: var(--text-primary);
          margin: 0 0 5px;
          line-height: 1;
        }

        .db-subtitle {
          font-family: var(--font-mono);
          font-size: 10.5px;
          color: var(--text-muted);
        }

        .db-header-right {
          display: flex;
          align-items: flex-end;
          gap: 12px;
        }

        .deck-id-box {
          text-align: right;
        }

        .deck-id-label {
          font-family: var(--font-mono);
          font-size: 9px;
          color: var(--text-muted);
          letter-spacing: 0.12em;
          text-transform: uppercase;
          margin-bottom: 2px;
        }

        .deck-id-val {
          font-family: var(--font-mono);
          font-size: 13px;
          font-weight: 600;
          color: var(--blue);
        }

        .db-export-btn {
          display: inline-flex; align-items: center; gap: 7px;
          font-family: var(--font-mono); font-size: 11px;
          font-weight: 500; color: var(--text-secondary);
          background: var(--surface); border: 1px solid var(--border);
          padding: 8px 16px; border-radius: 8px; cursor: pointer;
          transition: all 0.15s ease; letter-spacing: 0.02em;
        }

        .db-export-btn:hover {
          background: var(--surface-2);
          border-color: var(--border-strong);
          color: var(--text-primary);
        }

        .metric-grid {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 12px;
          padding: 16px 24px 0;
        }

        .metric-card {
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: var(--radius-md);
          padding: 16px 18px;
          box-shadow: var(--shadow-sm);
          position: relative;
          overflow: hidden;
          cursor: default;
          transition: transform 0.2s ease, box-shadow 0.2s ease;
        }

        .metric-card:hover {
          transform: translateY(-2px);
          box-shadow: var(--shadow-md);
        }

        .metric-top-row {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
        }

        .metric-icon-wrap {
          width: 34px; height: 34px;
          border-radius: 9px;
          display: flex; align-items: center; justify-content: center;
        }

        .metric-trend {
          font-family: var(--font-mono);
          font-size: 9px; font-weight: 600;
          padding: 3px 8px; border-radius: 20px;
          letter-spacing: 0.06em;
        }

        .metric-label {
          font-family: var(--font-mono);
          font-size: 9.5px; color: var(--text-muted);
          letter-spacing: 0.1em; text-transform: uppercase;
          margin-bottom: 4px;
        }

        .metric-value {
          font-family: var(--font-display);
          font-size: 22px; font-weight: 400;
          letter-spacing: -0.01em; line-height: 1;
          margin-bottom: 8px;
        }

        .metric-bottom-row {
          display: flex; align-items: center; justify-content: space-between;
        }

        .metric-sub {
          font-family: var(--font-mono);
          font-size: 9.5px; color: var(--text-muted); max-width: 100px;
        }

        .main-grid {
          display: grid;
          grid-template-columns: 1fr 280px;
          gap: 14px;
          padding: 14px 24px 24px;
        }

        .left-col { display: flex; flex-direction: column; gap: 14px; }
        .right-col { display: flex; flex-direction: column; gap: 14px; }

        .panel {
          background: var(--surface);
          border-radius: var(--radius-md);
          border: 1px solid var(--border);
          box-shadow: var(--shadow-sm);
        }

        .panel-pad { padding: 20px 22px; }

        .chart-header {
          display: flex; align-items: flex-start;
          justify-content: space-between; margin-bottom: 18px;
        }

        .panel-title {
          font-size: 14px; font-weight: 600; color: var(--text-primary);
          letter-spacing: -0.02em; margin-bottom: 2px;
        }

        .panel-sub {
          font-family: var(--font-mono);
          font-size: 9.5px; color: var(--text-muted);
        }

        .time-filters { display: flex; gap: 4px; }

        .time-btn {
          font-family: var(--font-mono);
          font-size: 10px; padding: 4px 10px; border-radius: 6px;
          border: 1px solid transparent; cursor: pointer; transition: all 0.14s ease;
          background: transparent; color: var(--text-muted);
        }

        .time-btn:hover { background: var(--surface-2); color: var(--text-primary); }

        .time-btn-active {
          background: rgba(29,111,232,0.08);
          border-color: rgba(29,111,232,0.22);
          color: var(--blue); font-weight: 600;
        }

        .stats-row {
          display: grid; grid-template-columns: repeat(4, 1fr);
          gap: 10px; margin-top: 16px; padding-top: 14px;
          border-top: 1px solid var(--border);
        }

        .stat-item { text-align: center; }

        .stat-label {
          font-family: var(--font-mono);
          font-size: 9px; color: var(--text-muted);
          text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 3px;
        }

        .stat-value {
          font-family: var(--font-mono);
          font-size: 13px; font-weight: 600; color: var(--text-primary);
        }

        .slabel {
          font-family: var(--font-mono);
          font-size: 9.5px; color: var(--text-muted);
          text-transform: uppercase; letter-spacing: 0.12em;
          margin-bottom: 12px;
        }

        .conviction-row {
          display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px;
        }

        .conviction-side {
          border-radius: 9px; padding: 12px;
        }

        .conviction-label {
          font-family: var(--font-mono);
          font-size: 9px; font-weight: 600;
          letter-spacing: 0.1em; text-transform: uppercase; margin-bottom: 6px;
        }

        .conviction-score {
          font-family: var(--font-display);
          font-size: 28px; margin-bottom: 8px; line-height: 1;
        }

        .conviction-track {
          height: 4px; border-radius: 4px; overflow: hidden;
        }

        .conviction-fill {
          height: 100%; border-radius: 4px;
          transition: width 1.2s cubic-bezier(0.22,1,0.36,1);
        }

        .comp-row {
          display: flex; align-items: center; gap: 10px;
          padding: 10px 0; border-bottom: 1px solid var(--border);
        }
        .comp-row:last-of-type { border-bottom: none; }
        .comp-color-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
        .comp-info { flex: 1; }
        .comp-name { font-size: 12.5px; font-weight: 500; color: var(--text-primary); letter-spacing: -0.01em; }
        .comp-meta { font-family: var(--font-mono); font-size: 9px; color: var(--text-muted); margin-top: 1px; }
        .comp-raise { font-family: var(--font-mono); font-size: 12px; font-weight: 600; color: var(--text-primary); }
        .comp-score-chip {
          font-family: var(--font-mono); font-size: 11px;
          font-weight: 700; padding: 4px 10px; border-radius: 7px;
          min-width: 36px; text-align: center;
        }

        .gauge-section { padding: 18px 22px 14px; }
        .gauge-value-wrap { text-align: center; margin-top: -28px; }
        .gauge-big {
          font-family: var(--font-display);
          font-size: 38px; font-weight: 400;
          color: var(--text-primary); line-height: 1; margin-bottom: 2px;
        }
        .gauge-label { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); }
        .gauge-scale { display: flex; justify-content: space-between; margin-top: 6px; }
        .gauge-scale-label { font-family: var(--font-mono); font-size: 8.5px; color: var(--text-muted); }

        .runway-widget {
          padding: 0 22px 18px;
          border-top: 1px solid var(--border);
          margin-top: 14px; padding-top: 14px;
        }

        .runway-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
        .runway-label { font-family: var(--font-mono); font-size: 10px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.1em; }
        .runway-months { font-family: var(--font-mono); font-size: 13px; font-weight: 600; color: var(--text-primary); }
        .runway-track { height: 6px; background: rgba(15,23,42,0.07); border-radius: 6px; overflow: hidden; margin-bottom: 7px; }
        .runway-fill { height: 100%; width: 58%; background: linear-gradient(90deg, #0EA66A, #1D6FE8); border-radius: 6px; }
        .runway-sub { display: flex; justify-content: space-between; font-family: var(--font-mono); font-size: 9.5px; color: var(--text-muted); }

        .signals-section { padding: 18px 20px; }
        .signal-row {
          display: flex; align-items: center; justify-content: space-between;
          padding: 8px 0; border-bottom: 1px solid var(--border);
        }
        .signal-row:last-child { border-bottom: none; }
        .signal-left { display: flex; align-items: center; gap: 8px; }
        .signal-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
        .signal-name { font-family: var(--font-mono); font-size: 10.5px; color: var(--text-secondary); }
        .signal-val-wrap { display: flex; align-items: center; gap: 5px; }
        .signal-value { font-family: var(--font-mono); font-size: 11px; font-weight: 600; color: var(--text-primary); }
      `}</style>

      <div className="db-root">
        {/* HEADER */}
        <div className="db-header">
          <div>
            <div className="db-badge">
              <div className="live-dot" />
              Intelligence Report · Live
            </div>
            <h1 className="db-title">AI Investment Dashboard</h1>
            <p className="db-subtitle">{report.company} · Analyzed {today}</p>
          </div>
          <div className="db-header-right">
            <div className="deck-id-box">
              <div className="deck-id-label">Deck ID</div>
              <div className="deck-id-val">{deckId}</div>
            </div>
            <button className="db-export-btn">
              <Download size={13} strokeWidth={2} />
              Export Memo
            </button>
          </div>
        </div>

        {/* METRICS */}
        <div className="metric-grid">
          {metrics.map((m, i) => {
            const Icon = m.icon;
            return (
              <motion.div
                key={i}
                className="metric-card"
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: i * 0.08, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              >
                <div className="metric-top-row">
                  <div className="metric-icon-wrap" style={{ background: m.bg, border: `1px solid ${m.border}` }}>
                    <Icon size={15} color={m.color} strokeWidth={1.8} />
                  </div>
                  {m.trend && (
                    <div className="metric-trend" style={{ color: m.color, background: m.bg, border: `1px solid ${m.border}` }}>
                      {m.trend}
                    </div>
                  )}
                </div>
                <div className="metric-label">{m.label}</div>
                <div className="metric-value" style={{ color: m.color }}>{m.value}</div>
                <div className="metric-bottom-row">
                  <span className="metric-sub">{m.sub}</span>
                </div>
              </motion.div>
            );
          })}
        </div>

        {/* MAIN GRID */}
        <div className="main-grid">
          <div className="left-col">
            {/* SCORE TREND CHART */}
            <motion.div
              className="panel panel-pad"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.36, duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            >
              <div className="chart-header">
                <div>
                  <div className="panel-title">Investment Score</div>
                  <div className="panel-sub">
                    {hasHistory
                      ? "Derived from verified claims · composite index"
                      : "First analysis on file for this company"}
                  </div>
                </div>
              </div>

              {hasHistory ? (
                <ResponsiveContainer width="100%" height={220}>
                  <AreaChart data={trendData} margin={{ top: 4, right: 0, left: -8, bottom: 0 }}>
                    <defs>
                      <linearGradient id="arrGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#1D6FE8" stopOpacity={0.14} />
                        <stop offset="100%" stopColor="#1D6FE8" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid stroke="rgba(15,23,42,0.05)" vertical={false} />
                    <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fill: "#5D6B7F", fontFamily: "var(--font-mono)", fontSize: 10 }} />
                    <YAxis axisLine={false} tickLine={false} tick={{ fill: "#5D6B7F", fontFamily: "var(--font-mono)", fontSize: 10 }} />
                    <Tooltip content={<ChartTooltip />} cursor={{ stroke: "rgba(15,23,42,0.08)", strokeWidth: 1 }} />
                    <Area type="monotone" dataKey="value" stroke="#1D6FE8" strokeWidth={2.5} fill="url(#arrGrad)" dot={false} isAnimationActive animationDuration={1400} animationEasing="ease-out" />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div style={{
                  height: 220, display: "flex", flexDirection: "column",
                  alignItems: "center", justifyContent: "center", gap: 6,
                  border: "1px dashed rgba(15,23,42,0.12)", borderRadius: 12,
                  background: "rgba(15,23,42,0.015)",
                }}>
                  <div style={{ fontFamily: "var(--font-display)", fontSize: 40, color: scoreColor }}>
                    {Math.round(score)}
                  </div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 10.5, color: "#5D6B7F", textAlign: "center", maxWidth: 260 }}>
                    Today&rsquo;s score. Re-run analysis on this company later to build a real trend line here.
                  </div>
                </div>
              )}

              <div className="stats-row">
                {[
                  { label: "Verified Claims", value: `${report.claims_supported}/${report.claims_verified}`, color: "#0EA66A" },
                  { label: "Refuted", value: String(report.claims_refuted), color: "#D93025" },
                  { label: "Risk Signals", value: String(report.risk_signals_found), color: riskColor },
                  { label: "Final Score", value: `${Math.round(score)}/100`, color: scoreColor },
                ].map((s, i) => (
                  <div key={i} className="stat-item">
                    <div className="stat-label">{s.label}</div>
                    <div className="stat-value" style={{ color: s.color }}>{s.value}</div>
                  </div>
                ))}
              </div>
            </motion.div>

            {/* BULL/BEAR + KEY CONCERNS ROW */}
            <motion.div
              style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.48, duration: 0.4 }}
            >
              {/* BULL BEAR CONVICTION */}
              <div className="panel panel-pad">
                <div className="slabel">Bull / Bear Conviction</div>
                <div className="conviction-row">
                  <div className="conviction-side" style={{ background: "rgba(14,166,106,0.06)", border: "1px solid rgba(14,166,106,0.15)" }}>
                    <div className="conviction-label" style={{ color: "#0EA66A" }}>▲ Bull</div>
                    <div className="conviction-score" style={{ color: "#0EA66A" }}>{Math.min(bullScore, 100)}</div>
                    <div className="conviction-track" style={{ background: "rgba(14,166,106,0.12)" }}>
                      <div className="conviction-fill" style={{ background: "#0EA66A", width: `${Math.min(bullScore, 100)}%` }} />
                    </div>
                  </div>
                  <div className="conviction-side" style={{ background: "rgba(217,48,37,0.05)", border: "1px solid rgba(217,48,37,0.14)" }}>
                    <div className="conviction-label" style={{ color: "#D93025" }}>▼ Bear</div>
                    <div className="conviction-score" style={{ color: "#D93025" }}>{bearScore}</div>
                    <div className="conviction-track" style={{ background: "rgba(217,48,37,0.10)" }}>
                      <div className="conviction-fill" style={{ background: "#D93025", width: `${bearScore}%` }} />
                    </div>
                  </div>
                </div>
                <div style={{ padding: "12px", background: "rgba(29,111,232,0.04)", borderRadius: 9, border: "1px solid rgba(29,111,232,0.12)" }}>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 9, color: "#5D6B7F", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>Verdict</div>
                  <div style={{ fontSize: 13, fontWeight: 700, color: "#0B1120", letterSpacing: "-0.02em" }}>{report.recommendation}</div>
                  <div style={{ fontFamily: "var(--font-mono)", fontSize: 9.5, color: "#4A5568", marginTop: 3 }}>
                    {report.key_concerns[0] || "Verify all claims before closing"}
                  </div>
                </div>
              </div>

              {/* KEY CONCERNS */}
              <div className="panel panel-pad">
                <div className="slabel">Key Concerns</div>
                {(report.key_concerns.length > 0 ? report.key_concerns : ["No major concerns detected"]).slice(0, 4).map((concern, i) => (
                  <div key={i} className="comp-row">
                    <div className="comp-color-dot" style={{ background: i === 0 ? "#D93025" : i === 1 ? "#C47A0A" : "#1D6FE8" }} />
                    <div className="comp-info">
                      <div className="comp-name" style={{ fontSize: 12 }}>{concern}</div>
                    </div>
                  </div>
                ))}
              </div>
            </motion.div>
          </div>

          {/* RIGHT COLUMN */}
          <motion.div
            className="right-col"
            initial={{ opacity: 0, x: 10 }}
            animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.44, duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
          >
            {/* GAUGE */}
            <div className="panel">
              <div className="gauge-section">
                <div className="slabel">Risk Assessment</div>
                <svg width="100%" height="114" viewBox="0 0 220 114" style={{ display: "block", overflow: "visible" }} aria-hidden="true">
                  <defs>
                    <linearGradient id="gaugeGrad" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#0EA66A" />
                      <stop offset="48%" stopColor="#C47A0A" />
                      <stop offset="100%" stopColor="#D93025" />
                    </linearGradient>
                  </defs>
                  <path d="M 22 82 A 88 88 0 0 1 198 82" fill="none" stroke="rgba(15,23,42,0.07)" strokeWidth="8" strokeLinecap="round" />
                  <path d="M 22 82 A 88 88 0 0 1 198 82" fill="none" stroke="url(#gaugeGrad)" strokeWidth="10" strokeLinecap="round"
                    strokeDasharray={`${(riskValue / 100) * 276} 276`}
                    style={{ transition: "stroke-dasharray 1.4s cubic-bezier(0.22,1,0.36,1)" }} />
                </svg>
                <div className="gauge-value-wrap">
                  <div className="gauge-big" style={{ color: riskColor }}>{riskValue}</div>
                  <div className="gauge-label">{riskLabel} · out of 100</div>
                </div>
                <div className="gauge-scale">
                  <span className="gauge-scale-label">Low</span>
                  <span className="gauge-scale-label">Moderate</span>
                  <span className="gauge-scale-label">High</span>
                </div>
              </div>

              <div className="runway-widget">
                <div className="runway-header">
                  <span className="runway-label">Risk Level</span>
                  <span className="runway-months" style={{ color: riskColor }}>{report.risk_level}</span>
                </div>
                <div className="runway-track">
                  <div className="runway-fill" style={{ width: `${riskValue}%`, background: `linear-gradient(90deg, #0EA66A, ${riskColor})` }} />
                </div>
                <div className="runway-sub">
                  <span>{report.risk_signals_found} signals detected</span>
                  <span>{report.claims_verified} claims checked</span>
                </div>
              </div>
            </div>

            {/* SIGNALS */}
            <div className="panel signals-section">
              <div className="slabel">Key Signals</div>
              {signals.length > 0 ? signals.map((s, i) => (
                <motion.div
                  key={i}
                  className="signal-row"
                  initial={{ opacity: 0, x: 6 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.5 + i * 0.05, duration: 0.3 }}
                >
                  <div className="signal-left">
                    <div className="signal-dot" style={{ background: s.dot }} />
                    <span className="signal-name">{s.label}</span>
                  </div>
                  <div className="signal-val-wrap">
                    <span className="signal-value">{s.value}</span>
                    {s.up === true && <TrendingUp size={10} color="#0EA66A" />}
                    {s.up === false && <TrendingDown size={10} color="#D93025" />}
                  </div>
                </motion.div>
              )) : (
                <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "#5D6B7F", textAlign: "center", padding: "16px 0" }}>
                  No signals detected
                </div>
              )}
            </div>
          </motion.div>
        </div>
      </div>
    </>
  );
};

export default Dashboard;
