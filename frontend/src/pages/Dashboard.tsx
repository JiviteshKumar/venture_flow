import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { ArrowUpRight, Loader2, Search, Upload } from "lucide-react";
import { useApp } from "../context/AppContext";
import { api, ReportSummary } from "../services/apiClient";
import { formatDate } from "../utils/format";
import { useElapsedSeconds, formatElapsed } from "../hooks/useElapsed";
import { GrowBar } from "../components/ui/Motion";
import { Magnetic, Reveal, SplitWords } from "../components/ui/scroll";
import { Badge, BadgeStyles, Tooltip, type Tone } from "../components/ui/Surface";
import { ScoreDistribution } from "../components/charts/Charts";
import {
  Button, ButtonStyles, Card, EmptyState, Label, Skeleton, SkeletonStyles,
} from "../components/ui/primitives";

/**
 * The command centre.
 *
 * WHAT THIS PAGE IS
 *
 * The deal table: every analysis on file with the four things that decide
 * whether it needs attention -- what it scored, what the pipeline made of its
 * risk, how much of the deck was actually read, and what the verdict was. It
 * is a working surface, so it is dense, sortable, searchable and keyboard
 * navigable, and it is the one screen in this product that is a table on
 * purpose.
 *
 * WHAT IT IS NOT
 *
 * It is not a second rendering of the current report. It used to be exactly
 * that -- the same score, claim counts, risk level, bull/bear split and key
 * concerns the report screen shows, drawn a few pixels away with different
 * widgets. Two pages stating the same findings in two visual languages is
 * worse than one page stating them once.
 *
 * WHY "NEEDS ATTENTION" IS NOT A MODEL
 *
 * The flag is a rule stated on screen, not a score: risk came back HIGH, or
 * under half the deck reached a structured field. Both are facts already in
 * the row. Inventing a weighted "attention score" would add a number nothing
 * measures to a product whose argument is that it does not do that.
 */

// ── Row helpers ──────────────────────────────────────────────────────────────

const scoreTone = (score: number): Tone =>
  score >= 70 ? "verified" : score >= 45 ? "caution" : "critical";

const toneVar = (t: Tone) =>
  t === "verified" ? "var(--verified)"
    : t === "caution" ? "var(--caution)"
      : t === "critical" ? "var(--critical)"
        : "var(--text-3)";

const riskTone = (level?: string | null): Tone => {
  const r = (level || "").toUpperCase();
  if (r === "HIGH") return "critical";
  if (r === "MEDIUM" || r === "MODERATE") return "caution";
  if (r === "LOW") return "verified";
  return "neutral";
};

const riskLabel = (level?: string | null) => {
  const r = (level || "").toUpperCase();
  if (r === "HIGH") return "High";
  if (r === "MEDIUM" || r === "MODERATE") return "Medium";
  if (r === "LOW") return "Low";
  if (r === "UNKNOWN") return "Unknown";
  return "—";
};

const verdictTone = (recommendation: string): Tone => {
  const r = recommendation.toUpperCase();
  if (r.includes("INVEST") && !r.includes("NOT")) return "verified";
  if (r.includes("PASS")) return "critical";
  return "caution";
};

/** Twenty rows reading "NEEDS MORE DILIGENCE" is twenty rows of noise. */
const verdictShort = (recommendation: string) => {
  const r = recommendation.toUpperCase();
  if (r.includes("NEEDS MORE DILIGENCE")) return "Diligence";
  if (r.includes("INVEST") && !r.includes("NOT")) return "Invest";
  if (r.includes("PASS")) return "Pass";
  return recommendation.charAt(0) + recommendation.slice(1).toLowerCase();
};

/** The stated rule, in one place, so the table and the filter cannot diverge. */
const needsAttention = (r: ReportSummary) =>
  (r.risk_level || "").toUpperCase() === "HIGH"
  || (typeof r.coverage_pct === "number" && r.coverage_pct < 50);

function ScoreMark({ score }: { score: number }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "baseline", gap: 5 }}>
      <span className="vf-figure" style={{ fontSize: 22, color: toneVar(scoreTone(score)) }}>
        {Math.round(score)}
      </span>
      <span style={{ fontSize: 11, color: "var(--text-faint)" }}>/100</span>
    </span>
  );
}

