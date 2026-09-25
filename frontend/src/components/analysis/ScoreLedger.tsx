import { useState } from "react";
import { ArrowDown, Info } from "lucide-react";
import type { AnalyzeResponse } from "../../services/apiClient";
import { Badge, Modal, type Tone } from "../ui/Surface";

/**
 * The score, as arithmetic rather than as an announcement.
 *
 * WHAT IT SHOWS
 *
 *   model prior            what a trained model expects of a company with
 *                          these characteristics, before this report
 *   evidence adjustment    what THIS report's own findings moved it by
 *   VentureFlow score      the sum, which is the number on the report
 *
 * plus the three figures that say how much to trust it: how much of the input
 * the model actually had, how much its ensemble members disagreed, and the
 * confidence band that follows from both.
 *
 * WHY THE LEDGER IS THE HEADLINE
 *
 * A single large number is a claim. A prior plus an adjustment is a method:
 * the reader can see that most of the score is a statement about companies
 * like this one rather than about this deck, and can weigh the part that came
 * from their own document separately. It is also the only honest way to show
 * a model that is barely better than the base rate -- which this one is, and
 * says so under "How this score was produced".
 *
 * NOTHING HERE IS COMPUTED IN THE BROWSER
 *
 * Every figure comes from `sections.venture_score`, which the server produced.
 * The one piece of arithmetic is `prior + adjustment`, shown so the reader can
 * check it against the total themselves.
 */

type VS = NonNullable<NonNullable<AnalyzeResponse["sections"]>["venture_score"]>;

const CONFIDENCE_TONE: Record<string, Tone> = {
  high: "verified",
  medium: "caution",
  low: "critical",
};

/**
 * The model family, spelled out.
 *
 * The field carries the trainer's own short code ("rf"), which is correct in a
 * metrics file and reads as a typo in a sentence shown to a partner.
 */
const FAMILY_NAMES: Record<string, string> = {
  rf: "random forest",
  random_forest: "random forest",
  gbm: "gradient-boosted tree ensemble",
  lgbm: "LightGBM gradient-boosted ensemble",
  lightgbm: "LightGBM gradient-boosted ensemble",
  xgb: "XGBoost ensemble",
  logreg: "logistic regression",
  logistic_regression: "logistic regression",
};
const familyName = (f?: string) =>
  (f && FAMILY_NAMES[f.toLowerCase()]) || f || "";

