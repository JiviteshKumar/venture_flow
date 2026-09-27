import { useEffect, useRef, useState } from "react";
import { motionOn } from "../../lib/prefs";

/**
 * The first three seconds.
 *
 * WHAT HAPPENS
 *
 *   0.0s  black. A hairline draws outward from the centre.
 *   0.2s  the wordmark rises through it, one LETTER at a time.
 *   0.3s  a counter runs 000 to 100 in the corner, and the same progress fills
 *         the hairline -- the line and the number are one measurement shown
 *         twice, not two decorations that happen to be on screen together.
 *   1.9s  the black splits into two panels that part from that line, revealing
 *         the app already rendered and settled underneath.
 *
 * It was two word-chunks rising through a static rule and a counter in the
 * corner that meant nothing. Per-letter is finer and reads as typesetting
 * rather than as two blocks moving; tying the rule to the counter is what
 * turns a decorative line into the thing the number is counting.
 *
 * WHY IT IS ALLOWED TO EXIST
 *
 * An entrance is a cost paid by every visitor, so it has to earn its second
 * and a half. This one does two jobs beyond looking like something: it covers
 * the first paint and the session check -- which on a sleeping free-tier
 * backend is the difference between "designed" and "broken" -- and it states
 * what the product is before the product asks the visitor to do anything.
 *
 * WHAT KEEPS IT FROM BEING AN OBSTACLE
 *
 *   - It plays once per tab. A reload during work does not replay it.
 *   - Any click or key press ends it immediately.
 *   - Under `prefers-reduced-motion` it never mounts at all.
 *   - It is `pointer-events: none` the moment the panels start to part, so a
 *     visitor who is already reaching for a control is never blocked by it.
 *   - The app renders underneath the whole time. Nothing waits for this.
 */

const SEEN_KEY = "vf:intro-played";

