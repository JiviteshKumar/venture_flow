import { motion, useReducedMotion } from "framer-motion";
import { Download, Loader2 } from "lucide-react";
import { CountUp, DURATION, EASE_OUT } from "../ui/Motion";

/**
 * The report's opening statement.
 *
 * WHY THIS EXISTS
 *
 * The analysis page had no focal point. The verdict -- the one thing a reader
 * opens the report to find -- was a 12px chip in the top-right corner reading
 * "48/100 overall score", visually identical to the Export button beside it,
 * while the score panel that explains it sat further down among twenty other
 * white cards of exactly the same weight. Everything was equally important, so
 * nothing was.
 *
 * This is the answer, stated once, at full size, before any of the supporting
 * detail. Everything below it is evidence for what this band says.
 *
 * WHY IT IS DARK
 *
 * Continuity with the sign-in screen, which is the only other place this
 * product has a voice. More practically: an inverted band is the cheapest way
 * to create hierarchy on a page made of white cards, and it does it without
 * adding another border, shadow or accent colour to a layout that already had
 * too many.
 *
 * WHAT IT REFUSES TO DO
 *
 * It never states the score without its interval and its base rate. A bare
 * "48" invites a precision the model does not have; "48, likely 40-57, against
 * a comparable base rate of 49" is the honest version of the same sentence, and
 * it is the version this product exists to give. When the model is unavailable
 * the band says so rather than rendering a number from the fallback formula as
 * though the model produced it.
 */

type Band = { fg: string; label: string; glow: string };

function bandFor(score: number): Band {
  // Thresholds mirror VentureScorePanel so one report cannot describe its own
  // score two different ways in two places.
  if (score >= 65) return { fg: "#3DDC97", label: "Above comparable base rate", glow: "rgba(61,220,151,0.22)" };
  if (score >= 45) return { fg: "#F0B72F", label: "Near comparable base rate", glow: "rgba(240,183,47,0.20)" };
  return { fg: "#FF6B5E", label: "Below comparable base rate", glow: "rgba(255,107,94,0.20)" };
}