export default function ScoreLedger({
  data,
  reportedScore,
}: {
  data?: VS;
  /** The score on the report, for the reconciliation note. */
  reportedScore: number;
}) {
  const [explaining, setExplaining] = useState(false);

  if (!data?.available || typeof data.venture_score !== "number") {
    return (
      <div className="sl-root sl-unavailable">
        <style>{SL_CSS}</style>
        <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>No model score</div>
        <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.7, color: "var(--text-2)", maxWidth: "62ch" }}>
          {data?.reason
            || "The trained model did not produce a score for this report, so the fallback formula was used. There is no calibrated prior or interval to break down here; the evidence in the rest of the report is unaffected."}
        </p>
      </div>
    );
  }

  const prior = typeof data.model_only_score === "number" ? Math.round(data.model_only_score) : null;
  /**
   * `evidence_penalty` is a PROBABILITY, not points.
   *
   * ml/venturescore.blend_with_evidence computes
   * `round((prior_probability - evidence_penalty) * 100)`, so a penalty of
   * 0.05 is five points off the score. Rounding the raw field displayed "0"
   * beside a prior of 49 and a total of 44 -- an equation that does not add
   * up, on the one panel in this product whose entire job is to show its
   * arithmetic. It is always subtracted, so it is always shown negative.
   */
  const penalty = typeof data.evidence_penalty === "number"
    ? -Math.round(data.evidence_penalty * 100)
    : null;
  const score = Math.round(data.venture_score);
  const baseRate = typeof data.base_rate === "number"
    ? Math.round(data.base_rate * (data.base_rate <= 1 ? 100 : 1))
    : null;
  const lift = baseRate !== null ? score - baseRate : null;
  const std = typeof data.ensemble_std === "number" ? Math.round(data.ensemble_std * 100) : null;
  const coverage = typeof data.feature_coverage === "number" ? Math.round(data.feature_coverage * 100) : null;
  const confidence = data.confidence ?? "medium";

  return (
    <div className="sl-root">
      <style>{SL_CSS}</style>

      {/* ── The ledger ──────────────────────────────────────────────────── */}
      <div className="sl-ledger">
        <div className="sl-line">
          <div>
            <div className="vf-label">Model prior</div>
            <div className="sl-line-note">a company with these characteristics</div>
          </div>
          <div className="sl-value vf-figure">{prior ?? "—"}</div>
        </div>

        <div className="sl-op" aria-hidden="true"><ArrowDown size={14} /></div>

        <div className="sl-line">
          <div>
            <div className="vf-label">Evidence adjustment</div>
            <div className="sl-line-note">what this report's claims, risk and financials moved it by</div>
          </div>
          <div
            className="sl-value vf-figure"
            style={{ color: penalty === null ? undefined : penalty < 0 ? "var(--critical)" : penalty > 0 ? "var(--verified)" : undefined }}
          >
            {penalty === null ? "—" : penalty === 0 ? "0" : penalty}
          </div>
        </div>

        <div className="sl-rule" />

        <div className="sl-line sl-total">
          <div>
            <div className="vf-label" style={{ color: "var(--text)" }}>VentureFlow score</div>
            <div className="sl-line-note">
              {baseRate !== null && (
                <>against a comparable base rate of <b className="vf-num">{baseRate}</b>
                  {lift !== null && (
                    <> &middot; {lift > 0 ? "+" : ""}{lift} {Math.abs(lift) === 1 ? "point" : "points"}</>
                  )}
                </>
              )}
            </div>
          </div>
          <div className="sl-value sl-value-total vf-figure">{score}</div>
        </div>
      </div>

      {/* Two different ways the ledger can fail to reconcile, and each says
          which one it is rather than leaving the reader to do the subtraction
          and conclude the panel is broken. */}
      {prior !== null && penalty !== null && prior + penalty !== score && (
        <p className="sl-reconcile">
          The prior and the adjustment do not sum exactly to the score: both are
          rounded to whole points for display, and the pipeline bounds the result to
          0&ndash;100 before rounding.
        </p>
      )}
      {score !== Math.round(reportedScore) && (
        <p className="sl-reconcile">
          The report shows <b className="vf-num">{Math.round(reportedScore)}</b>: the model
          score above is capped or adjusted elsewhere in the pipeline for this report.
        </p>
      )}

      {/* ── How much to trust it ────────────────────────────────────────── */}
      <div className="sl-trust">
        <div className="sl-trust-cell">
          <div className="vf-label">Input coverage</div>
          <div className="sl-trust-value vf-figure">{coverage === null ? "—" : `${coverage}%`}</div>
          <div className="sl-line-note">
            {data.imputed_features?.length
              ? `${data.imputed_features.length} feature${data.imputed_features.length === 1 ? "" : "s"} imputed`
              : "of the model's inputs were observed"}
          </div>
        </div>

        <div className="sl-trust-cell">
          <div className="vf-label">Model agreement</div>
          <div className="sl-trust-value vf-figure">{std === null ? "—" : `±${std}`}</div>
          <div className="sl-line-note">spread across the ensemble, in points</div>
        </div>

        <div className="sl-trust-cell">
          <div className="vf-label">Confidence</div>
          <div style={{ marginTop: 8 }}>
            <Badge tone={CONFIDENCE_TONE[confidence] ?? "caution"} dot>
              {confidence.charAt(0).toUpperCase() + confidence.slice(1)}
            </Badge>
          </div>
          <div className="sl-line-note">from coverage and ensemble spread</div>
        </div>
      </div>

      <button className="sl-explain" onClick={() => setExplaining(true)} data-cursor="Explain">
        <Info size={14} /> How was this score produced?
      </button>

      {/* ── The reasoning chain ─────────────────────────────────────────── */}
      <Modal open={explaining} onClose={() => setExplaining(false)} title="How this score was produced" width={720}>
        <ol className="sl-chain">
          <li>
            <h3>1 · A model trained on recorded outcomes</h3>
            <p>
              {data.model?.family
                ? <>The score comes from a <b>{familyName(data.model.family)}</b>{data.model.calibration ? <>, calibrated with {data.model.calibration} regression</> : null}.</>
                : <>The score comes from a trained classifier rather than from the language model.</>}
              {typeof data.model?.trained_n === "number" && (
                <> It was fitted on <b className="vf-num">{data.model.trained_n.toLocaleString()}</b> companies whose outcome is already settled &mdash; acquired, public, or shut down.</>
              )}
            </p>
            {typeof data.model?.cv_roc_auc === "number" && (
              <p className="sl-metric">
                Cross-validated ROC AUC <b className="vf-num">{data.model.cv_roc_auc.toFixed(3)}</b>
                {data.model.cv_roc_auc_ci95 && (
                  <> (95% CI {data.model.cv_roc_auc_ci95[0].toFixed(3)}&ndash;{data.model.cv_roc_auc_ci95[1].toFixed(3)})</>
                )}
                {typeof data.model.cv_ece === "number" && <> &middot; calibration error {data.model.cv_ece.toFixed(3)}</>}
                . 0.5 would be a coin flip.
              </p>
            )}
          </li>

          <li>
            <h3>2 · The prior for a company like this one</h3>
            <p>
              The model reads this company's characteristics &mdash; sector, stage, team
              size, the deck's own text &mdash; and returns{" "}
              <b className="vf-num">{prior ?? "—"}</b>. That figure is a statement about the
              population, not about this deck: two companies with identical
              characteristics start from the same place.
            </p>
            {data.imputed_features?.length ? (
              <p className="sl-metric">
                Not every input was present. Imputed: {data.imputed_features.join(", ")}.
                An imputed feature carries the population's average rather than this
                company's value.
              </p>
            ) : null}
          </li>

          <li>
            <h3>3 · What this report found</h3>
            <p>
              The evidence adjustment of{" "}
              <b className="vf-num">{penalty === null ? "—" : penalty}</b>{" "}
              {penalty === 0
                ? "means this report's findings did not move the prior at all."
                : "points is the only part of the score that came from your document:"}{" "}
              {penalty === 0
                ? "The claims, risk signals and financials it found were not enough to shift it."
                : "verified and refuted claims, detected risk signals, and disclosed financials."}{" "}
              The term only ever subtracts, and is capped at 60 points, so no single
              finding can swing the number arbitrarily.
            </p>
          </li>

          <li>
            <h3>4 · What the number does and does not mean</h3>
            <p>
              It estimates the likelihood of an exit rather than a shutdown for a company
              with these characteristics. It is not a forecast of returns, not a
              recommendation, and not a measurement of quality.
              {typeof data.ensemble_std === "number" && (
                <> The ensemble's members disagreed by about <b className="vf-num">{std}</b> points, which is why the report shows an interval and not a point.</>
              )}
            </p>
            {data.caveat && <p className="sl-metric">{data.caveat}</p>}
          </li>
        </ol>
      </Modal>
    </div>
  );
}

