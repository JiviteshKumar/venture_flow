import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { motionOn, subscribePrefs } from "../../lib/prefs";

/**
 * The wipe between routes: a scanner line reading the new page into place.
 *
 * WHY A SCAN AND NOT A SLIDE OR A FADE
 *
 * A slide says the pages are next to each other and a fade says nothing at
 * all. This product's single act is reading a document it has been handed and
 * resolving what it can check, so the transition borrows that: a bright line
 * travels down the viewport, the region it has passed is settled, the region
 * ahead of it is faintly held back. The reader watches the page being read.
 *
 * It is the same idea as `SignalField` one layer down -- unresolved becoming
 * resolved -- applied to time rather than to space, which is what keeps the
 * two from looking like two unrelated effects that happen to share a product.
 *
 * WHY IT IS CSS AND NOT A SPRING
 *
 * The animation is a fixed 520ms sweep with no interactive state, so a
 * keyframe does it exactly and costs one compositor-driven transform. Driving
 * it from React would re-render the tree on every frame of something the
 * reader cannot interrupt. The element is keyed on a counter so that a second
 * navigation restarts the sweep rather than ignoring it.
 *
 * WHAT IT REFUSES TO DO
 *
 *   - it never intercepts a pointer event: `pointer-events: none`
 *   - with motion off it renders nothing at all, not a faster version
 *   - it does not gate the route: the new page is mounted and usable from the
 *     first frame, with the sweep passing over the top of it
 */

const SWEEP_MS = 520;

export default function RouteScan() {
  const { pathname } = useLocation();
  const [moving, setMoving] = useState(motionOn);
  const [pass, setPass] = useState(0);
  const [running, setRunning] = useState(false);
  // The first render is an arrival, not a navigation. Sweeping then would
  // collide with the entrance animation and read as a glitch.
  const seen = useRef<string | null>(null);

  useEffect(() => subscribePrefs((s) => setMoving(s.motionOn)), []);

  useEffect(() => {
    if (seen.current === null) {
      seen.current = pathname;
      return;
    }
    if (seen.current === pathname) return;
    seen.current = pathname;
    setPass((n) => n + 1);
    setRunning(true);
  }, [pathname]);

  // Unmounted once the sweep is over rather than left hidden on top of the
  // page. A `visibility: hidden` overlay still sits in the stacking context
  // and still gets composited, and the next reader of this file should not
  // have to work out whether the fixed element over everything is inert.
  if (!moving || !running || pass === 0) return null;

  return (
    <div
      key={pass}
      aria-hidden="true"
      className="vf-scan"
      // The container's own animation is what times the sweep, so its end is
      // the honest signal that the effect is finished.
      onAnimationEnd={(e) => {
        if (e.target === e.currentTarget) setRunning(false);
      }}
      // Set as a custom property rather than `animationDuration`, because the
      // two children carry the animations and an inline duration on the parent
      // would not reach them.
      style={{ "--vf-scan-ms": SWEEP_MS + "ms" } as React.CSSProperties}
    >
      <div className="vf-scan-held" />
      <div className="vf-scan-line" />
      <style>{scanCss}</style>
    </div>
  );
}

// Kept out of the JSX so the rule text is plain CSS in a plain string: a
// backtick anywhere inside a template literal in the markup closes it early
// and the failure reads as a syntax error pages away from the cause.
const scanCss = [
  ".vf-scan {",
  "  position: fixed; inset: 0; z-index: 70; pointer-events: none;",
  "  overflow: hidden;",
  "  animation: vf-scan-out var(--vf-scan-ms, 520ms) linear forwards;",
  "}",
  // The region the line has not reached yet, held fractionally back. Its own
  // height is what animates, so the band is always exactly the unread part.
  ".vf-scan-held {",
  "  position: absolute; left: 0; right: 0; top: 0; height: 100%;",
  "  background: var(--scan-held, rgba(10, 14, 24, 0.22));",
  "  transform-origin: bottom;",
  "  animation: vf-scan-reveal var(--vf-scan-ms, 520ms) cubic-bezier(.4,0,.2,1) forwards;",
  "}",
  ".vf-scan-line {",
  "  position: absolute; left: 0; right: 0; top: 0; height: 1px;",
  "  background: var(--accent, #8fb6ff);",
  "  box-shadow: 0 0 18px 2px var(--accent, #8fb6ff);",
  "  opacity: .9;",
  "  animation: vf-scan-travel var(--vf-scan-ms, 520ms) cubic-bezier(.4,0,.2,1) forwards;",
  "}",
  "@keyframes vf-scan-travel {",
  "  from { transform: translateY(0); opacity: 0; }",
  "  12%  { opacity: .9; }",
  "  88%  { opacity: .9; }",
  "  to   { transform: translateY(100vh); opacity: 0; }",
  "}",
  // Scaling from the bottom shrinks the held band upward as the line descends,
  // so the two always meet and never drift apart on a slow frame.
  "@keyframes vf-scan-reveal {",
  "  from { transform: scaleY(1); }",
  "  to   { transform: scaleY(0); }",
  "}",
  "@keyframes vf-scan-out {",
  "  to { opacity: 1; visibility: hidden; }",
  "}",
  // A light page is dimmed by white, not by more black.
  ':root[data-theme="light"] .vf-scan-held {',
  "  background: rgba(255, 255, 255, 0.5);",
  "}",
  // The band is a flash of contrast. Anyone who has asked for less of that
  // gets the line alone, which still shows the direction of travel.
  "@media (prefers-contrast: more) {",
  "  .vf-scan-held { display: none; }",
  "}",
].join("\n");
