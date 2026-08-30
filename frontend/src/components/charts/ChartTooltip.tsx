/**
 * Recharts tooltip in the app's own styling.
 *
 * Two near-identical copies of this existed, one in Analysis.tsx and one in
 * Dashboard.tsx, differing only in shadow opacity and letter-spacing — the
 * classic result of copy-paste rather than a deliberate difference. Analysis's
 * copy also hardcoded a `$…B` suffix on every value, which was correct for the
 * one chart it served and wrong for anything else.
 *
 * This version takes a `formatValue` prop instead of assuming a unit, so a
 * caller states what its numbers mean rather than inheriting another screen's
 * assumption.
 */
type TooltipPayloadEntry = {
  name?: string;
  value?: number | string;
  stroke?: string;
  fill?: string;
};

type Props = {
  active?: boolean;
  payload?: TooltipPayloadEntry[];
  label?: string | number;
  /** Render a raw value. Defaults to plain string conversion — never a unit. */
  formatValue?: (value: number | string | undefined) => string;
  /** Show one row per series with its colour swatch, vs. a single big figure. */
  multiSeries?: boolean;
};

export const ChartTooltip = ({
  active,
  payload,
  label,
  formatValue = (v) => (v === undefined || v === null ? "—" : String(v)),
  multiSeries = false,
}: Props) => {
  if (!active || !payload?.length) return null;

  return (
    <div
      style={{
        background: "rgba(255,255,255,0.98)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: "12px 16px",
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        boxShadow: "var(--shadow-lifted, 0 12px 40px rgba(15,23,42,0.12))",
        minWidth: 130,
      }}
    >
      <div
        style={{
          color: "var(--text-muted)",
          marginBottom: 8,
          fontSize: 9.5,
          letterSpacing: "0.1em",
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>

      {multiSeries ? (
        payload.map((p, i) => (
          <div
            key={i}
            style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}
          >
            <div
              style={{
                width: 5,
                height: 5,
                borderRadius: "50%",
                background: p.stroke || p.fill,
              }}
            />
            <span style={{ color: "var(--text-muted)", flex: 1 }}>{p.name}</span>
            <span style={{ color: "var(--text-primary)", fontWeight: 600 }}>
              {formatValue(p.value)}
            </span>
          </div>
        ))
      ) : (
        <div style={{ color: "var(--accent)", fontSize: 15, fontWeight: 600 }}>
          {formatValue(payload[0]?.value)}
        </div>
      )}
    </div>
  );
};

export default ChartTooltip;
