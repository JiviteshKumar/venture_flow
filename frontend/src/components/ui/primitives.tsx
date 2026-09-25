import { useId, useState, type CSSProperties, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { ChevronDown } from "lucide-react";
import { DURATION, EASE_OUT } from "./Motion";

/**
 * The shared vocabulary of surfaces, labels, chips and buttons.
 *
 * WHY THIS FILE EXISTS
 *
 * Every screen used to declare its own version of these. Three pages each had
 * a card with a slightly different radius, a label at a slightly different
 * size, and a chip with a colour computed by appending an alpha suffix to a
 * hex string (`${color}14`). The result was an interface where no two panels
 * agreed, and where adding a fifth tone meant inventing a fifth palette.
 *
 * Every component below reads the tokens in src/styles/tailwind.css and takes
 * a `tone` from a fixed set rather than a colour. If a component cannot say
 * what a colour *means*, it does not get to use one.
 */

// ── Tones ────────────────────────────────────────────────────────────────────

export type Tone = "neutral" | "accent" | "positive" | "caution" | "negative";

const TONE: Record<Tone, { fg: string; tint: string; line: string }> = {
  neutral: { fg: "var(--text-secondary)", tint: "var(--surface-2)", line: "var(--border)" },
  accent: { fg: "var(--accent)", tint: "var(--accent-tint)", line: "var(--accent-line)" },
  positive: { fg: "var(--positive)", tint: "var(--positive-tint)", line: "var(--positive-line)" },
  caution: { fg: "var(--caution)", tint: "var(--caution-tint)", line: "var(--caution-line)" },
  negative: { fg: "var(--negative)", tint: "var(--negative-tint)", line: "var(--negative-line)" },
};

export const toneOf = (t: Tone) => TONE[t];

/** The tone a 0-100 score carries. Kept here so every screen agrees. */
export function scoreTone(score: number): Tone {
  if (score >= 70) return "positive";
  if (score >= 45) return "caution";
  return "negative";
}

// ── Label ────────────────────────────────────────────────────────────────────

/**
 * The small uppercase label above a value or a section.
 *
 * Inter, not mono. These are words -- "Extraction coverage", "Risk level" --
 * and setting a word in a monospaced face at 10px with 0.1em tracking makes
 * it read as a log line. Mono is for the figure underneath.
 */
export function Label({
  children,
  tone = "neutral",
  style,
}: {
  children: ReactNode;
  tone?: Tone;
  style?: CSSProperties;
}) {
  return (
    <div
      className="vf-label"
      style={{ color: tone === "neutral" ? undefined : TONE[tone].fg, ...style }}
    >
      {children}
    </div>
  );
}

// ── Card ─────────────────────────────────────────────────────────────────────

export function Card({
  children,
  tone,
  interactive = false,
  padding = 20,
  className = "",
  style,
  ...rest
}: {
  children: ReactNode;
  /** Tints the whole card. Use sparingly: a page of tinted cards has no hierarchy. */
  tone?: Tone;
  interactive?: boolean;
  padding?: number | string;
  className?: string;
  style?: CSSProperties;
} & Omit<React.HTMLAttributes<HTMLDivElement>, "style" | "className">) {
  const t = tone ? TONE[tone] : null;
  return (
    <div
      className={`vf-card${interactive ? " vf-card-interactive" : ""} ${className}`.trim()}
      style={{
        padding,
        ...(t ? { background: t.tint, borderColor: t.line } : null),
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  );
}

/** Title + optional one-line description + optional right-hand control. */
export function CardHead({
  title,
  hint,
  right,
  label,
}: {
  title: ReactNode;
  hint?: ReactNode;
  right?: ReactNode;
  /** An uppercase label above the title, for cards that need categorising. */
  label?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 16,
        marginBottom: hint ? 14 : 12,
      }}
    >
      <div style={{ minWidth: 0 }}>
        {label && <Label style={{ marginBottom: 6 }}>{label}</Label>}
        <h2
          style={{
            font: "inherit",
            fontSize: "var(--text-title)",
            fontWeight: 600,
            letterSpacing: "-0.01em",
            color: "var(--text-primary)",
            margin: 0,
            lineHeight: 1.25,
          }}
        >
          {title}
        </h2>
        {hint && (
          <p style={{ margin: "5px 0 0", fontSize: "var(--text-small)", color: "var(--text-muted)", lineHeight: 1.5, maxWidth: "64ch" }}>
            {hint}
          </p>
        )}
      </div>
      {right && <div style={{ flexShrink: 0 }}>{right}</div>}
    </div>
  );
}

// ── Chip ─────────────────────────────────────────────────────────────────────

/**
 * A small status pill.
 *
 * `mono` is opt-in and exists for chips whose content is a figure
 * ("52/100", "9 of 25"). A chip carrying words stays in Inter.
 */
export function Chip({
  children,
  tone = "neutral",
  mono = false,
  icon,
  size = "md",
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  mono?: boolean;
  icon?: ReactNode;
  size?: "sm" | "md";
  /** The long form, when the chip carries an abbreviation. */
  title?: string;
}) {
  const t = TONE[tone];
  return (
    <span
      className={mono ? "vf-num" : undefined}
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        background: t.tint,
        border: `1px solid ${t.line}`,
        color: t.fg,
        borderRadius: "var(--radius-pill)",
        padding: size === "sm" ? "2px 8px" : "4px 11px",
        fontSize: size === "sm" ? 11 : 12,
        fontWeight: 600,
        lineHeight: 1.5,
        whiteSpace: "nowrap",
      }}
    >
      {icon}
      {children}
    </span>
  );
}