// ── In-flight run ────────────────────────────────────────────────────────────

function RunningStrip() {
  const { currentStage, progressPct, companyName, startedAt } = useApp();
  const elapsed = useElapsedSeconds(startedAt);
  return (
    <Card padding={18} style={{ marginBottom: 20, borderColor: "var(--accent-line)" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <motion.span
          animate={{ rotate: 360 }}
          transition={{ repeat: Infinity, duration: 1.1, ease: "linear" }}
          style={{ display: "flex", color: "var(--accent)" }}
        >
          <Loader2 size={16} />
        </motion.span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>Analysing {companyName || "your deck"}</div>
          <div style={{ fontSize: 12.5, color: "var(--text-3)" }}>{currentStage}</div>
        </div>
        <span className="vf-num" style={{ marginLeft: "auto", fontSize: 14, color: "var(--text-2)" }}>
          {formatElapsed(elapsed)}
        </span>
      </div>
      <GrowBar pct={progressPct} color="var(--accent)" height={4} />
    </Card>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

type SortKey = "recent" | "score" | "risk" | "company";

const Dashboard = () => {
  const navigate = useNavigate();
  const { report, status, loadSavedReport } = useApp();
  const [reports, setReports] = useState<ReportSummary[] | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("recent");
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [opening, setOpening] = useState<string | null>(null);

  const running = status === "uploading" || status === "analyzing";

  useEffect(() => {
    let live = true;
    api.listReports()
      .then((rows) => live && setReports(rows))
      .catch(() => live && setReports([]));
    return () => { live = false; };
  }, []);

  const visible = useMemo(() => {
    const rows = [...(reports || [])];
    const needle = query.trim().toLowerCase();
    const filtered = rows.filter((r) => {
      if (onlyAttention && !needsAttention(r)) return false;
      if (!needle) return true;
      return r.company.toLowerCase().includes(needle)
        || r.recommendation.toLowerCase().includes(needle);
    });
    const riskRank = (r?: string | null) => {
      const v = (r || "").toUpperCase();
      return v === "HIGH" ? 3 : v === "MEDIUM" || v === "MODERATE" ? 2 : v === "LOW" ? 1 : 0;
    };
    filtered.sort((a, b) => {
      if (sort === "score") return b.final_score - a.final_score;
      if (sort === "company") return a.company.localeCompare(b.company);
      if (sort === "risk") return riskRank(b.risk_level) - riskRank(a.risk_level);
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
    return filtered;
  }, [reports, query, sort, onlyAttention]);

  /** Counts over what is on file. No modelling, no weighting -- arithmetic. */
  const summary = useMemo(() => {
    if (!reports?.length) return null;
    const scores = reports.map((r) => r.final_score).sort((a, b) => a - b);
    const median = scores.length % 2
      ? scores[(scores.length - 1) / 2]
      : (scores[scores.length / 2 - 1] + scores[scores.length / 2]) / 2;
    const coverages = reports
      .map((r) => r.coverage_pct)
      .filter((c): c is number => typeof c === "number")
      .sort((a, b) => a - b);
    return {
      count: reports.length,
      companies: new Set(reports.map((r) => r.company.toLowerCase())).size,
      median,
      attention: reports.filter(needsAttention).length,
      medianCoverage: coverages.length ? coverages[Math.floor(coverages.length / 2)] : null,
      claimsChecked: reports.reduce((n, r) => n + (r.claims_verified ?? 0), 0),
      claimsSupported: reports.reduce((n, r) => n + (r.claims_supported ?? 0), 0),
      signals: reports.reduce((n, r) => n + (r.risk_signals_found ?? 0), 0),
    };
  }, [reports]);

  const open = async (reportId: string) => {
    setOpening(reportId);
    try {
      await loadSavedReport(reportId);
      navigate("/analysis");
    } finally {
      setOpening(null);
    }
  };

  const allShared = Boolean(reports?.length) && reports!.every((r) => r.shared);

  return (
    <div className="db-root">
      <ButtonStyles />
      <SkeletonStyles />
      <BadgeStyles />
      <style>{`
        .db-toolbar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 14px; }
        .db-search {
          width: 100%; padding: 9px 12px 9px 34px; font: inherit; font-size: var(--t-small);
          background: var(--surface); border: 1px solid var(--line);
          border-radius: var(--r-sm); color: var(--text);
          transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
        }
        .db-search::placeholder { color: var(--text-faint); }
        .db-search:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-quiet); }

        .db-seg { display: inline-flex; background: var(--surface-2); border: 1px solid var(--line); border-radius: var(--r-sm); padding: 2px; }
        .db-seg button {
          font: inherit; font-size: var(--t-micro); font-weight: 500; padding: 6px 11px;
          border: none; background: transparent; color: var(--text-3);
          border-radius: 6px; cursor: pointer;
          transition: color var(--dur-fast) var(--ease-out), background var(--dur-fast) var(--ease-out);
        }
        .db-seg button:hover { color: var(--text); }
        .db-seg button[aria-pressed="true"] {
          background: var(--surface); color: var(--text); font-weight: 600; box-shadow: var(--e-1);
        }

        /* The deal table. A grid rather than <table>: every row is one button,
           which makes the whole row a target and keeps keyboard order to one
           stop per deal instead of one per cell. */
        .db-table { border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden; background: var(--surface); }
        .db-head, .db-row {
          display: grid;
          grid-template-columns: minmax(0, 2.1fr) 96px 108px 150px 116px 28px;
          align-items: center; gap: 14px;
          padding: 0 18px;
        }
        .db-head { height: 40px; background: var(--surface-2); border-bottom: 1px solid var(--line); }
        .db-row {
          width: 100%; height: 64px; text-align: left; font: inherit; cursor: pointer;
          background: transparent; border: none; border-bottom: 1px solid var(--line);
          transition: background var(--dur-fast) var(--ease-out);
        }
        .db-row:last-child { border-bottom: none; }
        .db-row:hover { background: var(--surface-2); }
        .db-row:hover .db-go { color: var(--accent); transform: translateX(2px); }
        .db-row[data-attention="true"] { box-shadow: inset 3px 0 0 var(--caution); }
        .db-go { color: var(--text-faint); transition: color var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out); }
        .db-company { display: block; font-size: var(--t-body); font-weight: 600; letter-spacing: -0.01em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .db-when { display: block; font-size: var(--t-micro); color: var(--text-3); margin-top: 2px; }

        /* Coverage as a bar: the eye compares lengths faster than it compares
           two-digit percentages down a column. */
        .db-cov { display: flex; align-items: center; gap: 9px; }
        .db-cov-track { flex: 1; height: 4px; border-radius: 4px; background: var(--surface-3); overflow: hidden; }
        .db-cov-fill { display: block; height: 100%; border-radius: 4px; }
        .db-cov-num { font-size: var(--t-micro); color: var(--text-3); min-width: 32px; text-align: right; }

        @media (max-width: 1080px) {
          .db-head, .db-row { grid-template-columns: minmax(0, 2fr) 88px 104px 112px 28px; }
          .db-col-cov { display: none; }
        }
        @media (max-width: 760px) {
          .db-head { display: none; }
          .db-row { grid-template-columns: minmax(0, 1fr) auto auto; height: auto; padding: 14px 16px; gap: 12px; }
          .db-col-risk { display: none; }
        }
      `}</style>

      <div className="vf-page">
        <Reveal>
          <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: 20, flexWrap: "wrap", marginBottom: 30 }}>
            <div>
              <Label style={{ marginBottom: 10 }}>Investment intelligence</Label>
              <h1 className="vf-lg" style={{ margin: 0 }}>
                <SplitWords text="VentureFlow" />
              </h1>
            </div>
            <Magnetic>
              <Button variant="primary" size="lg" icon={<Upload size={16} />} data-cursor="Upload" onClick={() => navigate("/upload")}>
                New analysis
              </Button>
            </Magnetic>
          </div>
        </Reveal>

        {running && <RunningStrip />}

        {summary && (
          <Reveal delay={0.05}>
            <div
              className="vf-grid-4"
              style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 26 }}
            >
              <Card padding="18px 20px">
                <Label style={{ marginBottom: 8 }}>Analyses on file</Label>
                <div className="vf-figure" style={{ fontSize: 30 }}>{summary.count}</div>
                <div style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 5 }}>
                  across {summary.companies} {summary.companies === 1 ? "company" : "companies"}
                </div>
              </Card>

              <Card padding="18px 20px">
                <Label style={{ marginBottom: 8 }}>Median score</Label>
                <div className="vf-figure" style={{ fontSize: 30, color: toneVar(scoreTone(summary.median)) }}>
                  {Math.round(summary.median)}
                </div>
                <div style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 5 }}>
                  the comparable population sits at 49
                </div>
              </Card>

              <Card padding="18px 20px">
                <Label style={{ marginBottom: 8 }}>Median deck read</Label>
                <div className="vf-figure" style={{ fontSize: 30 }}>
                  {summary.medianCoverage === null ? "—" : `${Math.round(summary.medianCoverage)}%`}
                </div>
                <div style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 5 }}>
                  {summary.medianCoverage === null
                    ? "not recorded on these reports"
                    : "of each deck reached a structured field"}
                </div>
              </Card>

              <Card padding="18px 20px" style={summary.attention ? { borderColor: "var(--caution-line)" } : undefined}>
                <Label style={{ marginBottom: 8 }}>Needs attention</Label>
                <div className="vf-figure" style={{ fontSize: 30, color: summary.attention ? "var(--caution)" : undefined }}>
                  {summary.attention}
                </div>
                <div style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 5 }}>
                  high risk, or under half the deck read
                </div>
              </Card>
            </div>
          </Reveal>
        )}

        {summary && reports && reports.length > 2 && (
          <Reveal delay={0.08}>
            <Card padding="20px 22px" style={{ marginBottom: 26 }}>
              <ScoreDistribution scores={reports.map((r) => r.final_score)} />
            </Card>
          </Reveal>
        )}

        {reports && reports.length > 0 && (
          <div className="db-toolbar">
            <div style={{ position: "relative", flex: "1 1 240px", maxWidth: 320 }}>
              <Search size={15} style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-faint)" }} aria-hidden="true" />
              <input
                className="db-search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search company or verdict"
                aria-label="Search analyses"
              />
            </div>
            <div className="db-seg" role="group" aria-label="Sort deals">
              {([["recent", "Recent"], ["score", "Score"], ["risk", "Risk"], ["company", "A–Z"]] as [SortKey, string][]).map(([key, label]) => (
                <button key={key} aria-pressed={sort === key} onClick={() => setSort(key)}>{label}</button>
              ))}
            </div>
            {summary && summary.attention > 0 && (
              <div className="db-seg">
                <button aria-pressed={onlyAttention} onClick={() => setOnlyAttention((v) => !v)}>
                  Needs attention · {summary.attention}
                </button>
              </div>
            )}
          </div>
        )}

        {reports === null ? (
          <Card padding={0}>
            {[0, 1, 2, 3, 4].map((i) => (
              <div
                key={i}
                style={{
                  display: "flex", alignItems: "center", gap: 16, padding: 18,
                  borderBottom: i < 4 ? "1px solid var(--line)" : undefined,
                }}
              >
                <Skeleton height={13} width={`${28 - i * 2}%`} />
                <Skeleton height={13} width={52} style={{ marginLeft: "auto" }} />
                <Skeleton height={13} width={64} />
                <Skeleton height={13} width={90} />
              </div>
            ))}
          </Card>
        ) : visible.length === 0 ? (
          <Card padding={0}>
            <EmptyState
              icon={<Upload size={20} />}
              title={reports.length ? "Nothing matches" : "No analyses yet"}
              body={
                reports.length
                  ? "No deal matches that filter."
                  : "Upload a pitch deck. VentureFlow will extract its claims, check them against live sources, and say plainly what it could not establish."
              }
              action={
                reports.length ? (
                  <Button onClick={() => { setQuery(""); setOnlyAttention(false); }}>Clear filters</Button>
                ) : (
                  <Button variant="primary" icon={<Upload size={15} />} data-cursor="Upload" onClick={() => navigate("/upload")}>
                    New analysis
                  </Button>
                )
              }
            />
          </Card>
        ) : (
          <>
            <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 10, flexWrap: "wrap" }}>
              <Label>{visible.length} {visible.length === 1 ? "deal" : "deals"}</Label>
              {allShared && (
                <span style={{ fontSize: 12.5, color: "var(--text-3)" }}>
                  These predate accounts, so they have no owner and are visible to anyone who can reach this deployment.
                </span>
              )}
            </div>

            <div className="db-table">
              <div className="db-head" aria-hidden="true">
                <span className="vf-label">Company</span>
                <span className="vf-label">Score</span>
                <span className="vf-label db-col-risk">Risk</span>
                <span className="vf-label db-col-cov">Deck read</span>
                <span className="vf-label">Verdict</span>
                <span />
              </div>

              {visible.map((r) => {
                const cov = r.coverage_pct;
                const covTone: Tone = typeof cov !== "number" ? "neutral"
                  : cov >= 75 ? "verified" : cov >= 50 ? "caution" : "critical";
                return (
                  <button
                    key={r.report_id}
                    className="db-row"
                    data-attention={needsAttention(r)}
                    data-cursor="Open"
                    onClick={() => open(r.report_id)}
                    disabled={opening !== null}
                    aria-busy={opening === r.report_id}
                  >
                    <span style={{ minWidth: 0 }}>
                      <span className="db-company">{r.company}</span>
                      <span className="db-when">{formatDate(r.created_at)}</span>
                    </span>

                    <ScoreMark score={r.final_score} />

                    <span className="db-col-risk">
                      <Badge tone={riskTone(r.risk_level)} size="sm" dot>
                        {riskLabel(r.risk_level)}
                      </Badge>
                    </span>

                    <span className="db-col-cov">
                      {typeof cov === "number" ? (
                        <Tooltip label={`${Math.round(cov)}% of this deck reached a structured field`}>
                          <span className="db-cov" style={{ width: 132 }}>
                            <span className="db-cov-track">
                              <span
                                className="db-cov-fill"
                                style={{ width: `${Math.max(2, Math.min(100, cov))}%`, background: toneVar(covTone) }}
                              />
                            </span>
                            <span className="db-cov-num vf-num">{Math.round(cov)}%</span>
                          </span>
                        </Tooltip>
                      ) : (
                        <span className="db-cov-num">—</span>
                      )}
                    </span>

                    <span>
                      <Badge tone={verdictTone(r.recommendation)} size="sm" title={r.recommendation}>
                        {verdictShort(r.recommendation)}
                      </Badge>
                    </span>

                    <span style={{ display: "flex", justifyContent: "flex-end" }}>
                      {opening === r.report_id ? (
                        <motion.span
                          animate={{ rotate: 360 }}
                          transition={{ repeat: Infinity, duration: 1, ease: "linear" }}
                          style={{ display: "flex", color: "var(--accent)" }}
                        >
                          <Loader2 size={15} />
                        </motion.span>
                      ) : (
                        <ArrowUpRight size={16} className="db-go" />
                      )}
                    </span>
                  </button>
                );
              })}
            </div>

            {summary && (summary.claimsChecked > 0 || summary.signals > 0) && (
              <div
                style={{
                  display: "flex", gap: 28, flexWrap: "wrap", marginTop: 22,
                  paddingTop: 18, borderTop: "1px solid var(--line)",
                }}
              >
                <span style={{ fontSize: 13, color: "var(--text-3)" }}>
                  <b className="vf-num" style={{ color: "var(--text)", fontWeight: 600 }}>{summary.claimsSupported}</b>
                  {" of "}
                  <b className="vf-num" style={{ color: "var(--text)", fontWeight: 600 }}>{summary.claimsChecked}</b>
                  {" checked claims corroborated"}
                </span>
                <span style={{ fontSize: 13, color: "var(--text-3)" }}>
                  <b className="vf-num" style={{ color: "var(--text)", fontWeight: 600 }}>{summary.signals}</b>
                  {" risk signals detected across these decks"}
                </span>
                {report && (
                  <button
                    onClick={() => navigate("/analysis")}
                    data-cursor="Open"
                    style={{
                      marginLeft: "auto", font: "inherit", fontSize: 13, fontWeight: 600,
                      background: "none", border: "none", color: "var(--accent)", cursor: "pointer",
                    }}
                  >
                    Back to {report.company} →
                  </button>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default Dashboard;
