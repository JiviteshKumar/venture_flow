import { ArrowDown, ArrowLeft, Download, Loader2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { type DeckPage } from "./DeckSculpture";
import Constellation, { type ComparablePoint } from "./Constellation";
import { Act, beat, easeOut, Reveal, SplitWords, ActStyles } from "../ui/scroll";

/**
 * The opening of the report, as a sequence of scenes.
 *
 * WHY IT IS BUILT THIS WAY
 *
 * A report of this kind has four things to say before any detail: whose deck
 * this is, how much of it we could read, what the number is, and what the
 * number is measured against. Presented as panels they arrive simultaneously
 * and compete; presented as scenes they arrive in order, each holding the
 * screen until it has been read.
 *
 * Each `Act` is a section several viewports tall whose contents are pinned to
 * the top of the screen. Scrolling does not move them -- it advances them.
 * That is the whole mechanic, and everything below is staged against the 0-1
 * progress each act reports.
 *
 * NOTHING HERE INVENTS ANYTHING
 *
 * The sculpture is the deck's own pages, lit where the extractor read them.
 * The field in the last act is this report's own comparables. The score, its
 * interval and its base rate are the model's. When a figure is missing the
 * scene says so rather than animating a placeholder.
 */

type Band = { fg: string; label: string };

const BANDS = {
  above: "var(--positive-on-ink)",
  within: "var(--caution-on-ink)",
  below: "var(--negative-on-ink)",
} as const;

function bandFor(score: number): Band {
  if (score >= 65) return { fg: BANDS.above, label: "Above comparable base rate" };
  if (score >= 45) return { fg: BANDS.within, label: "Near comparable base rate" };
  return { fg: BANDS.below, label: "Below comparable base rate" };
}

export default function ReportFilm({
  company,
  deckId,
  analyzedOn,
  claimsChecked,
  score,
  recommendation,
  riskLevel,
  low,
  high,
  baseRate,
  modelAvailable,
  bandKey,
  bandLabel,
  provisional,
  pages,
  coveragePct,
  readPages,
  totalPages,
  comparables,
  bull,
  bear,
  bullRan,
  bearRan,
  claims,
  onExport,
  exporting,
}: {
  company: string;
  deckId: string;
  analyzedOn: string;
  claimsChecked: number;
  score: number;
  recommendation: string;
  riskLevel?: string | null;
  low?: number;
  high?: number;
  baseRate?: number;
  modelAvailable: boolean;
  bandKey?: "above" | "within" | "below";
  bandLabel?: string;
  provisional?: boolean;
  /** The deck's own pages, for the sculpture. */
  pages: DeckPage[];
  coveragePct?: number;
  readPages?: number;
  totalPages?: number;
  comparables: ComparablePoint[];
  /** The two specialists' findings, for the split-screen act. */
  bull: string[];
  bear: string[];
  /** Whether each specialist ran at all -- silence and absence are not the same. */
  bullRan: boolean;
  bearRan: boolean;
  /** One entry per checked claim, for the evidence act. */
  claims: Array<{ claim: string; verdict: string; confidence: number }>;
  onExport: () => void;
  exporting: boolean;
}) {
  const navigate = useNavigate();
  const band: Band = bandKey
    ? { fg: BANDS[bandKey], label: bandLabel || bandFor(score).label }
    : bandFor(score);
  const hasInterval = typeof low === "number" && typeof high === "number" && high > low;
  const hasCoverage = typeof coveragePct === "number" && typeof totalPages === "number";

  return (
    <div className="film">
      <ActStyles />
      <style>{`
        .film { position: relative; background: transparent; color: var(--text-on-ink); }

        .film-scene {
          position: relative; height: 100vh; width: 100%;
          /* Transparent, like .film: the acts are lit by the room behind the
             whole product rather than each painting its own flat ground. */
          background: transparent;
          display: flex; flex-direction: column; justify-content: center;
          padding: 0 clamp(20px, 5vw, 92px);
          overflow: hidden;
        }
        .film-inner { position: relative; z-index: 2; max-width: 1320px; margin: 0 auto; width: 100%; }

        .film-eyebrow {
          display: inline-flex; align-items: center; gap: 12px;
          font-size: 11px; font-weight: 600; letter-spacing: 0.22em;
          text-transform: uppercase; color: color-mix(in srgb, var(--text-on-ink) 45%, transparent);
        }
        .film-id {
          font-family: var(--font-mono); letter-spacing: 0.06em;
          padding: 4px 11px; border-radius: 999px;
          border: 1px solid var(--ink-line); color: color-mix(in srgb, var(--text-on-ink) 70%, transparent);
        }

        /* The subject, at the size the subject deserves. clamp() so this is one
           line on a laptop and still one line on a phone. */
        .film-name {
          font-family: var(--font-display);
          font-size: clamp(64px, 14vw, 230px);
          line-height: 0.84;
          letter-spacing: -0.045em;
          margin: 26px 0 0;
          color: var(--text-on-ink);
          text-wrap: balance;
        }

        .film-meta {
          margin-top: 30px; display: flex; gap: 28px; flex-wrap: wrap;
          font-size: 13.5px; color: color-mix(in srgb, var(--text-on-ink) 52%, transparent);
        }
        .film-meta b { display: block; color: var(--text-on-ink); font-weight: 600; font-size: 15px; margin-bottom: 3px; }

        .film-cue {
          position: absolute; left: clamp(20px, 5vw, 92px); bottom: 42px; z-index: 3;
          display: inline-flex; align-items: center; gap: 10px;
          font-size: 11px; font-weight: 600; letter-spacing: 0.22em;
          text-transform: uppercase; color: color-mix(in srgb, var(--text-on-ink) 40%, transparent);
        }
        .film-cue svg { animation: film-bob 2.6s var(--ease-in-out) infinite; }
        @keyframes film-bob { 0%,100% { transform: translateY(0); opacity: .45 } 50% { transform: translateY(6px); opacity: 1 } }
        :root[data-motion="off"] .film-cue svg { animation: none } 

        /* ── The number ─────────────────────────────────────────────────── */
        .film-score {
          font-family: var(--font-display);
          line-height: 0.8; letter-spacing: -0.05em;
          display: block;
        }
        .film-of { font-family: var(--font-mono); font-size: clamp(14px, 1.4vw, 22px); color: color-mix(in srgb, var(--text-on-ink) 35%, transparent); }

        .film-track { position: relative; height: 3px; background: color-mix(in srgb, var(--text-on-ink) 12%, transparent); border-radius: 3px; }
        .film-range { position: absolute; top: 0; height: 100%; border-radius: 3px; background: color-mix(in srgb, var(--text-on-ink) 34%, transparent); }
        .film-base { position: absolute; top: -6px; width: 1.5px; height: 15px; background: color-mix(in srgb, var(--text-on-ink) 60%, transparent); }
        .film-dot {
          position: absolute; top: 50%; width: 13px; height: 13px; border-radius: 50%;
          transform: translate(-50%,-50%); box-shadow: 0 0 0 5px var(--ink-0), 0 0 28px currentColor;
        }
        .film-legend {
          display: flex; justify-content: space-between; margin-top: 12px;
          font-family: var(--font-mono); font-size: 11.5px; color: color-mix(in srgb, var(--text-on-ink) 42%, transparent);
        }

        /* ── Coverage ───────────────────────────────────────────────────── */
        .film-strip { display: flex; flex-wrap: wrap; gap: 6px; max-width: 900px; }
        .film-page {
          width: 26px; height: 34px; border-radius: 3px;
          border: 1px solid color-mix(in srgb, var(--text-on-ink) 16%, transparent);
          background: color-mix(in srgb, var(--text-on-ink) 5%, transparent);
          transition: background 320ms var(--ease-out), border-color 320ms var(--ease-out), transform 320ms var(--ease-out);
        }
        .film-page[data-on="true"][data-read="true"] {
          background: color-mix(in srgb, var(--text-on-ink) 82%, transparent);
          border-color: color-mix(in srgb, var(--text-on-ink) 90%, transparent);
        }
        .film-page[data-on="true"][data-read="false"] {
          background: rgba(255,124,110,0.10); border-color: rgba(255,124,110,0.55);
          border-style: dashed;
        }

        .film-split {
          display: grid;
          grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
          gap: clamp(28px, 5vw, 76px);
          align-items: end;
        }
        @media (max-width: 900px) { .film-split { grid-template-columns: 1fr; align-items: start; gap: 30px; } }

        .film-note {
          font-size: clamp(15px, 1.25vw, 18px); line-height: 1.75;
          color: color-mix(in srgb, var(--text-on-ink) 62%, transparent); max-width: 46ch;
        }

        .film-chip {
          display: inline-flex; align-items: center; padding: 8px 16px;
          border-radius: 999px; border: 1px solid var(--ink-line-strong);
          background: color-mix(in srgb, var(--text-on-ink) 5%, transparent);
          font-size: 12.5px; font-weight: 600; letter-spacing: 0.04em;
        }

        /* ── The case, both ways ────────────────────────────────────────── */
        .film-versus {
          position: absolute; inset: 0; display: grid;
          grid-template-columns: 1fr 1fr;
        }
        .film-side {
          padding: clamp(60px, 9vh, 120px) clamp(20px, 4vw, 64px);
          display: flex; flex-direction: column; justify-content: center;
          gap: 18px; min-width: 0;
        }
        .film-side-bull { background: linear-gradient(120deg, rgba(53,208,141,0.09), transparent 62%); }
        .film-side-bear { background: linear-gradient(240deg, rgba(255,124,110,0.09), transparent 62%); align-items: flex-end; text-align: right; }
        .film-side h3 {
          font-family: var(--font-display); font-size: clamp(30px, 4vw, 62px);
          margin: 0 0 8px; letter-spacing: -0.025em; line-height: 1;
        }
        .film-point {
          font-size: clamp(14px, 1.15vw, 17px); line-height: 1.6;
          color: color-mix(in srgb, var(--text-on-ink) 78%, transparent); max-width: 34ch;
          padding: 14px 0; border-top: 1px solid var(--ink-line);
        }
        .film-seam {
          position: absolute; left: 50%; top: 0; bottom: 0; width: 1px;
          background: linear-gradient(180deg, transparent, var(--ink-line-strong) 22%, var(--ink-line-strong) 78%, transparent);
        }
        @media (max-width: 820px) {
          .film-versus { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; }
          .film-side-bear { align-items: flex-start; text-align: left; }
          .film-seam { left: 0; right: 0; top: 50%; bottom: auto; width: auto; height: 1px;
            background: linear-gradient(90deg, transparent, var(--ink-line-strong), transparent); }
        }

        /* ── Evidence ───────────────────────────────────────────────────── */
        .film-claims { display: grid; gap: 12px; }
        .film-claim {
          border: 1px solid var(--ink-line); border-radius: var(--radius-lg);
          padding: 18px 22px; background: color-mix(in srgb, var(--text-on-ink) 3%, transparent);
          display: flex; align-items: flex-start; gap: 18px;
        }
        .film-claim-verdict {
          font-size: 11px; font-weight: 700; letter-spacing: 0.14em;
          text-transform: uppercase; white-space: nowrap; padding-top: 3px;
        }
        .film-claim-text { font-size: clamp(14px, 1.1vw, 16.5px); line-height: 1.6; color: color-mix(in srgb, var(--text-on-ink) 84%, transparent); }

        /* ── The fixed chrome the film carries instead of a sidebar ─────── */
        /* Absolute, not fixed: it belongs to the film and scrolls away with
           it. Fixed, it collided with the document sheet's own sticky bar,
           which carries the same two controls once the reader is in the
           evidence. */
        .film-bar {
          position: absolute; top: 0; left: 0; right: 0; z-index: 50;
          display: flex; align-items: center; gap: 16px;
          padding: 16px clamp(20px, 5vw, 92px);
          /* The bar's own scrim, so the two pills stay readable over whatever
             the scene puts behind them. It is the page fading out, not a black
             one -- on the light theme a literal black wash was a bruise across
             the top of the report. */
          background: linear-gradient(180deg, color-mix(in srgb, var(--ink-0) 88%, transparent), transparent);
          pointer-events: none;
        }
        .film-bar > * { pointer-events: auto; }
        .film-back, .film-export {
          display: inline-flex; align-items: center; gap: 8px;
          padding: 9px 16px; border-radius: 999px; cursor: pointer;
          font-family: var(--font-sans); font-size: 12.5px; font-weight: 600;
          color: var(--text-on-ink); background: color-mix(in srgb, var(--text-on-ink) 7%, transparent);
          border: 1px solid var(--ink-line);
          transition: background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
        }
        .film-back:hover, .film-export:hover:not(:disabled) {
          background: color-mix(in srgb, var(--text-on-ink) 16%, transparent); border-color: var(--ink-line-strong);
        }
        .film-export:disabled { opacity: 0.6; cursor: progress; }
        .film-spin { animation: film-rot 0.9s linear infinite; }
        @keyframes film-rot { to { transform: rotate(360deg) } }

        @media (max-width: 720px) {
          .film-meta { gap: 18px; font-size: 12.5px; }
          .film-bar { padding: 12px 18px; }
        }
      `}</style>

      {/* ── Chrome. The report has no sidebar; this is all of it. ───────── */}
      <div className="film-bar">
        <button className="film-back" onClick={() => navigate("/")}>
          <ArrowLeft size={14} /> All analyses
        </button>
        <span style={{ marginLeft: "auto" }}>
          <button className="film-export" onClick={onExport} disabled={exporting}>
            {exporting
              ? <><Loader2 size={13} className="film-spin" /> Exporting…</>
              : <><Download size={13} /> Export PDF</>}
          </button>
        </span>
      </div>

      {/* ── ACT I · The subject ─────────────────────────────────────────── */}
      <Act length={1.7}>
        {(p, reduced) => {
          // Nothing departs when motion is suppressed: there is no scroll
          // scrub to bring the next scene in, so leaving is just vanishing.
          const leave = reduced ? 0 : beat(p, 0.86, 1);
          return (
            <div className="film-scene">
              {/* The deck sculpture used to hang here: a stack of translucent
                  blue sheets, one per page, fanned in perspective. It was
                  honest -- lit sheets were pages the extractor read -- but on
                  the opening frame it read as decoration competing with the
                  company's name, and the same fact is already stated in words
                  two lines below ("6 of 6 pages read") and drawn page by page
                  in the coverage act. Removed rather than restyled: the hero
                  has one job, which is to say whose report this is. */}
              <div
                className="film-inner"
                style={{
                  transform: `translate3d(0, ${-leave * 90}px, 0)`,
                  opacity: 1 - leave,
                }}
              >
                <Reveal as="div">
                  <span className="film-eyebrow">
                    Analysis report
                    <span className="film-id">{deckId}</span>
                  </span>
                </Reveal>

                <h1 className="film-name">
                  <SplitWords text={company} stagger={0.09} />
                </h1>

                {/* Revealed on arrival, not on scroll: staging this against
                    act progress meant it was invisible at the top of the act,
                    which is exactly when a reader looks for it. */}
                <Reveal as="div" className="film-meta" delay={0.5}>
                  <span><b>{analyzedOn}</b>analysed</span>
                  <span><b>{claimsChecked}</b>claim{claimsChecked === 1 ? "" : "s"} checked</span>
                  {hasCoverage && <span><b>{readPages} of {totalPages}</b>pages read</span>}
                  <span><b>{recommendation}</b>verdict</span>
                </Reveal>
              </div>

              <span className="film-cue" style={{ opacity: 1 - beat(p, 0.06, 0.28) }}>
                <ArrowDown size={13} /> Scroll
              </span>
            </div>
          );
        }}
      </Act>

      {/* ── ACT II · The number ─────────────────────────────────────────── */}
      <Act length={2.0}>
        {(p) => {
          const grow = easeOut(beat(p, 0, 0.22));
          const counted = Math.round(score * easeOut(beat(p, 0.02, 0.26)));
          const drawn = easeOut(beat(p, 0.22, 0.42));
          const told = easeOut(beat(p, 0.34, 0.52));
          return (
            <div className="film-scene">
              <div className="film-inner">
                <div className="film-eyebrow" style={{ opacity: easeOut(beat(p, 0, 0.1)) }}>
                  The number
                </div>

                {modelAvailable ? (
                  <div className="film-split" style={{ marginTop: 20 }}>
                  <div>
                    <div style={{ display: "flex", alignItems: "baseline", gap: "min(2vw, 20px)" }}>
                      <span
                        className="film-score"
                        style={{
                          color: band.fg,
                          fontSize: `clamp(120px, ${11 + grow * 12}vw, 340px)`,
                          textShadow: `0 0 ${70 * grow}px color-mix(in srgb, ${band.fg} 26%, transparent)`,
                        }}
                      >
                        {counted}
                      </span>
                      <span className="film-of" style={{ opacity: grow }}>/100</span>
                    </div>

                    <div
                      style={{
                        marginTop: 30,
                        opacity: drawn, transform: `translate3d(0, ${(1 - drawn) * 16}px, 0)`,
                      }}
                    >
                      {hasInterval && (
                        <>
                          <div className="film-track">
                            <div
                              className="film-range"
                              style={{ left: `${low}%`, width: `${Math.max((high as number) - (low as number), 1) * drawn}%` }}
                            />
                            {typeof baseRate === "number" && (
                              <div className="film-base" style={{ left: `${baseRate}%`, opacity: drawn }} />
                            )}
                            <div
                              className="film-dot"
                              style={{ left: `${score * drawn}%`, background: band.fg, color: band.fg }}
                            />
                          </div>
                          <div className="film-legend">
                            <span>likely {low}–{high}</span>
                            {typeof baseRate === "number" && <span>base rate {baseRate}</span>}
                          </div>
                        </>
                      )}
                    </div>

                  </div>

                  <div style={{ paddingBottom: "clamp(0px, 2vw, 22px)" }}>
                    <div
                      style={{
                        display: "flex", gap: 12, flexWrap: "wrap",
                        opacity: told, transform: `translate3d(0, ${(1 - told) * 14}px, 0)`,
                      }}
                    >
                      <span className="film-chip" style={{ color: band.fg, borderColor: "currentColor" }}>
                        {band.label}
                      </span>
                      {riskLevel && <span className="film-chip">{riskLevel} risk</span>}
                      {provisional && <span className="film-chip" style={{ color: "var(--caution-on-ink)" }}>Provisional</span>}
                    </div>

                    <p className="film-note" style={{ marginTop: 22, opacity: told }}>
                      It estimates the likelihood of an exit rather than a shutdown, for a
                      company with these characteristics. It is not a forecast of returns,
                      and the interval beside it is as much of the answer as the number is.
                    </p>
                  </div>
                  </div>
                ) : (
                  <p style={{ marginTop: 26, maxWidth: "46ch", fontSize: 19, lineHeight: 1.6 }}>
                    <strong style={{ color: "var(--text-on-ink)" }}>No model score.</strong>{" "}
                    <span style={{ color: "color-mix(in srgb, var(--text-on-ink) 62%, transparent)" }}>
                      This report fell back to the formula, so there is no calibrated
                      score or interval to show. The evidence that follows is unaffected.
                    </span>
                  </p>
                )}
              </div>
            </div>
          );
        }}
      </Act>

      {/* ── ACT III · What was read ─────────────────────────────────────── */}
      {hasCoverage && (
        <Act length={1.9}>
          {(p) => {
            const lit = beat(p, 0.02, 0.4);
            const shownPages = Math.round(lit * (totalPages ?? 0));
            const told = 0.4 + 0.6 * easeOut(beat(p, 0, 0.34));
            const tone = (coveragePct ?? 0) >= 75 ? "var(--positive-on-ink)"
              : (coveragePct ?? 0) >= 40 ? "var(--caution-on-ink)" : "var(--negative-on-ink)";
            return (
              <div className="film-scene">
                <div className="film-inner">
                  <div className="film-eyebrow">What we could read</div>

                  <div className="film-split" style={{ marginTop: 20 }}>
                  <div>
                    <span
                      className="film-score"
                      style={{ color: tone, fontSize: "clamp(96px, 12vw, 240px)", display: "block" }}
                    >
                      {Math.round((coveragePct ?? 0) * easeOut(beat(p, 0.04, 0.34)))}%
                    </span>
                    <span style={{ display: "block", marginTop: 18, fontSize: 16, color: "color-mix(in srgb, var(--text-on-ink) 55%, transparent)" }}>
                      of the deck reached a structured field
                    </span>
                  </div>

                  <div style={{ paddingBottom: "clamp(0px, 2vw, 18px)" }}>
                  {/* One tile per page, lighting up as the reader advances. A
                      percentage is a claim; this is the claim's arithmetic. */}
                  <div className="film-strip">
                    {pages.map((page, i) => (
                      <span
                        key={page.slide}
                        className="film-page"
                        data-on={i < shownPages}
                        data-read={page.read}
                        title={`Page ${page.slide}${page.heading ? ` — ${page.heading}` : ""}`}
                      />
                    ))}
                  </div>

                  <p className="film-note" style={{ marginTop: 28, opacity: told }}>
                    {(coveragePct ?? 0) >= 75
                      ? "Nearly all of this deck reached the findings, so an absent figure below is most likely absent from the deck."
                      : "The hollow tiles are pages nothing structured came out of. Treat an “insufficient data” finding below as a gap in the reading before you treat it as a gap in the company."}
                  </p>
                  </div>
                  </div>
                </div>
              </div>
            );
          }}
        </Act>
      )}

      {/* ── ACT IV · The case, both ways ────────────────────────────────── */}
      {(bull.length > 0 || bear.length > 0 || !bullRan || !bearRan) && (
        <Act length={1.7}>
          {(p, reduced) => {
            // The two halves arrive from their own sides and meet at the seam.
            const enter = reduced ? 1 : easeOut(beat(p, 0, 0.26));
            const items = reduced ? 1 : beat(p, 0.12, 0.58);
            return (
              <div className="film-scene" style={{ padding: 0 }}>
                <div className="film-versus">
                  <div
                    className="film-side film-side-bull"
                    style={{ transform: `translate3d(${(enter - 1) * 14}%, 0, 0)`, opacity: enter }}
                  >
                    <div className="film-eyebrow" style={{ color: "var(--positive-on-ink)" }}>The case for</div>
                    <h3 style={{ color: "var(--positive-on-ink)" }}>Bull</h3>
                    {bullRan ? (
                      bull.length > 0 ? bull.map((point, i) => (
                        <p
                          key={point}
                          className="film-point"
                          style={{ opacity: items > i / Math.max(bull.length, 1) ? 1 : 0.06 }}
                        >
                          {point}
                        </p>
                      )) : <p className="film-point">No positive signal cleared the evidence bar.</p>
                    ) : (
                      <p className="film-point">
                        The bull-case agent did not run &mdash; the language model was
                        unavailable. Nothing was established either way.
                      </p>
                    )}
                  </div>

                  <div
                    className="film-side film-side-bear"
                    style={{ transform: `translate3d(${(1 - enter) * 14}%, 0, 0)`, opacity: enter }}
                  >
                    <div className="film-eyebrow" style={{ color: "var(--negative-on-ink)" }}>The case against</div>
                    <h3 style={{ color: "var(--negative-on-ink)" }}>Bear</h3>
                    {bearRan ? (
                      bear.length > 0 ? bear.map((point, i) => (
                        <p
                          key={point}
                          className="film-point"
                          style={{ opacity: items > i / Math.max(bear.length, 1) ? 1 : 0.06 }}
                        >
                          {point}
                        </p>
                      )) : <p className="film-point">No red flag cleared the evidence bar.</p>
                    ) : (
                      <p className="film-point">
                        The bear-case agent did not run &mdash; the language model was
                        unavailable. Nothing was established either way.
                      </p>
                    )}
                  </div>
                </div>
                <div className="film-seam" style={{ opacity: enter }} aria-hidden="true" />
              </div>
            );
          }}
        </Act>
      )}

      {/* ── ACT V · The evidence ────────────────────────────────────────── */}
      {claims.length > 0 && (
        <Act length={2.6}>
          {(p, reduced) => {
            // Each claim is dealt in turn rather than all at once: the point of
            // this scene is that they were checked one at a time.
            const dealt = reduced ? claims.length : beat(p, 0.05, 0.6) * claims.length;
            const told = reduced ? 1 : easeOut(beat(p, 0, 0.18));
            return (
              <div className="film-scene">
                <div className="film-inner">
                  <div className="film-split" style={{ alignItems: "start" }}>
                  <div>
                    <div className="film-eyebrow" style={{ opacity: told }}>Checked against public sources</div>
                    <h2 className="vf-lg" style={{ color: "var(--text-on-ink)", margin: "18px 0 26px", opacity: told, maxWidth: "12ch" }}>
                      {claims.length} claim{claims.length === 1 ? "" : "s"}, each with its evidence
                    </h2>
                    <p className="film-note" style={{ opacity: told }}>
                      Unsettled is not a failure. A private company&rsquo;s revenue is not
                      published anywhere, so no search can confirm it. Every verdict
                      and its sources are on the Evidence tab below.
                    </p>
                  </div>

                  <div className="film-claims">
                    {claims.map((c, i) => {
                      const shown = Math.max(0, Math.min(1, dealt - i));
                      const tone = c.verdict === "SUPPORTS" ? "var(--positive-on-ink)"
                        : c.verdict === "REFUTES" ? "var(--negative-on-ink)"
                          : "color-mix(in srgb, var(--text-on-ink) 50%, transparent)";
                      const word = c.verdict === "SUPPORTS" ? "Supported"
                        : c.verdict === "REFUTES" ? "Refuted" : "Unsettled";
                      return (
                        <div
                          key={`${c.claim}-${i}`}
                          className="film-claim"
                          style={{
                            opacity: shown,
                            transform: `translate3d(0, ${(1 - shown) * 26}px, 0)`,
                          }}
                        >
                          <span className="film-claim-verdict" style={{ color: tone }}>{word}</span>
                          <span className="film-claim-text">{c.claim}</span>
                        </div>
                      );
                    })}
                  </div>
                  </div>
                </div>
              </div>
            );
          }}
        </Act>
      )}

      {/* ── ACT VI · The population ─────────────────────────────────────── */}
      {comparables.length > 0 && (
        <Act length={1.6}>
          {(p) => {
            const told = easeOut(beat(p, 0.02, 0.24));
            return (
              <div className="film-scene">
                <div style={{ position: "absolute", inset: 0, opacity: 0.9 }}>
                  <Constellation points={comparables} company={company} height={900} />
                </div>
                <div className="film-inner" style={{ opacity: told }}>
                  <div className="film-eyebrow">Measured against</div>
                  <h2
                    className="vf-lg"
                    style={{ color: "var(--text-on-ink)", margin: "18px 0 0", maxWidth: "16ch" }}
                  >
                    {comparables.length} companies whose outcome is already known
                  </h2>
                  <p style={{ marginTop: 20, maxWidth: "48ch", fontSize: 15, lineHeight: 1.7, color: "color-mix(in srgb, var(--text-on-ink) 62%, transparent)" }}>
                    Each point is one of them: the closer to the centre, the more like
                    this company it is. Green exited, red shut down. The score is a
                    statement about this population, not about the world.
                  </p>
                </div>
              </div>
            );
          }}
        </Act>
      )}
    </div>
  );
}
