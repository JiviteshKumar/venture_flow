import { motion, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";
import { DURATION, EASE_OUT } from "./Motion";

/**
 * The dark band that opens a page.
 *
 * WHY IT EXISTS
 *
 * Three screens each grew their own pale header: a thin eyebrow, a title, a
 * subtitle, a shimmering gradient rule and a row of status chips, all on white,
 * all the same weight as the content beneath them. None of them established
 * where the page started or what it was for.
 *
 * This is one band, shared, matching the report's VerdictHero and the sign-in
 * screen. Inverting it is the cheapest way to open a page made of white cards
 * without adding another border or accent colour to a layout that had too many
 * already.
 *
 * WHAT IT DOES NOT CARRY
 *
 * No status lights. The headers this replaces had "Intelligence Report · Live"
 * with a pulsing dot, and "Bull Agent Active / Bear Agent Active / Fact-Check
 * Live" -- all lit permanently and identically whether anything was running or
 * not. A light that is always green reports nothing, and this product's whole
 * argument is that it does not show things it cannot support.
 */
export default function PageHero({
  eyebrow,
  title,
  subtitle,
  actions,
  compact = false,
}: {
  eyebrow: string;
  title: ReactNode;
  subtitle?: ReactNode;
  /** Right-aligned controls: an export button, a deck id. */
  actions?: ReactNode;
  /** Slightly tighter, for pages whose content starts immediately. */
  compact?: boolean;
}) {
  const reduced = useReducedMotion();

  return (
    <header className={`ph-root${compact ? " ph-compact" : ""}`}>
      <style>{`
        .ph-root {
          position: relative; overflow: hidden;
          padding: 40px 32px 34px;
          background: radial-gradient(120% 150% at 0% 0%, #16355F 0%, #0B1120 55%, #070B14 100%);
          color: #E8EEF9;
        }
        .ph-compact { padding: 30px 32px 26px; }

        .ph-aura {
          position: absolute; inset: -40% -20%;
          background:
            radial-gradient(38% 38% at 24% 30%, rgba(29,111,232,0.28), transparent 70%),
            radial-gradient(30% 30% at 74% 62%, rgba(14,166,106,0.16), transparent 70%);
          filter: blur(60px); pointer-events: none;
          animation: ph-drift 26s ease-in-out infinite alternate;
        }
        @keyframes ph-drift {
          from { transform: translate3d(-2%, -1%, 0) scale(1); }
          to   { transform: translate3d(3%, 2%, 0) scale(1.07); }
        }
        @media (prefers-reduced-motion: reduce) { .ph-aura { animation: none; } }

        .ph-inner {
          position: relative; z-index: 1;
          display: flex; align-items: flex-end; justify-content: space-between;
          gap: 32px; flex-wrap: wrap;
        }
        .ph-eyebrow {
          font-family: var(--font-mono); font-size: 9.5px; letter-spacing: 0.18em;
          text-transform: uppercase; color: rgba(232,238,249,0.52); margin-bottom: 13px;
        }
        .ph-title {
          font-family: var(--font-display);
          font-size: clamp(34px, 4vw, 52px); line-height: 1.04;
          letter-spacing: -0.022em; color: #FFFFFF; margin: 0;
        }
        .ph-subtitle {
          font-family: var(--font-sans);
          font-size: 14px; line-height: 1.65; margin: 12px 0 0;
          color: rgba(232,238,249,0.70); max-width: 58ch;
        }
        .ph-actions { display: flex; align-items: center; gap: 10px; }

        @media (max-width: 900px) {
          .ph-root, .ph-compact { padding: 26px 20px 22px; }
          .ph-inner { gap: 18px; }
        }
      `}</style>

      <div className="ph-aura" aria-hidden="true" />
      <div className="ph-inner">
        <div style={{ minWidth: 0 }}>
          <div className="ph-eyebrow">{eyebrow}</div>
          <motion.h1
            className="ph-title"
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: DURATION.slow, ease: EASE_OUT }}
          >
            {title}
          </motion.h1>
          {subtitle && <p className="ph-subtitle">{subtitle}</p>}
        </div>
        {actions && <div className="ph-actions">{actions}</div>}
      </div>
    </header>
  );
}
