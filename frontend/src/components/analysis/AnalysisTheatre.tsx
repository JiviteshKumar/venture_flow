import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Loader2, Minus, X } from "lucide-react";

/**
 * The investigation, while it is happening.
 *
 * WHAT DRIVES IT
 *
 * Nothing here is on a timer. The backend writes its current step to the job
 * row (ventureflow_agent._stage) and AppContext polls it; this maps those
 * seven real strings onto the specialists that produce them:
 *
 *   "Verifying claims against live web search"          -> claims
 *   "Detecting risk signals in the deck"                -> risk
 *   "Checking founder backgrounds..."                   -> founders
 *   "Searching public sources for undisclosed founders" -> founders
 *   "Running market, team, bull and bear agents"        -> market, team, bull, bear
 *   "Retrieving evidence from prior reports"            -> memory
 *   "Writing the investment memo"                       -> memo
 *
 * The fifth stage lights four nodes at once because the pipeline genuinely
 * runs those four together. That is the one moment this picture is allowed to
 * claim parallelism, and it is claiming it because it is true.
 *
 * WHY THE NODES ARE HTML AND THE LINES ARE SVG
 *
 * The labels are real text: selectable, translatable, and announced by a
 * screen reader in the order the work happens. Only the geometry -- the orbit
 * and the connectors -- is drawn, because that is the part text cannot do.
 * Putting the whole scene in a canvas would have made every agent's status
 * invisible to anything that is not an eye.
 *
 * WHAT IT SHOWS WHEN SOMETHING FAILS
 *
 * `degraded` marks the specialists that did not run. An agent that failed is
 * drawn as failed rather than left looking idle, because "we did not check" and
 * "we checked and found nothing" are the two conclusions this product exists
 * to keep apart.
 */

export type AgentId =
  | "claims" | "risk" | "founders" | "market" | "team" | "bull" | "bear" | "memory" | "memo";

export type AgentState = "idle" | "active" | "done" | "failed";

type Agent = {
  id: AgentId;
  label: string;
  /** What this specialist actually does, in one line. */
  role: string;
  /** Position on the orbit, in degrees clockwise from twelve o'clock. */
  angle: number;
  /** Two rings: the closer one for the work that runs first. */
  ring: 0 | 1;
};

const AGENTS: Agent[] = [
  { id: "claims",   label: "Claims",    role: "Checks the deck's claims against live web search", angle: 0,   ring: 0 },
  { id: "risk",     label: "Risk",      role: "Screens the deck for disclosure and financial risk", angle: 51,  ring: 0 },
  { id: "founders", label: "Founders",  role: "Searches public evidence for the named founders",    angle: 103, ring: 0 },
  { id: "market",   label: "Market",    role: "Sizes and evidences the market case",                angle: 154, ring: 1 },
  { id: "team",     label: "Team",      role: "Assesses team capability from the deck",             angle: 205, ring: 1 },
  { id: "bull",     label: "Bull",      role: "Argues the strongest case for the company",          angle: 257, ring: 1 },
  { id: "bear",     label: "Bear",      role: "Argues the strongest case against it",               angle: 308, ring: 1 },
  { id: "memory",   label: "Comparables", role: "Retrieves evidence from companies already analysed", angle: 334, ring: 0 },
  { id: "memo",     label: "Memo",      role: "Writes the investment memo over the computed score",  angle: 180, ring: 0 },
];

/** The real stage strings, in the order the pipeline emits them. */
const STAGE_MAP: Array<{ match: string; agents: AgentId[] }> = [
  { match: "verifying claims",           agents: ["claims"] },
  { match: "detecting risk",             agents: ["risk"] },
  { match: "checking founder",           agents: ["founders"] },
  { match: "searching public sources",   agents: ["founders"] },
  { match: "running market",             agents: ["market", "team", "bull", "bear"] },
  { match: "retrieving evidence",        agents: ["memory"] },
  { match: "writing the investment memo", agents: ["memo"] },
];

/**
 * Which agents are running, and which have finished.
 *
 * Everything before the current stage is done; the current stage is active;
 * everything after is idle. `degraded` overrides with failure once the run
 * finishes, since that is when the backend reports it.
 */
