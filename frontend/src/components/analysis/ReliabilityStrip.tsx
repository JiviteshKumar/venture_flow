import { AlertTriangle, FileWarning, Info, ScanLine } from "lucide-react";
import type { ExtractionCoverage, ExtractionProvenance } from "../../services/apiClient";
import { Card, Chip, Disclosure, Label, type Tone } from "../ui/primitives";
import { GrowBar } from "../ui/Motion";

/**
 * Everything qualifying this report, in one place, collapsed.
 *
 * WHAT IT REPLACES
 *
 * Six full-width panels stacked above the report: an incomplete-analysis
 * alert, a claim-verification-did-not-run alert, a narrower-sources notice, a
 * nothing-corroborated notice, an extraction-coverage panel with a paragraph
 * and a list of slide chips, and a degraded-extraction alert. On a report
 * where several fired at once that was roughly 350 pixels of caveat, in three
 * different background colours, before the reader reached a single finding.
 *
 * WHY IT IS NOT SIMPLY SHORTER
 *
 * Because none of it is removable. Every one of those messages exists to stop
 * a reader mistaking a parsing gap for a finding about the company, and this
 * product's entire argument is that it says what it could not establish. So
 * each keeps its full text -- it moves behind its own one-line headline, and
 * the reader opens the ones that matter to them.
 *
 * The coverage figure stays visible rather than collapsing, because it
 * qualifies every number below it: a score computed from a third of a deck is
 * a different object from one computed from all of it.
 */

type Caveat = {
  key: string;
  tone: Tone;
  icon: React.ReactNode;
  summary: string;
  body: React.ReactNode;
};