// ── Button ───────────────────────────────────────────────────────────────────

export function Button({
  children,
  variant = "secondary",
  size = "md",
  icon,
  iconRight,
  full = false,
  style,
  ...rest
}: {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "inverted";
  size?: "sm" | "md" | "lg";
  icon?: ReactNode;
  iconRight?: ReactNode;
  full?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const pad = size === "lg" ? "13px 22px" : size === "sm" ? "6px 12px" : "9px 16px";
  const font = size === "lg" ? 15 : size === "sm" ? 12.5 : 13.5;
  return (
    <button
      className={`vf-btn vf-btn-${variant}`}
      style={{
        display: full ? "flex" : "inline-flex",
        width: full ? "100%" : undefined,
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        padding: pad,
        fontSize: font,
        fontWeight: 600,
        fontFamily: "var(--font-sans)",
        borderRadius: "var(--radius-sm)",
        cursor: rest.disabled ? "not-allowed" : "pointer",
        transition: "background var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-base) var(--ease-out), transform var(--dur-fast) var(--ease-out)",
        ...style,
      }}
      {...rest}
    >
      {icon}
      {children}
      {iconRight}
    </button>
  );
}

/** Button styling lives in CSS so hover/active/disabled do not need JS state. */
export function ButtonStyles() {
  return (
    <style>{`
      .vf-btn { border: 1px solid transparent; }
      .vf-btn:disabled { opacity: 0.55; }
      .vf-btn-primary {
        background: var(--accent-solid); color: var(--on-accent);
        box-shadow: 0 1px 2px rgba(15,23,42,0.10), 0 6px 18px rgba(29,111,232,0.22);
      }
      .vf-btn-primary:hover:not(:disabled) { background: var(--accent-strong); transform: translateY(-1px); }
      .vf-btn-primary:active:not(:disabled) { transform: translateY(0); }
      .vf-btn-secondary {
        background: var(--surface); color: var(--text-primary); border-color: var(--border-strong);
      }
      .vf-btn-secondary:hover:not(:disabled) { background: var(--surface-2); }
      .vf-btn-ghost { background: transparent; color: var(--text-secondary); }
      .vf-btn-ghost:hover:not(:disabled) { background: var(--surface-2); color: var(--text-primary); }
      .vf-btn-inverted {
        background: color-mix(in srgb, var(--text-on-ink) 12%, transparent); color: var(--text-on-ink);
        border-color: color-mix(in srgb, var(--text-on-ink) 22%, transparent);
      }
      .vf-btn-inverted:hover:not(:disabled) { background: color-mix(in srgb, var(--text-on-ink) 20%, transparent); }
    `}</style>
  );
}

// ── Stat ─────────────────────────────────────────────────────────────────────

/**
 * One figure with its label.
 *
 * `value` is a pre-formatted string on purpose: this component must never
 * decide how a number is rendered, because that is where "absent" quietly
 * becomes "0". Format with src/utils/format.ts and pass the result.
 */
export function Stat({
  label,
  value,
  hint,
  tone = "neutral",
  size = "md",
  numeric = true,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  tone?: Tone;
  size?: "sm" | "md" | "lg";
  /**
   * Kept for the two callers that pass a company name. It no longer switches
   * the typeface -- see .vf-figure in styles/tailwind.css for why choosing a
   * face per value is what made a row of three stats read as three
   * instruments -- it only relaxes the tabular figure spacing, which does
   * nothing useful to a word.
   */
  numeric?: boolean;
}) {
  const fontSize = size === "lg" ? 34 : size === "sm" ? 22 : 27;
  return (
    <div>
      <Label style={{ marginBottom: 7 }}>{label}</Label>
      <div
        className="vf-figure"
        style={{
          fontSize,
          lineHeight: 1.1,
          fontVariantNumeric: numeric ? "tabular-nums" : "normal",
          color: tone === "neutral" ? "var(--text-primary)" : TONE[tone].fg,
        }}
      >
        {value}
      </div>
      {hint && (
        <div style={{ marginTop: 6, fontSize: 12.5, color: "var(--text-muted)", lineHeight: 1.45 }}>
          {hint}
        </div>
      )}
    </div>
  );
}

// ── Disclosure ───────────────────────────────────────────────────────────────

/**
 * Collapsed detail.
 *
 * The report screen previously stacked three full-width warning panels above
 * the content -- roughly 350 pixels of caveat before a reader reached a single
 * finding. The caveats matter and are not being removed; they are being put
 * behind their own headline, so the reader chooses when to read the long
 * version. The headline still states the fact.
 */
export function Disclosure({
  summary,
  children,
  tone = "neutral",
  defaultOpen = false,
  icon,
  meta,
}: {
  summary: ReactNode;
  children: ReactNode;
  tone?: Tone;
  defaultOpen?: boolean;
  icon?: ReactNode;
  /** Right-aligned figure or chip, visible while collapsed. */
  meta?: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const reduced = useReducedMotion();
  const id = useId();
  const t = TONE[tone];

  return (
    <div
      style={{
        background: tone === "neutral" ? "var(--surface)" : t.tint,
        border: `1px solid ${tone === "neutral" ? "var(--border)" : t.line}`,
        borderRadius: "var(--radius)",
        overflow: "hidden",
      }}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 12,
          padding: "13px 16px",
          background: "transparent",
          border: "none",
          cursor: "pointer",
          textAlign: "left",
          font: "inherit",
        }}
      >
        {icon && <span style={{ display: "flex", color: t.fg, flexShrink: 0 }}>{icon}</span>}
        <span style={{ flex: 1, minWidth: 0, fontSize: 13.5, fontWeight: 600, color: tone === "neutral" ? "var(--text-primary)" : t.fg }}>
          {summary}
        </span>
        {meta}
        <motion.span
          animate={{ rotate: open ? 180 : 0 }}
          transition={{ duration: reduced ? 0 : DURATION.fast, ease: EASE_OUT }}
          style={{ display: "flex", color: "var(--text-muted)", flexShrink: 0 }}
        >
          <ChevronDown size={16} />
        </motion.span>
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id={id}
            initial={reduced ? { opacity: 0 } : { height: 0, opacity: 0 }}
            animate={reduced ? { opacity: 1 } : { height: "auto", opacity: 1 }}
            exit={reduced ? { opacity: 0 } : { height: 0, opacity: 0 }}
            transition={{ duration: reduced ? 0 : DURATION.base, ease: EASE_OUT }}
            style={{ overflow: "hidden" }}
          >
            <div style={{ padding: "0 16px 16px", fontSize: 13.5, lineHeight: 1.65, color: "var(--text-secondary)" }}>
              {children}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// ── Empty state ──────────────────────────────────────────────────────────────

export function EmptyState({
  icon,
  title,
  body,
  action,
}: {
  icon?: ReactNode;
  title: string;
  body?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div style={{ textAlign: "center", padding: "44px 24px", maxWidth: 440, margin: "0 auto" }}>
      {icon && (
        <div
          style={{
            width: 44, height: 44, borderRadius: 12, margin: "0 auto 16px",
            display: "grid", placeItems: "center",
            background: "var(--accent-tint)", color: "var(--accent)",
          }}
        >
          {icon}
        </div>
      )}
      <div className="vf-display" style={{ fontSize: 22, marginBottom: body ? 8 : 18 }}>{title}</div>
      {body && (
        <p style={{ margin: "0 0 18px", fontSize: 13.5, lineHeight: 1.6, color: "var(--text-muted)" }}>{body}</p>
      )}
      {action}
    </div>
  );
}

// ── Skeleton ─────────────────────────────────────────────────────────────────

/**
 * A loading placeholder shaped like the thing that is coming.
 *
 * Shown instead of a spinner because a spinner says "something is happening"
 * while a skeleton says "a list of five rows is happening" -- the page does
 * not jump when the data lands.
 */
export function Skeleton({ height = 16, width = "100%", radius = 6, style }: {
  height?: number | string;
  width?: number | string;
  radius?: number;
  style?: CSSProperties;
}) {
  return (
    <div
      aria-hidden="true"
      className="vf-skeleton"
      style={{ height, width, borderRadius: radius, ...style }}
    />
  );
}

export function SkeletonStyles() {
  return (
    <style>{`
      .vf-skeleton {
        background: linear-gradient(90deg, var(--surface-2) 25%, var(--surface-3) 37%, var(--surface-2) 63%);
        background-size: 400% 100%;
        animation: vf-shimmer 1.4s ease-in-out infinite;
      }
      @keyframes vf-shimmer {
        from { background-position: 100% 50%; }
        to { background-position: 0 50%; }
      }
      :root[data-motion="off"] .vf-skeleton { animation: none; background: var(--surface-2); }
      
    `}</style>
  );
}