export function agentStates(
  stage: string,
  degraded: string[] = [],
  finished = false,
): Record<AgentId, AgentState> {
  const lower = (stage || "").toLowerCase();
  const index = STAGE_MAP.findIndex((s) => lower.includes(s.match));

  const states = {} as Record<AgentId, AgentState>;
  for (const a of AGENTS) states[a.id] = "idle";

  STAGE_MAP.forEach((entry, i) => {
    if (index < 0) return;
    for (const id of entry.agents) {
      if (i < index) states[id] = "done";
      else if (i === index) states[id] = "active";
    }
  });

  if (finished) {
    for (const a of AGENTS) if (states[a.id] !== "failed") states[a.id] = "done";
  }

  const failedText = degraded.join(" ").toLowerCase();
  for (const a of AGENTS) {
    if (failedText.includes(a.id)) states[a.id] = "failed";
  }
  return states;
}

const STATE_COLOUR: Record<AgentState, string> = {
  idle: "var(--text-faint)",
  active: "var(--accent)",
  done: "var(--verified)",
  failed: "var(--critical)",
};

export default function AnalysisTheatre({
  company,
  stage,
  degraded = [],
  finished = false,
  height = 520,
}: {
  company: string;
  /** The backend's current stage string, verbatim. */
  stage: string;
  /** `degraded_components[].component` from the report, once there is one. */
  degraded?: string[];
  finished?: boolean;
  height?: number;
}) {
  const states = useMemo(() => agentStates(stage, degraded, finished), [stage, degraded, finished]);
  const hostRef = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 900, h: height });

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setSize({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, []);

  // The orbit is an ellipse rather than a circle: a circle of nine labels
  // needs more width than a screen has, and squashing it vertically is what
  // makes the ring read as a plane seen at an angle rather than as a wheel.
  const cx = size.w / 2;
  const cy = size.h / 2;
  const rx0 = Math.min(size.w * 0.30, 330);
  const ry0 = Math.min(size.h * 0.34, 175);
  const rx1 = Math.min(size.w * 0.43, 470);
  const ry1 = Math.min(size.h * 0.46, 235);

  const place = (a: Agent) => {
    const rad = ((a.angle - 90) * Math.PI) / 180;
    const rx = a.ring === 0 ? rx0 : rx1;
    const ry = a.ring === 0 ? ry0 : ry1;
    return { x: cx + rx * Math.cos(rad), y: cy + ry * Math.sin(rad) };
  };

  const activeCount = Object.values(states).filter((s) => s === "active").length;

  return (
    <div ref={hostRef} className="th-root" style={{ height }}>
      <style>{`
        .th-root { position: relative; width: 100%; }

        .th-ring { position: absolute; inset: 0; pointer-events: none; }

        .th-core {
          position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%);
          display: grid; place-items: center; text-align: center;
          width: 190px; height: 190px; border-radius: 50%;
          border: 1px solid var(--line-strong);
          background: radial-gradient(circle at 50% 40%, var(--accent-quiet), transparent 68%);
        }
        .th-core-label { font-size: var(--t-label); font-weight: 600; letter-spacing: 0.14em; text-transform: uppercase; color: var(--text-3); }
        /* Two lines rather than an ellipsis: the subject of the whole scene
           should not read "Northwind ...". */
        .th-core-name {
          font-family: var(--font-display); font-size: clamp(18px, 2vw, 28px);
          line-height: 1.04; letter-spacing: -0.02em; margin-top: 8px;
          max-width: 156px; overflow: hidden;
          display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
          overflow-wrap: anywhere;
        }
        .th-core-run { margin-top: 10px; font-size: var(--t-micro); color: var(--text-3); }

        .th-node {
          position: absolute; transform: translate(-50%, -50%);
          display: flex; align-items: center; gap: 9px;
          padding: 9px 14px 9px 11px; border-radius: var(--r-pill);
          background: var(--surface); border: 1px solid var(--line);
          white-space: nowrap; cursor: default;
          transition: border-color var(--dur-base) var(--ease-out),
                      background var(--dur-base) var(--ease-out),
                      box-shadow var(--dur-base) var(--ease-out),
                      opacity var(--dur-base) var(--ease-out);
        }
        .th-node[data-state="idle"] { opacity: 0.45; }
        .th-node[data-state="active"] {
          border-color: var(--accent); background: var(--accent-quiet);
          box-shadow: 0 0 0 4px var(--accent-quiet), 0 12px 34px rgba(47,107,255,0.22);
        }
        .th-node[data-state="done"] { border-color: var(--verified-line); }
        .th-node[data-state="failed"] { border-color: var(--critical-line); background: var(--critical-quiet); }

        .th-node-label { font-size: var(--t-small); font-weight: 600; letter-spacing: -0.005em; }
        .th-node-icon { display: flex; flex-shrink: 0; }
        .th-spin { animation: th-spin 1.1s linear infinite; }
        @keyframes th-spin { to { transform: rotate(360deg); } }

        /* The connector to an active agent draws itself, then holds. */
        .th-line { stroke-dasharray: 1; stroke-dashoffset: 1; }
        .th-line[data-on="true"] { animation: th-draw 700ms var(--ease-out) forwards; }
        @keyframes th-draw { to { stroke-dashoffset: 0; } }

        .th-pulse { transform-origin: center; animation: th-pulse 2.4s var(--ease-in-out) infinite; }
        @keyframes th-pulse { 0%,100% { opacity: 0.16; } 50% { opacity: 0.4; } }

        :root[data-motion="off"] .th-spin, :root[data-motion="off"] .th-pulse { animation: none; }:root[data-motion="off"] .th-line[data-on="true"] { animation: none; stroke-dashoffset: 0; }
        

        @media (max-width: 860px) {
          .th-core { width: 150px; height: 150px; }
          .th-node { padding: 7px 11px 7px 9px; }
          .th-node-label { font-size: var(--t-micro); }
        }
      `}</style>

      {/* Geometry: the orbits, and a connector for every agent. */}
      <svg className="th-ring" viewBox={`0 0 ${size.w} ${size.h}`} aria-hidden="true">
        <ellipse cx={cx} cy={cy} rx={rx0} ry={ry0} fill="none" stroke="var(--line)" strokeWidth="1" />
        <ellipse cx={cx} cy={cy} rx={rx1} ry={ry1} fill="none" stroke="var(--line)" strokeWidth="1" strokeDasharray="3 6" />
        {activeCount > 0 && (
          <circle className="th-pulse" cx={cx} cy={cy} r={rx0 * 0.62} fill="none" stroke="var(--accent)" strokeWidth="1" />
        )}
        {AGENTS.map((a) => {
          const p = place(a);
          const state = states[a.id];
          const on = state === "active" || state === "done";
          return (
            <line
              key={a.id}
              className="th-line"
              data-on={on}
              x1={cx} y1={cy} x2={p.x} y2={p.y}
              pathLength={1}
              stroke={state === "active" ? "var(--accent)" : state === "done" ? "var(--verified)" : "var(--line)"}
              strokeWidth={state === "active" ? 1.6 : 1}
              opacity={state === "idle" ? 0.5 : state === "done" ? 0.45 : 1}
            />
          );
        })}
      </svg>

      {/* The subject. */}
      <div className="th-core">
        <div className="th-core-label">Company</div>
        <div className="th-core-name" title={company}>{company}</div>
        <div className="th-core-run">
          {finished
            ? "analysis complete"
            : activeCount > 1
              ? `${activeCount} agents running`
              : activeCount === 1 ? "1 agent running" : "starting"}
        </div>
      </div>

      {/* The specialists. Real text, in the order the pipeline runs them. */}
      <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
        {AGENTS.map((a) => {
          const p = place(a);
          const state = states[a.id];
          return (
            <li
              key={a.id}
              className="th-node"
              data-state={state}
              style={{ left: p.x, top: p.y }}
              title={a.role}
            >
              <span className="th-node-icon" style={{ color: STATE_COLOUR[state] }}>
                {state === "active" ? <Loader2 size={13} className="th-spin" />
                  : state === "done" ? <Check size={13} />
                    : state === "failed" ? <X size={13} />
                      : <Minus size={13} />}
              </span>
              <span className="th-node-label">{a.label}</span>
            </li>
          );
        })}
      </ol>

      {/* The same information, for anything that is not an eye. */}
      <p className="sr-only" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>
        {AGENTS.map((a) => `${a.label}: ${states[a.id]}.`).join(" ")}
      </p>
    </div>
  );
}
