import {
  Area, AreaChart, Bar, BarChart, Cell, PolarAngleAxis, PolarGrid, Radar,
  RadarChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import type { ReactNode } from "react";

/**
 * Every chart in the product, with one theme.
 *
 * Recharts ships a light-grey, blue-by-default look that belongs to no
 * product. These wrappers fix the grid, the axes, the type and the palette
 * once, so a chart added in six months cannot arrive in a different accent.
 *
 * THE RULES THEY ENCODE
 *
 *   - no gridlines on the category axis: they fence values in without helping
 *     anyone read them
 *   - no axis lines or ticks: the labels are the axis
 *   - one accent, and semantic colour only where the colour MEANS something
 *     (a verdict, a risk level) rather than to tell two bars apart
 *   - every chart states its own units in a caption, because a number without
 *     a unit is the most common way a chart lies
 *   - a chart with nothing to show renders a sentence, not an empty frame
 */

const AXIS = { fill: "var(--viz-axis)", fontSize: 11, fontWeight: 500 };

function Frame({
  label,
  caption,
  height = 190,
  children,
  empty,
}: {
  label: string;
  caption?: string;
  height?: number;
  children: ReactNode;
  /** Shown instead of the chart when there is nothing to plot. */
  empty?: string;
}) {
  return (
    <figure className="ch-frame">
      <style>{CH_CSS}</style>
      <figcaption>
        <span className="vf-label">{label}</span>
        {caption && <span className="ch-caption">{caption}</span>}
      </figcaption>
      {empty ? (
        <p className="ch-empty">{empty}</p>
      ) : (
        <div style={{ height }}>
          <ResponsiveContainer width="100%" height="100%">
            {children as never}
          </ResponsiveContainer>
        </div>
      )}
    </figure>
  );
}

/** One shared tooltip, so no chart invents its own. */
function ChartTip({ active, payload, label, unit }: {
  active?: boolean;
  payload?: Array<{ value: number; name: string; payload?: Record<string, unknown> }>;
  label?: string | number;
  unit?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="ch-tip">
      {label !== undefined && <div className="ch-tip-label">{label}</div>}
      {payload.map((p) => (
        <div key={p.name} className="ch-tip-row">
          <span className="vf-num">{p.value}</span>{unit ? ` ${unit}` : ""}
        </div>
      ))}
    </div>
  );
}

// ── Score distribution ───────────────────────────────────────────────────────

/**
 * Where a portfolio's scores fall, in ten-point buckets.
 *
 * The base-rate line matters more than the bars: it is the level a company
 * with no signal either way would score, so a distribution sitting on top of
 * it is the honest reading of "our deal flow looks average".
 */
export function ScoreDistribution({ scores, baseRate = 49 }: { scores: number[]; baseRate?: number }) {
  if (scores.length === 0) {
    return <Frame label="Score distribution" empty="No analyses on file yet.">{null}</Frame>;
  }
  const buckets = Array.from({ length: 10 }, (_, i) => ({
    band: `${i * 10}`,
    lower: i * 10,
    count: 0,
  }));
  for (const s of scores) {
    const i = Math.max(0, Math.min(9, Math.floor(s / 10)));
    buckets[i].count += 1;
  }
  return (
    <Frame label="Score distribution" caption={`${scores.length} analyses · base rate ${baseRate}`}>
      <BarChart data={buckets} margin={{ top: 6, right: 4, left: 0, bottom: 0 }}>
        <XAxis dataKey="band" tick={AXIS} axisLine={false} tickLine={false} />
        <YAxis tick={AXIS} axisLine={false} tickLine={false} allowDecimals={false} width={28} />
        <Tooltip content={<ChartTip unit="analyses" />} cursor={{ fill: "var(--neutral-quiet)" }} />
        <Bar dataKey="count" radius={[3, 3, 0, 0]} isAnimationActive animationDuration={700}>
          {buckets.map((b) => (
            <Cell
              key={b.band}
              fill={b.lower + 10 <= baseRate ? "var(--critical)"
                : b.lower >= baseRate ? "var(--verified)" : "var(--caution)"}
              fillOpacity={0.85}
            />
          ))}
        </Bar>
      </BarChart>
    </Frame>
  );
}

// ── Claim verdicts ───────────────────────────────────────────────────────────

/** What happened to the claims that were checked. */
export function ClaimBreakdown({
  supported, refuted, unsettled,
}: { supported: number; refuted: number; unsettled: number }) {
  const total = supported + refuted + unsettled;
  if (total === 0) {
    return <Frame label="Claim verdicts" empty="No claim was checked for this report.">{null}</Frame>;
  }
  const data = [
    { name: "Supported", value: supported, fill: "var(--verified)" },
    { name: "Unsettled", value: unsettled, fill: "var(--viz-5)" },
    { name: "Refuted", value: refuted, fill: "var(--critical)" },
  ].filter((d) => d.value > 0);

  return (
    <Frame label="Claim verdicts" caption={`${total} checked`} height={150}>
      <BarChart data={[Object.fromEntries(data.map((d) => [d.name, d.value]))]} layout="vertical" margin={{ top: 0, right: 0, left: 0, bottom: 0 }} stackOffset="expand">
        <XAxis type="number" hide />
        <YAxis type="category" hide />
        <Tooltip content={<ChartTip unit="claims" />} cursor={false} />
        {data.map((d, i) => (
          <Bar
            key={d.name}
            dataKey={d.name}
            stackId="a"
            fill={d.fill}
            fillOpacity={0.9}
            radius={i === 0 ? [4, 0, 0, 4] : i === data.length - 1 ? [0, 4, 4, 0] : 0}
            isAnimationActive
            animationDuration={700}
          />
        ))}
      </BarChart>
    </Frame>
  );
}

// ── Team capability ──────────────────────────────────────────────────────────

/** The team specialist's own scores, per capability it assessed. */
export function CapabilityRadar({
  capabilities,
}: { capabilities: Array<{ area: string; score: number }> }) {
  if (capabilities.length < 3) {
    return (
      <Frame
        label="Team capability"
        empty="The team specialist did not return enough assessed areas to plot. Its findings are listed below."
      >{null}</Frame>
    );
  }
  return (
    <Frame label="Team capability" caption="assessed from the deck, 0–100" height={240}>
      <RadarChart data={capabilities} outerRadius="72%">
        <PolarGrid stroke="var(--viz-grid)" />
        <PolarAngleAxis dataKey="area" tick={AXIS} />
        <Tooltip content={<ChartTip />} />
        <Radar
          dataKey="score"
          stroke="var(--viz-1)"
          fill="var(--viz-1)"
          fillOpacity={0.16}
          strokeWidth={2}
          isAnimationActive
          animationDuration={800}
        />
      </RadarChart>
    </Frame>
  );
}

// ── Founder evidence ─────────────────────────────────────────────────────────

export type FounderPoint = {
  name: string;
  /** CONSISTENT | CONTRADICTS | NOT_ENOUGH_INFO, from agents/founder_verifier.py. */
  assessment?: string;
  /** The verifier's own confidence, 0-1. */
  confidence?: number;
  /** Pages the background check read. */
  sources?: string[];
  /** "deck" when the deck named them, "external_research" when we searched. */
  origin?: string;
};

/** Distinct hosts, because five pages on one site is one publication. */
function distinctHosts(urls: string[]): number {
  const hosts = new Set<string>();
  for (const url of urls) {
    try { hosts.add(new URL(url).hostname.replace(/^www\./, "")); }
    catch { hosts.add(url); }
  }
  return hosts.size;
}

const AGREEMENT: Record<string, number> = {
  CONSISTENT: 100,
  NOT_ENOUGH_INFO: 40,
  CONTRADICTS: 0,
};

/** The five axes, and the recorded fact each one reads. */
const FOUNDER_AXES = [
  "Corroboration",
  "Independence",
  "Agreement",
  "Confidence",
  "Disclosed",
] as const;

/**
 * How well each founder is established. NOT how good they are.
 *
 * WHY THE DISTINCTION IS THE WHOLE POINT
 *
 * The obvious chart for a page headed "Founder Analysis" is a radar scoring
 * each founder's technical depth, commercial instinct and so on. There is no
 * honest way to draw that here: this pipeline has never met these people. It
 * has a name, some pages that mention it, and a verifier's reading of whether
 * those pages agree with the deck. A radar of a stranger's abilities built
 * from web snippets would be the most confident-looking fabrication in the
 * product, and the team radar it replaces was already halfway there --
 * scoring "Commercial Execution 80" for a deck with no team slide.
 *
 * So every axis is a recorded fact about the EVIDENCE, and the chart says so
 * in its caption:
 *
 *   Corroboration   distinct sites that mention this founder, 5+ reads full
 *   Independence    how much of that is separate publications rather than
 *                   several pages of the same one
 *   Agreement       the verifier's verdict: consistent with the deck, unable
 *                   to tell, or contradicting it
 *   Confidence      the verifier's own confidence in that verdict
 *   Disclosed       whether the deck named them, or we had to go and find
 *                   them -- a name a founder put in writing is stronger
 *                   evidence than one this tool recovered
 *
 * A reader who wants the underlying pages has them: they are listed as links
 * directly beneath this chart.
 */
export function FounderRadar({ founders }: { founders: FounderPoint[] }) {
  const usable = founders.filter((f) => f.name);
  if (usable.length === 0) {
    return (
      <Frame
        label="Founder evidence"
        empty="No founder has been established for this deck, so there is nothing to plot. The deck named none, and the public search is reported below."
      >{null}</Frame>
    );
  }

  // Recharts wants one row per axis, one key per founder.
  const rows = FOUNDER_AXES.map((axis) => {
    const row: Record<string, string | number> = { axis };
    for (const f of usable) {
      const sources = f.sources ?? [];
      const hosts = distinctHosts(sources);
      const value =
        axis === "Corroboration" ? Math.min(100, (hosts / 5) * 100)
        : axis === "Independence" ? (sources.length ? (hosts / sources.length) * 100 : 0)
        : axis === "Agreement" ? (AGREEMENT[(f.assessment || "").toUpperCase()] ?? 40)
        : axis === "Confidence" ? Math.max(0, Math.min(100, (f.confidence ?? 0) * 100))
        // A name in the deck is a claim its authors are answerable for. One we
        // found is real evidence, and weaker evidence.
        : f.origin === "deck" ? 100 : 45;
      row[f.name] = Math.round(value);
    }
    return row;
  });

  const PALETTE = ["var(--viz-1)", "var(--viz-2)", "var(--viz-3)", "var(--viz-4)"];

  return (
    <Frame
      label="Founder evidence"
      caption="how well each name is established, 0-100 - not an assessment of the person"
      height={260}
    >
      <RadarChart data={rows} outerRadius="70%">
        <PolarGrid stroke="var(--viz-grid)" />
        <PolarAngleAxis dataKey="axis" tick={AXIS} />
        <Tooltip content={<ChartTip />} />
        {usable.slice(0, 4).map((f, i) => (
          <Radar
            key={f.name}
            name={f.name}
            dataKey={f.name}
            stroke={PALETTE[i % PALETTE.length]}
            fill={PALETTE[i % PALETTE.length]}
            fillOpacity={0.14}
            strokeWidth={2}
            isAnimationActive
            animationDuration={800}
          />
        ))}
      </RadarChart>
    </Frame>
  );
}

// ── Score history ────────────────────────────────────────────────────────────

/** One company's score across the times it has been analysed. */
export function ScoreHistory({ points }: { points: Array<{ label: string; score: number }> }) {
  if (points.length < 2) {
    return (
      <Frame label="Score history" empty="This is the first analysis on file for this company.">{null}</Frame>
    );
  }
  return (
    <Frame label="Score history" caption="0–100 per analysis">
      <AreaChart data={points} margin={{ top: 6, right: 6, left: 0, bottom: 0 }}>
        <defs>
          <linearGradient id="vf-score-grad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--viz-1)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--viz-1)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <XAxis dataKey="label" tick={AXIS} axisLine={false} tickLine={false} />
        <YAxis domain={[0, 100]} tick={AXIS} axisLine={false} tickLine={false} width={34} />
        <Tooltip content={<ChartTip />} cursor={{ stroke: "var(--line-strong)" }} />
        <Area
          type="monotone" dataKey="score"
          stroke="var(--viz-1)" strokeWidth={2}
          fill="url(#vf-score-grad)"
          isAnimationActive animationDuration={900}
        />
      </AreaChart>
    </Frame>
  );
}

const CH_CSS = `
  .ch-frame { margin: 0; }
  .ch-frame figcaption {
    display: flex; align-items: baseline; gap: 10px;
    margin-bottom: 12px; flex-wrap: wrap;
  }
  .ch-caption { font-size: var(--t-micro); color: var(--text-3); }
  .ch-empty {
    margin: 0; padding: 22px 0; font-size: var(--t-small);
    line-height: 1.6; color: var(--text-3); max-width: 46ch;
  }
  .ch-tip {
    background: var(--surface-3); border: 1px solid var(--line-strong);
    border-radius: var(--r-sm); padding: 8px 11px;
    font-size: var(--t-micro); color: var(--text);
    box-shadow: var(--e-2);
  }
  .ch-tip-label { color: var(--text-3); margin-bottom: 3px; }
  .ch-tip-row { font-weight: 600; }
  .recharts-surface:focus { outline: none; }
`;
