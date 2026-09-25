import { useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";
import { DURATION, EASE_OUT } from "./Motion";
import { Label, toneOf, type Tone } from "./primitives";

/**
 * A card that states one finding, and turns over to show the working.
 *
 * WHY IT TURNS OVER RATHER THAN SHOWING EVERYTHING
 *
 * Each of these findings has a headline (a figure and a verdict) and a
 * justification (which sources, which slides, what was missing). Printing both
 * for four findings put roughly six hundred words on screen before the reader
 * had decided which of the four they cared about. The headline is what you
 * scan; the working is what you check. Scanning comes first.
 *
 * WHY NOT A CSS BACKFACE FLIP
 *
 * A `backface-visibility: hidden` flip keeps the back face in the document
 * while it is invisible, so screen readers announce both sides at once and
 * find-in-page matches text nobody can see. This crossfades the two faces and
 * animates the height instead: only the visible face is mounted, the button
 * carries `aria-expanded`, and the card still reads as physical because it
 * tilts very slightly as it turns.
 */
export default function InsightCard({
  label,
  value,
  verdict,
  tone = "neutral",
  icon,
  children,
  backLabel = "How this was reached",
}: {
  /** The dimension: "Market evidence", "Risk level". */
  label: string;
  /** The headline figure. Pre-formatted -- never let a component invent "0". */
  value: ReactNode;
  /** One line, plain words, on what the figure means. */
  verdict: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
  /** The working: sources, counts, what was not established. */
  children: ReactNode;
  backLabel?: string;
}) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotion();
  const t = toneOf(tone);

  return (
    <motion.div
      layout={!reduced}
      transition={{ duration: reduced ? 0 : DURATION.base, ease: EASE_OUT }}
      style={{ perspective: 1000, height: "100%" }}
    >
      <motion.button
        type="button"
        aria-expanded={open}
        data-cursor={open ? "Back" : "Turn"}
        onClick={() => setOpen((o) => !o)}
        layout={!reduced}
        whileHover={reduced ? undefined : { y: -2 }}
        animate={reduced ? undefined : { rotateX: open ? [0, -6, 0] : [0, 6, 0] }}
        transition={{ duration: reduced ? 0 : DURATION.base, ease: EASE_OUT }}
        className="vf-card vf-insight"
        style={{
          width: "100%",
          height: "100%",
          textAlign: "left",
          padding: 18,
          cursor: "pointer",
          font: "inherit",
          display: "block",
          transformStyle: "preserve-3d",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 12 }}>
          {icon && (
            <span
              style={{
                width: 26, height: 26, borderRadius: 7, flexShrink: 0,
                display: "grid", placeItems: "center",
                background: t.tint, color: t.fg,
              }}
            >
              {icon}
            </span>
          )}
          <Label style={{ margin: 0, whiteSpace: "nowrap" }}>{label}</Label>
          <span
            className="vf-insight-cue"
            style={{ marginLeft: "auto", display: "flex", color: "var(--text-faint)" }}
            aria-hidden="true"
          >
            <ArrowUpRight size={15} />
          </span>
        </div>

        <AnimatePresence mode="wait" initial={false}>
          {open ? (
            <motion.div
              key="back"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: reduced ? 0 : DURATION.fast }}
            >
              <div className="vf-label" style={{ marginBottom: 8 }}>{backLabel}</div>
              <div style={{ fontSize: 13, lineHeight: 1.65, color: "var(--text-secondary)" }}>
                {children}
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="front"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: reduced ? 0 : DURATION.fast }}
            >
              {/* One face for every value, whether it is "78%", "2/5" or
                  "Moderate". Choosing per value is what made a row of three
                  cards read as three different instruments. */}
              <div
                className="vf-figure"
                style={{ fontSize: 34, color: t.fg }}
              >
                {value}
              </div>
              <div style={{ marginTop: 8, fontSize: 13, lineHeight: 1.55, color: "var(--text-muted)" }}>
                {verdict}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </motion.button>
    </motion.div>
  );
}

export function InsightCardStyles() {
  return (
    <style>{`
      .vf-insight { transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-base) var(--ease-out); }
      .vf-insight:hover { border-color: var(--border-strong); box-shadow: var(--shadow-raised); }
      .vf-insight:hover .vf-insight-cue { color: var(--accent); }
      .vf-insight .vf-insight-cue { transition: color var(--dur-fast) var(--ease-out); }
    `}</style>
  );
}