const SL_CSS = `
  .sl-root { width: 100%; }
  .sl-unavailable { padding: 20px 22px; border: 1px solid var(--line); border-radius: var(--r-lg); background: var(--surface); }

  .sl-ledger { border: 1px solid var(--line); border-radius: var(--r-lg); background: var(--surface); padding: 6px 22px 10px; }
  .sl-line { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 16px 0; }
  .sl-line-note { font-size: var(--t-micro); color: var(--text-3); margin-top: 5px; max-width: 46ch; }
  .sl-value { font-size: 34px; color: var(--text); }
  .sl-total .sl-value-total { font-size: 54px; }
  .sl-op { display: flex; justify-content: flex-end; color: var(--text-faint); padding-right: 14px; }
  .sl-rule { height: 1px; background: var(--line-strong); margin: 4px 0; }

  .sl-reconcile { margin: 12px 2px 0; font-size: var(--t-micro); color: var(--text-3); line-height: 1.6; }

  .sl-trust {
    display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 1px; background: var(--line); border: 1px solid var(--line);
    border-radius: var(--r-lg); overflow: hidden; margin-top: 14px;
  }
  .sl-trust-cell { background: var(--surface); padding: 16px 18px; }
  .sl-trust-value { font-size: 26px; margin-top: 8px; }

  .sl-explain {
    display: inline-flex; align-items: center; gap: 8px; margin-top: 16px;
    padding: 10px 16px; border-radius: var(--r-pill); cursor: pointer;
    font: inherit; font-size: var(--t-small); font-weight: 600;
    background: var(--surface); color: var(--text-2);
    border: 1px solid var(--line-strong);
    transition: color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
  }
  .sl-explain:hover { color: var(--accent); border-color: var(--accent-line); }

  .sl-chain { list-style: none; margin: 0; padding: 0; display: grid; gap: 22px; }
  .sl-chain h3 { margin: 0 0 8px; font-size: var(--t-body); font-weight: 600; letter-spacing: -0.01em; }
  .sl-chain p { margin: 0 0 8px; font-size: var(--t-small); line-height: 1.72; color: var(--text-2); }
  .sl-metric { color: var(--text-3) !important; font-size: var(--t-micro) !important; }

  @media (max-width: 720px) {
    .sl-trust { grid-template-columns: 1fr; }
    .sl-total .sl-value-total { font-size: 42px; }
  }
`;