export default function VerdictHero({
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
  provisional = false,
  provisionalNote = "",
  bandKey,
  bandLabel,
  measures = "",
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
  /** Interval bounds and base rate, from the trained model. */
  low?: number;
  high?: number;
  baseRate?: number;
  modelAvailable: boolean;
  /**
   * The score was built without a component that normally moves it, so it
   * is not comparable with a complete report's. Shown beside the numeral,
   * not in a footnote: the number and its status are one fact.
   */
  provisional?: boolean;
  provisionalNote?: string;
  /** Server-computed band (ml/score_context.py): read off the interval, not fixed thresholds. */
  bandKey?: "above" | "within" | "below";
  bandLabel?: string;
  /** What the number measures, as a tooltip on the short line below the band. */
  measures?: string;
  onExport: () => void;
  exporting: boolean;
}) {
  const reduced = useReducedMotion();
  const HERO_BANDS = {
    above: { fg: "#3DDC97", glow: "rgba(61,220,151,0.22)" },
    within: { fg: "#F0B72F", glow: "rgba(240,183,47,0.20)" },
    below: { fg: "#FF6B5E", glow: "rgba(255,107,94,0.20)" },
  } as const;
  // The server's band when there is one, so the headline and the score panel
  // below it can never describe the same number two different ways.
  const band: Band = bandKey
    ? { ...HERO_BANDS[bandKey], label: bandLabel || bandFor(score).label }
    : bandFor(score);
  const hasInterval =
    typeof low === "number" && typeof high === "number" && high > low;

  return (
    <header className="vh-root">
      <style>{`
        .vh-root {
          position: relative;
          overflow: hidden;
          padding: 34px 32px 0;
          background:
            radial-gradient(120% 140% at 0% 0%, #16355F 0%, #0B1120 52%, #070B14 100%);
          color: #E8EEF9;
        }
        /* One very slow, very low-contrast drift, shared with the sign-in
           screen so the two read as the same product. Disabled entirely under
           reduced motion -- see the query at the end of this block. */
        .vh-aura {
          position: absolute; inset: -40% -20%;
          background:
            radial-gradient(38% 38% at 22% 26%, rgba(29,111,232,0.30), transparent 70%),
            radial-gradient(32% 32% at 76% 60%, var(--vh-glow), transparent 70%);
          filter: blur(60px);
          animation: vh-drift 26s ease-in-out infinite alternate;
          pointer-events: none;
        }
        @keyframes vh-drift {
          from { transform: translate3d(-2%, -1%, 0) scale(1); }
          to   { transform: translate3d(3%, 2%, 0) scale(1.07); }
        }

        .vh-inner {
          position: relative; z-index: 1;
          display: grid; grid-template-columns: 1fr auto;
          gap: 40px; align-items: end;
          max-width: 1180px;
        }

        .vh-eyebrow {
          display: flex; align-items: center; gap: 10px;
          font-family: var(--font-mono); font-size: 9.5px;
          letter-spacing: 0.18em; text-transform: uppercase;
          color: rgba(232,238,249,0.52); margin-bottom: 14px;
        }
        .vh-id {
          border: 1px solid rgba(232,238,249,0.18); border-radius: 20px;
          padding: 2px 9px; color: rgba(232,238,249,0.72); letter-spacing: 0.1em;
        }

        .vh-company {
          font-family: var(--font-display);
          font-size: clamp(38px, 4.4vw, 62px);
          line-height: 1.02; letter-spacing: -0.022em;
          margin: 0 0 12px; color: #FFFFFF;
        }
        .vh-sub {
          font-size: 13.5px; color: rgba(232,238,249,0.62);
          margin: 0 0 22px; font-family: var(--font-mono); letter-spacing: 0.01em;
        }

        .vh-verdict-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 26px; }
        .vh-rec {
          font-family: var(--font-sans); font-size: 12px; font-weight: 700;
          letter-spacing: 0.09em; text-transform: uppercase;
          padding: 7px 14px; border-radius: 30px;
          background: rgba(232,238,249,0.09);
          border: 1px solid rgba(232,238,249,0.20);
          color: #FFFFFF;
        }
        .vh-chip {
          font-family: var(--font-mono); font-size: 10px; letter-spacing: 0.08em;
          text-transform: uppercase; padding: 6px 11px; border-radius: 30px;
          border: 1px solid rgba(232,238,249,0.16);
          color: rgba(232,238,249,0.74);
        }

        /* The score block. Right-aligned so the eye lands on the numeral after
           the company name, which is the reading order that matters. */
        .vh-score-block { text-align: right; padding-bottom: 4px; min-width: 260px; }
        .vh-measures { margin-top: 4px; font-size: 11.5px; color: rgba(232,238,249,0.62); letter-spacing: 0.01em; cursor: help; }
        .vh-provisional {
          display: inline-flex; flex-direction: column; gap: 3px; margin-top: 8px;
          padding: 6px 10px; border-radius: 8px; max-width: 320px; text-align: left;
          background: rgba(240,183,47,0.12); border: 1px solid rgba(240,183,47,0.35);
          color: #F0B72F; font-size: 12px; font-weight: 600; letter-spacing: 0.01em;
        }
        .vh-provisional-note { color: rgba(232,238,249,0.78); font-weight: 400; line-height: 1.45; }
        .vh-score-line { display: flex; align-items: baseline; justify-content: flex-end; gap: 6px; }
        .vh-score {
          font-family: var(--font-display);
          font-size: clamp(64px, 7vw, 96px);
          line-height: 0.92; letter-spacing: -0.03em;
          font-variant-numeric: tabular-nums;
        }
        .vh-of { font-family: var(--font-mono); font-size: 15px; color: rgba(232,238,249,0.45); }
        .vh-band-label {
          font-size: 12.5px; margin-top: 10px; font-weight: 500;
        }

        /* The interval, drawn to scale. The width of "we do not know" is a
           fact about this score and belongs next to it, not in a footnote. */
        .vh-track { margin-top: 16px; }
        .vh-track-bar {
          position: relative; height: 4px; border-radius: 4px;
          background: rgba(232,238,249,0.13);
        }
        .vh-track-range { position: absolute; top: 0; height: 100%; border-radius: 4px; }
        .vh-track-base {
          position: absolute; top: -4px; width: 1.5px; height: 12px;
          background: rgba(232,238,249,0.55);
        }
        .vh-track-point {
          position: absolute; top: 50%; width: 10px; height: 10px;
          border-radius: 50%; transform: translate(-50%, -50%);
          box-shadow: 0 0 0 3px rgba(7,11,20,0.85);
        }
        .vh-track-legend {
          display: flex; justify-content: space-between;
          font-family: var(--font-mono); font-size: 9.5px;
          color: rgba(232,238,249,0.42); margin-top: 8px; letter-spacing: 0.05em;
        }

        .vh-export {
          display: inline-flex; align-items: center; gap: 7px;
          font-family: var(--font-sans); font-size: 12.5px; font-weight: 600;
          padding: 9px 15px; border-radius: 9px; cursor: pointer;
          background: rgba(232,238,249,0.10);
          border: 1px solid rgba(232,238,249,0.20);
          color: #E8EEF9;
          transition: background var(--dur-fast) var(--ease-out),
                      border-color var(--dur-fast) var(--ease-out),
                      transform var(--dur-fast) var(--ease-out);
        }
        .vh-export:hover:not(:disabled) {
          background: rgba(232,238,249,0.17);
          border-color: rgba(232,238,249,0.34);
          transform: translateY(-1px);
        }
        .vh-export:disabled { opacity: 0.55; cursor: progress; }
        .vh-spin { animation: vh-rotate 0.9s linear infinite; }
        @keyframes vh-rotate { to { transform: rotate(360deg); } }

        .vh-unavailable {
          font-size: 13px; line-height: 1.6; color: rgba(232,238,249,0.75);
          max-width: 46ch; text-align: right;
        }

        @media (max-width: 900px) {
          .vh-root { padding: 26px 20px 0; }
          .vh-inner { grid-template-columns: 1fr; gap: 22px; align-items: start; }
          .vh-score-block { text-align: left; min-width: 0; }
          .vh-score-line { justify-content: flex-start; }
          .vh-unavailable { text-align: left; }
        }
        @media (prefers-reduced-motion: reduce) {
          .vh-aura { animation: none; }
        }
      `}</style>

      <div
        className="vh-aura"
        aria-hidden="true"
        style={{ ["--vh-glow" as string]: band.glow }}
      />

      <div className="vh-inner">
        <div>
          <div className="vh-eyebrow">
            <span>Analysis Report</span>
            <span className="vh-id">{deckId}</span>
          </div>

          <motion.h1
            className="vh-company"
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: DURATION.slow, ease: EASE_OUT }}
          >
            {company}
          </motion.h1>

          <p className="vh-sub">
            Analyzed {analyzedOn} · {claimsChecked} claim{claimsChecked === 1 ? "" : "s"} checked
          </p>

          <div className="vh-verdict-row">
            <span className="vh-rec">{recommendation}</span>
            {riskLevel && <span className="vh-chip">{riskLevel} risk</span>}
            <button
              className="vh-export"
              type="button"
              onClick={onExport}
              disabled={exporting}
              aria-label="Export due diligence report as PDF"
            >
              {exporting
                ? <><Loader2 size={13} className="vh-spin" /> Exporting…</>
                : <><Download size={13} strokeWidth={2} /> Export PDF</>}
            </button>
          </div>
        </div>

        <div className="vh-score-block">
          {modelAvailable ? (
            <>
              <div className="vh-score-line">
                <motion.span
                  className="vh-score"
                  style={{ color: band.fg }}
                  initial={reduced ? { opacity: 0 } : { opacity: 0, scale: 0.94 }}
                  animate={{ opacity: 1, scale: 1 }}
                  transition={{ duration: DURATION.slow, ease: EASE_OUT }}
                >
                  <CountUp value={score} duration={1.1} />
                </motion.span>
                <span className="vh-of">/100</span>
              </div>
              <div className="vh-band-label" style={{ color: band.fg }}>
                {band.label}
              </div>
              <div className="vh-measures" title={measures}>
                Exit-or-shutdown likelihood · not a forecast of returns
              </div>
              {provisional && (
                <div className="vh-provisional" role="note" title={provisionalNote}>
                  Provisional score
                  {provisionalNote && <span className="vh-provisional-note">{provisionalNote}</span>}
                </div>
              )}

              {hasInterval && (
                <div className="vh-track">
                  <div
                    className="vh-track-bar"
                    role="img"
                    aria-label={
                      `Score ${score} of 100, likely range ${low} to ${high}` +
                      (typeof baseRate === "number" ? `, comparable base rate ${baseRate}` : "")
                    }
                  >
                    <motion.div
                      className="vh-track-range"
                      style={{ left: `${low}%`, background: "rgba(232,238,249,0.28)" }}
                      initial={{ width: 0 }}
                      animate={{ width: `${Math.max((high as number) - (low as number), 1)}%` }}
                      transition={{ duration: 0.6, delay: 0.15, ease: EASE_OUT }}
                    />
                    {typeof baseRate === "number" && (
                      <div className="vh-track-base" style={{ left: `${baseRate}%` }} />
                    )}
                    <motion.div
                      className="vh-track-point"
                      style={{ background: band.fg }}
                      initial={{ left: "0%", opacity: 0 }}
                      animate={{ left: `${score}%`, opacity: 1 }}
                      transition={{ duration: 1.1, ease: EASE_OUT }}
                    />
                  </div>
                  <div className="vh-track-legend">
                    <span>likely {low}–{high}</span>
                    {typeof baseRate === "number" && <span>base rate {baseRate}</span>}
                  </div>
                </div>
              )}
            </>
          ) : (
            /* No number at all rather than the fallback formula's output
               dressed up as a model score. */
            <p className="vh-unavailable">
              <strong style={{ color: "#FFFFFF" }}>Model score unavailable.</strong>{" "}
              This report used the fallback scoring formula, so there is no
              calibrated score or interval to show here. The evidence below is
              unaffected.
            </p>
          )}
        </div>
      </div>
    </header>
  );
}
