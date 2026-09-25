import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

/**
 * Surfaces and overlays: Badge, Tooltip, Modal, Tabs.
 *
 * The four pieces every screen from here on needs, each written once so a
 * later phase cannot quietly invent a fifth variant. They read tone from the
 * token set rather than taking colours, so the same component is correct on
 * paper and on ink without a single conditional.
 */

export type Tone = "neutral" | "accent" | "verified" | "caution" | "critical";

const TONE_VAR: Record<Tone, { fg: string; quiet: string; line: string }> = {
  neutral:  { fg: "var(--text-2)",  quiet: "var(--neutral-quiet)",  line: "var(--neutral-line)" },
  accent:   { fg: "var(--accent)",  quiet: "var(--accent-quiet)",   line: "var(--accent-line)" },
  verified: { fg: "var(--verified)",quiet: "var(--verified-quiet)", line: "var(--verified-line)" },
  caution:  { fg: "var(--caution)", quiet: "var(--caution-quiet)",  line: "var(--caution-line)" },
  critical: { fg: "var(--critical)",quiet: "var(--critical-quiet)", line: "var(--critical-line)" },
};

export const tone = (t: Tone) => TONE_VAR[t];

/** Micro type: badges and tooltips. One constant, so the two cannot drift. */
const MICRO = 12;

// ── Badge ────────────────────────────────────────────────────────────────────

/**
 * A status, not a decoration.
 *
 * `dot` gives the badge a leading indicator for states a reader scans down a
 * column -- verified, analysing, failed -- where the word is the label and the
 * dot is what the eye actually follows.
 */
export function Badge({
  children,
  tone: t = "neutral",
  dot = false,
  pulse = false,
  size = "md",
  title,
}: {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
  /** For a live state only: something that is happening right now. */
  pulse?: boolean;
  size?: "sm" | "md";
  title?: string;
}) {
  const c = TONE_VAR[t];
  return (
    <span
      title={title}
      style={{
        display: "inline-flex", alignItems: "center", gap: dot ? 7 : 6,
        padding: size === "sm" ? "2px 8px" : "4px 11px",
        borderRadius: "var(--r-pill)",
        background: c.quiet,
        border: `1px solid ${c.line}`,
        color: c.fg,
        fontSize: size === "sm" ? 11 : MICRO,
        fontWeight: 600,
        lineHeight: 1.5,
        whiteSpace: "nowrap",
      }}
    >
      {dot && (
        <span
          className={pulse ? "vf-badge-dot vf-badge-pulse" : "vf-badge-dot"}
          style={{ background: c.fg }}
        />
      )}
      {children}
    </span>
  );
}

export function BadgeStyles() {
  return (
    <style>{`
      .vf-badge-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
      .vf-badge-pulse { animation: vf-badge-pulse 1.9s var(--ease-in-out) infinite; }
      @keyframes vf-badge-pulse {
        0%, 100% { box-shadow: 0 0 0 0 currentColor; opacity: 1; }
        50% { box-shadow: 0 0 0 4px transparent; opacity: 0.55; }
      }
      :root[data-motion="off"] .vf-badge-pulse { animation: none; } 
    `}</style>
  );
}

// ── Tooltip ──────────────────────────────────────────────────────────────────

/**
 * A hover explanation that is also reachable without a pointer.
 *
 * The version this replaces was a CSS `[data-tip]::after`, which is invisible
 * to a screen reader, unreachable on a touch screen, and -- because it fired
 * on any hover including one the page itself caused -- occasionally left
 * stranded over the element below. This renders a real element, is opened by
 * focus as well as hover, and is referenced by `aria-describedby`.
 */
export function Tooltip({
  label,
  children,
  side = "top",
}: {
  label: string;
  children: ReactNode;
  side?: "top" | "bottom";
}) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span
      style={{ position: "relative", display: "inline-flex" }}
      /* Capture phase: the control being described is the child, and focus
         does not bubble in React's synthetic system for every element type.
         These listeners observe the child rather than adding a control. */
      onPointerEnter={() => setOpen(true)}
      onPointerLeave={() => setOpen(false)}
      onFocusCapture={() => setOpen(true)}
      onBlurCapture={() => setOpen(false)}
    >
      <span aria-describedby={open ? id : undefined} style={{ display: "inline-flex" }}>
        {children}
      </span>
      {open && (
        <span
          id={id}
          role="tooltip"
          style={{
            position: "absolute",
            [side === "top" ? "bottom" : "top"]: "calc(100% + 8px)",
            left: "50%", transform: "translateX(-50%)",
            background: "var(--n-900)", color: "var(--n-0)",
            padding: "7px 11px", borderRadius: "var(--r-sm)",
            fontSize: MICRO, lineHeight: 1.45, fontWeight: 500,
            maxWidth: 260, width: "max-content", textAlign: "center",
            boxShadow: "var(--e-2)", zIndex: 400, pointerEvents: "none",
          }}
        >
          {label}
        </span>
      )}
    </span>
  );
}