export default function ReliabilityStrip({
  coverage,
  provenance,
  incompleteAnalysis,
  verificationDegraded,
  evidenceSearchDegraded,
  claimsUnverified,
}: {
  coverage?: ExtractionCoverage;
  provenance?: ExtractionProvenance;
  incompleteAnalysis?: boolean;
  verificationDegraded?: boolean;
  evidenceSearchDegraded?: boolean;
  claimsUnverified?: boolean;
}) {
  const caveats: Caveat[] = [];

  if (incompleteAnalysis) {
    caveats.push({
      key: "incomplete",
      tone: "negative",
      icon: <AlertTriangle size={15} />,
      summary: "The analysis did not complete",
      body: "Key verification or specialist-agent results were unavailable. The score is capped and should not be used as an investment recommendation.",
    });
  }

  // A pipeline failure and "this company is too early for anyone to have
  // written about it" call for very different reactions from an investor, so
  // they say different things.
  if (verificationDegraded) {
    caveats.push({
      key: "verification",
      tone: "caution",
      icon: <AlertTriangle size={15} />,
      summary: "Claim verification did not run",
      body: "The language model was unavailable while this deck was analysed, so the claims below were never checked against public sources. This says nothing about the company — nothing was established either way, and the score has not been reduced for it. Re-run the analysis to verify them.",
    });
  }

  if (evidenceSearchDegraded && !verificationDegraded) {
    caveats.push({
      key: "sources",
      tone: "accent",
      icon: <Info size={15} />,
      summary: "Claims were checked against a narrower set of sources",
      body: "The general web index was rate-limited during this analysis, so the fallback providers supplied the evidence. The verdicts below are real and count towards the score, but an unconfirmed claim here is more likely to mean we could not reach the right page than that the claim is wrong. Re-running later will search the open web again.",
    });
  }

  if (claimsUnverified && !incompleteAnalysis && !verificationDegraded) {
    caveats.push({
      key: "uncorroborated",
      tone: "caution",
      icon: <Info size={15} />,
      summary: "No deck claim could be independently corroborated",
      body: "Every checked claim was searched, but public sources had nothing specific enough to confirm or contradict it — normal for a company this early, and not a sign the analysis failed. The score already reflects this, and an INVEST verdict is withheld until at least two claims verify. Treat the numbers below as founder-reported.",
    });
  }

  // A silent fallback to regex is the defect this whole pass exists to make
  // impossible; the reader of the claims table is the person who needs to know
  // it fired.
  if (provenance?.is_fallback) {
    caveats.push({
      key: "extraction",
      tone: "negative",
      icon: <FileWarning size={15} />,
      summary: `Degraded extraction — ${provenance.method ?? "fallback"}`,
      body: provenance.warning
        ?? "This report's facts were extracted by the fallback extractor, which captures materially less of a deck than the schema-validated one.",
    });
  }

  const unrepresented = coverage?.unrepresented_slides ?? [];
  if (coverage?.available && unrepresented.length > 0) {
    caveats.push({
      key: "slides",
      tone: "neutral",
      icon: <ScanLine size={15} />,
      summary: `${unrepresented.length} slide${unrepresented.length === 1 ? "" : "s"} did not reach a structured field`,
      body: (
        <>
          <p style={{ margin: "0 0 10px" }}>
            Nothing from these slides appears in the findings below. Treat an
            &ldquo;insufficient data&rdquo; result on one of these subjects as a
            gap in the reading, not as evidence the deck is silent on it.
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {unrepresented.slice(0, 14).map((s) => (
              <Chip key={s.slide} size="sm">
                {s.slide}. {s.heading.slice(0, 28)}
              </Chip>
            ))}
          </div>
        </>
      ),
    });
  }

  if (!coverage?.available && caveats.length === 0) return null;

  /**
   * The server's interpretation, adjusted for where it is now shown.
   *
   * Two removals, no rewording. It ends "The unrepresented slides are listed
   * above" because that list used to sit above the sentence; here it is the
   * row directly below, so the pointer would send a reader the wrong way --
   * and every report already in the database carries the old wording, which is
   * why this happens here rather than in the generator. The "WARNING:" prefix
   * goes because the meter beside it is already red and already says LOW.
   * Every other word is the server's.
   */
  const interpretation = (coverage?.interpretation ?? "")
    .replace(/^WARNING:\s*/, "")
    .replace(/\s*The unrepresented slides are listed above\.\s*$/, "")
    .trim();

  const pct = coverage?.coverage_pct ?? 0;
  const tone: Tone =
    coverage?.verdict === "HIGH" ? "positive"
      : coverage?.verdict === "PARTIAL" ? "caution"
        : "negative";

  return (
    <Card padding={18} style={{ marginBottom: 16 }}>
      {coverage?.available && (
        <>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14, flexWrap: "wrap" }}>
            {/* No label here: the chapter heading directly above this panel
                already says what the figure is. */}
            <span className="vf-figure" style={{ fontSize: 52, color: `var(--${tone === "positive" ? "positive" : tone === "caution" ? "caution" : "negative"})` }}>
              {pct}%
            </span>
            {coverage.verdict && <Chip tone={tone} size="sm">{coverage.verdict}</Chip>}
            <span style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
              {coverage.represented_slides} of {coverage.content_slides} content slides reached a structured field
            </span>
          </div>

          <div style={{ margin: "12px 0 10px" }}>
            <GrowBar
              pct={pct}
              color={`var(--${tone === "positive" ? "positive" : tone === "caution" ? "caution" : "negative"})`}
              height={5}
            />
          </div>

          {interpretation && (
            <p style={{ margin: 0, fontSize: 13, lineHeight: 1.6, color: "var(--text-secondary)", maxWidth: "76ch" }}>
              {interpretation}
            </p>
          )}
        </>
      )}

      {caveats.length > 0 && (
        <div style={{ display: "grid", gap: 8, marginTop: coverage?.available ? 14 : 0 }}>
          {caveats.map((c) => (
            <Disclosure
              key={c.key}
              tone={c.tone}
              icon={c.icon}
              summary={c.summary}
              defaultOpen={false}
            >
              {c.body}
            </Disclosure>
          ))}
        </div>
      )}
    </Card>
  );
}
