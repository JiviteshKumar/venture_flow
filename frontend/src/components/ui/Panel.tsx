import type { CSSProperties, ReactNode } from "react";

/**
 * The three surface primitives the report screens are built from.
 *
 * These were declared inline at the top of Analysis.tsx, which meant any other
 * screen wanting the same surface had to copy them. Dashboard and UploadDeck
 * had each grown their own near-miss variants as a result. Defining them once
 * is what makes "one design system" true in the components as well as in the
 * token file.
 *
 * They read their colours from the CSS custom properties in
 * src/styles/tailwind.css rather than taking hex literals, so a token change
 * reaches them without edits here.
 */

export const Panel = ({
  children,
  style = {},
  accentColor,
  className = "",
}: {
  children: ReactNode;
  style?: CSSProperties;
  accentColor?: string;
  className?: string;
}) => (
  <div
    className={`vf-panel ${className}`.trim()}
    style={{ borderLeftColor: accentColor || "transparent", ...style }}
  >
    {children}
  </div>
);

/** Small uppercase section label. */
export const SLabel = ({
  children,
  color,
}: {
  children: ReactNode;
  color?: string;
}) => (
  <div className="vf-slabel" style={color ? { color } : undefined}>
    {children}
  </div>
);

/**
 * A single figure in a tinted pill.
 *
 * `value` is a pre-formatted string on purpose: this component must never
 * decide how a number is rendered, because that is where "absent" quietly
 * becomes "0". Format with src/utils/format.ts and pass the result.
 */
export const ScoreBadge = ({
  value,
  color,
  bg,
  border,
}: {
  value: ReactNode;
  color: string;
  bg: string;
  border: string;
}) => (
  <div
    style={{
      display: "inline-flex",
      alignItems: "center",
      padding: "6px 14px",
      borderRadius: "8px",
      background: bg,
      border: `1px solid ${border}`,
      fontFamily: "var(--font-mono)",
      fontSize: "15px",
      fontWeight: 600,
      color,
      letterSpacing: "-0.01em",
    }}
  >
    {value}
  </div>
);

export default Panel;