// ── Modal ────────────────────────────────────────────────────────────────────

/**
 * A dialog that behaves like one: Escape closes it, the backdrop closes it,
 * focus moves into it on open and returns to the opener on close, and the
 * page behind it cannot be scrolled away underneath.
 *
 * Rendered through a portal so it is never clipped by a transformed ancestor
 * -- which is a real hazard in this product, where whole scenes sit inside
 * `transform` containers for the scroll scrub.
 */
export function Modal({
  open,
  onClose,
  title,
  children,
  width = 640,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  width?: number;
}) {
  const panel = useRef<HTMLDivElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    if (!open) return;
    opener.current = document.activeElement;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    panel.current?.focus();
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
      (opener.current as HTMLElement | null)?.focus?.();
    };
  }, [open, onClose]);

  if (!open) return null;

  return createPortal(
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 500,
        display: "grid", placeItems: "center", padding: "var(--s-5)",
      }}
    >
      <button
        type="button"
        onClick={onClose}
        aria-label="Close dialog"
        tabIndex={-1}
        style={{
          position: "absolute", inset: 0, border: "none", cursor: "default",
          background: "rgba(6,10,20,0.55)", backdropFilter: "blur(3px)",
        }}
      />
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        style={{
          position: "relative", width: "min(100%, " + width + "px)",
          maxHeight: "86vh", overflowY: "auto",
          background: "var(--surface)", color: "var(--text)",
          border: "1px solid var(--line)", borderRadius: "var(--r-lg)",
          boxShadow: "var(--e-3)", outline: "none",
        }}
      >
        <div
          style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            gap: 16, padding: "18px 22px", borderBottom: "1px solid var(--line)",
            position: "sticky", top: 0, background: "var(--surface)", zIndex: 1,
          }}
        >
          <h2 style={{ margin: 0, font: "inherit", fontSize: 16, fontWeight: 600 }}>{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              display: "inline-flex", padding: 7, borderRadius: "var(--r-sm)",
              background: "transparent", border: "1px solid var(--line)",
              color: "var(--text-3)", cursor: "pointer",
            }}
          >
            <X size={15} />
          </button>
        </div>
        <div style={{ padding: "20px 22px 24px" }}>{children}</div>
      </div>
    </div>,
    document.body,
  );
}

// ── Tabs ─────────────────────────────────────────────────────────────────────

/**
 * A tab strip with a travelling indicator and real keyboard semantics.
 *
 * Arrow keys move between tabs, Home and End jump to the ends, and only the
 * active tab is in the tab order -- which is what the roving-tabindex pattern
 * exists for, and what a row of plain buttons gets wrong.
 */
export function Tabs({
  tabs,
  active,
  onChange,
  ariaLabel = "Sections",
}: {
  tabs: string[];
  active: string;
  onChange: (next: string) => void;
  ariaLabel?: string;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const i = tabs.indexOf(active);
    let next = i;
    if (e.key === "ArrowRight") next = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;
    e.preventDefault();
    onChange(tabs[next]);
    refs.current[next]?.focus();
  };

  return (
    <div role="tablist" aria-label={ariaLabel} className="vf-tabs">
      <style>{`
        .vf-tabs { display: flex; gap: 2px; overflow-x: auto; scrollbar-width: none; }
        .vf-tabs::-webkit-scrollbar { display: none; }
        .vf-tab {
          position: relative; flex-shrink: 0;
          padding: 16px 16px 15px; border: none; background: none; cursor: pointer;
          font-family: var(--font-sans); font-size: var(--t-small); font-weight: 600;
          color: var(--text-3); letter-spacing: -0.005em;
          transition: color var(--dur-fast) var(--ease-out);
        }
        .vf-tab:hover { color: var(--text); }
        .vf-tab[aria-selected="true"] { color: var(--accent); }
        .vf-tab-rule {
          position: absolute; left: 12px; right: 12px; bottom: 0; height: 2px;
          border-radius: 2px; background: var(--accent);
          transition: transform var(--dur-base) var(--ease-out);
        }
      `}</style>
      {tabs.map((t, i) => (
        <button
          key={t}
          ref={(el) => { refs.current[i] = el; }}
          role="tab"
          aria-selected={active === t}
          tabIndex={active === t ? 0 : -1}
          className="vf-tab"
          onClick={() => onChange(t)}
          onKeyDown={onKeyDown}
        >
          {t}
          {active === t && <span className="vf-tab-rule" />}
        </button>
      ))}
    </div>
  );
}