export default function Intro() {
  const [phase, setPhase] = useState<"off" | "playing" | "leaving" | "done">("off");
  const [count, setCount] = useState(0);
  const timers = useRef<number[]>([]);

  useEffect(() => {
    const reduced = !motionOn();
    let seen = false;
    try { seen = sessionStorage.getItem(SEEN_KEY) === "1"; } catch { /* private mode */ }
    if (reduced || seen) { setPhase("done"); return; }

    // The "already played" flag is written when the sequence ENDS, not when it
    // starts. Written on entry, React's development double-mount marked it as
    // seen during the first, discarded mount, so the second -- the one that
    // actually renders -- skipped it and the entrance never appeared at all in
    // development. Writing on exit also means an entrance interrupted by a
    // navigation is not counted as having been shown.
    setPhase("playing");

    const started = performance.now();
    const DURATION = 1500;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / DURATION);
      // easeOutExpo: the counter sprints and then crawls the last few, which
      // is the rhythm that makes a loading number feel like it is measuring
      // something rather than animating.
      setCount(Math.round(100 * (t === 1 ? 1 : 1 - Math.pow(2, -10 * t))));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    // Held locally as well as on the ref: the cleanup must clear the timers
    // THIS run started, and by then the ref may already belong to a later one.
    const pending = [
      window.setTimeout(() => setPhase("leaving"), 1900),
      window.setTimeout(() => {
        setPhase("done");
        try { sessionStorage.setItem(SEEN_KEY, "1"); } catch { /* non-fatal */ }
      }, 3000),
    ];
    timers.current = pending;

    return () => {
      cancelAnimationFrame(frame);
      pending.forEach(window.clearTimeout);
    };
  }, []);

  // Any input skips it. Someone who has seen it once and is back to work
  // should never have to wait for it twice.
  useEffect(() => {
    if (phase !== "playing") return;
    const skip = () => {
      timers.current.forEach(window.clearTimeout);
      setPhase("leaving");
      timers.current.push(window.setTimeout(() => {
        setPhase("done");
        try { sessionStorage.setItem(SEEN_KEY, "1"); } catch { /* non-fatal */ }
      }, 1100));
    };
    window.addEventListener("pointerdown", skip);
    window.addEventListener("keydown", skip);
    return () => {
      window.removeEventListener("pointerdown", skip);
      window.removeEventListener("keydown", skip);
    };
  }, [phase]);

  if (phase === "off" || phase === "done") return null;

  return (
    <div className="vf-intro" data-leaving={phase === "leaving"} aria-hidden="true">
      <style>{`
        .vf-intro {
          position: fixed; inset: 0; z-index: 9998;
          pointer-events: auto;
        }
        .vf-intro[data-leaving="true"] { pointer-events: none; }

        /* Two panels rather than one curtain: they part from the centre line
           the wordmark sat on, so the reveal finishes the gesture the opening
           started. */
        .vf-intro-panel {
          position: absolute; left: 0; right: 0; height: 50%;
          background: var(--ink-0);
          transition: transform 1100ms cubic-bezier(0.76, 0, 0.24, 1);
          will-change: transform;
        }
        .vf-intro-panel.top { top: 0; }
        .vf-intro-panel.bottom { bottom: 0; }
        .vf-intro[data-leaving="true"] .vf-intro-panel.top { transform: translate3d(0, -100%, 0); }
        .vf-intro[data-leaving="true"] .vf-intro-panel.bottom { transform: translate3d(0, 100%, 0); }

        .vf-intro-stage {
          position: absolute; inset: 0; display: grid; place-items: center;
          transition: opacity 420ms var(--ease-out);
        }
        .vf-intro[data-leaving="true"] .vf-intro-stage { opacity: 0; }

        .vf-intro-mark {
          position: relative;
          font-family: var(--font-display);
          font-size: clamp(42px, 8vw, 128px);
          letter-spacing: -0.03em; line-height: 1;
          color: var(--text-on-ink);
          display: flex; overflow: hidden;
        }
        .vf-intro-mark span {
          display: inline-block;
          transform: translate3d(0, 105%, 0);
          animation: vf-intro-rise 820ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        /* "Flow" sits back a step, so the wordmark keeps its two halves. */
        .vf-intro-mark span[data-dim="true"] { color: var(--accent); }
        @keyframes vf-intro-rise { to { transform: none; } }

        /* The line the wordmark rises through, drawing outward from centre. */
        .vf-intro-rule {
          position: absolute; left: 50%; top: 50%;
          width: min(78vw, 1100px); height: 1px;
          transform: translate(-50%, -50%) scaleX(0);
          transform-origin: center;
          background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--text-on-ink) 26%, transparent), transparent);
          animation: vf-intro-draw 900ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        /* The counter, drawn along the rule. Same number, second reading. */
        .vf-intro-rule-fill {
          position: absolute; inset: 0;
          transform-origin: center;
          background: linear-gradient(90deg, transparent, var(--accent), transparent);
          will-change: transform;
        }
        @keyframes vf-intro-draw { to { transform: translate(-50%, -50%) scaleX(1); } }

        .vf-intro-sub {
          position: absolute; left: 50%; top: calc(50% + clamp(46px, 7vw, 96px));
          transform: translateX(-50%);
          font-size: 12px; font-weight: 600; letter-spacing: 0.3em;
          text-transform: uppercase; color: color-mix(in srgb, var(--text-on-ink) 45%, transparent);
          white-space: nowrap;
          opacity: 0; animation: vf-intro-fade 700ms 700ms var(--ease-out) forwards;
        }
        @keyframes vf-intro-fade { to { opacity: 1; } }

        .vf-intro-count {
          position: absolute; right: clamp(20px, 5vw, 64px); bottom: clamp(20px, 5vw, 56px);
          font-family: var(--font-mono); font-size: clamp(28px, 4vw, 56px);
          color: color-mix(in srgb, var(--text-on-ink) 28%, transparent); letter-spacing: -0.02em;
        }
      `}</style>

      <div className="vf-intro-panel top" />
      <div className="vf-intro-panel bottom" />

      <div className="vf-intro-stage">
        <div className="vf-intro-rule">
            <i className="vf-intro-rule-fill" style={{ transform: `scaleX(${count / 100})` }} />
          </div>
        {/* One span per letter. The two halves keep their own colour so the
            wordmark still reads as VentureFlow rather than as eleven glyphs. */}
        <div className="vf-intro-mark">
          {"VentureFlow".split("").map((letter, i) => (
            <span
              key={`${letter}-${i}`}
              data-dim={i >= 7}
              style={{ animationDelay: `${200 + i * 45}ms` }}
            >
              {letter}
            </span>
          ))}
        </div>
        <div className="vf-intro-sub">Diligence that shows its working</div>
        <div className="vf-intro-count">{String(count).padStart(3, "0")}</div>
      </div>
    </div>
  );
}
