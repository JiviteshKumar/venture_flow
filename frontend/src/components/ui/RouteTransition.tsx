import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { motionOn } from "../../lib/prefs";

/**
 * The wipe between pages.
 *
 * A route change in a single-page app is instantaneous, and instantaneous is
 * the problem: the old screen is replaced mid-blink with no sense that
 * anything travelled. A short wipe gives the change a direction and covers
 * the frame where the new page's data has not arrived yet.
 *
 * HOW IT WORKS
 *
 * A panel sweeps across the viewport when the path changes. Navigation itself
 * is never delayed -- React has already swapped the route by the time the
 * panel is over the screen, so the wipe hides the swap rather than waiting for
 * it. The name of the destination rides along on the panel, which is what
 * turns a decorative sweep into a piece of information.
 *
 * It does not run on the first paint (the intro owns that), and it does not
 * run at all under `prefers-reduced-motion`.
 */

const TITLES: Record<string, string> = {
  "/": "Analyses",
  "/upload": "Upload",
  "/analysis": "Report",
  "/signin": "Sign in",
};

export default function RouteTransition({ children }: { children: ReactNode }) {
  const { pathname } = useLocation();
  const [sweeping, setSweeping] = useState(false);
  const [label, setLabel] = useState("");
  const first = useRef(true);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (!motionOn()) return;

    setLabel(TITLES[pathname] ?? "");
    setSweeping(true);
    if (timer.current) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setSweeping(false), 1500);
    return () => { if (timer.current) window.clearTimeout(timer.current); };
  }, [pathname]);

  return (
    <>
      <style>{`
        .vf-wipe {
          position: fixed; inset: 0; z-index: 9990;
          pointer-events: none;
          display: grid; place-items: center;
          background: var(--ink-0);
          transform: translate3d(0, 100%, 0);
        }
        /* 1500ms, with the panel held still across the middle third.
           At 860ms the hold was 16% of the run -- about 140ms -- so the panel
           arrived and left in one movement and the destination's name flashed
           past unread. The covered stretch is now ~420ms: long enough to read
           one word, short enough that nobody is waiting on it. Navigation is
           never delayed by any of this; React has already swapped the route
           behind the panel. */
        .vf-wipe[data-on="true"] { animation: vf-wipe-through 1500ms cubic-bezier(0.76, 0, 0.24, 1); }
        @keyframes vf-wipe-through {
          0%   { transform: translate3d(0, 100%, 0); }
          34%  { transform: translate3d(0, 0, 0); }
          62%  { transform: translate3d(0, 0, 0); }
          100% { transform: translate3d(0, -100%, 0); }
        }

        .vf-wipe-label {
          font-family: var(--font-display);
          font-size: clamp(34px, 6vw, 86px);
          letter-spacing: -0.03em; color: var(--text-on-ink);
          opacity: 0;
        }
        .vf-wipe[data-on="true"] .vf-wipe-label { animation: vf-wipe-label 1500ms ease-out; }
        @keyframes vf-wipe-label {
          0%, 16%  { opacity: 0; transform: translate3d(0, 18px, 0); }
          34%, 62% { opacity: 1; transform: none; }
          100%     { opacity: 0; transform: translate3d(0, -18px, 0); }
        }
      `}</style>

      {children}

      <div className="vf-wipe" data-on={sweeping} aria-hidden="true">
        <span className="vf-wipe-label">{label}</span>
      </div>
    </>
  );
}
