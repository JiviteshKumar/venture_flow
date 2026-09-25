import { useEffect, useRef, useState } from "react";
import { motionOn, subscribePrefs } from "../../lib/prefs";

/**
 * The pointer, replaced.
 *
 * WHAT IT IS
 *
 * Two objects and an echo:
 *
 *   the dot     a small solid disc that tracks the pointer exactly
 *   the ring    a circle that chases the dot with a lag, and which leans into
 *               the direction of travel
 *   the ripple  a ring that leaves the click point and fades
 *
 * The gap between dot and ring is the whole effect. The ring overshoots on a
 * fast flick and settles a beat later, which reads as weight; a single element
 * that tracks perfectly is just a worse mouse pointer.
 *
 * THE LEAN
 *
 * The ring is stretched along its own velocity and squashed across it, and
 * rotated to match. That is one rotate and one scale on an element the
 * compositor is already moving, so it costs nothing, and it is what makes the
 * thing feel like an object with mass rather than a circle being teleported.
 * The stretch is capped: past a certain speed it stops growing, so a fast
 * flick across a wide screen does not fire a streak across the page.
 *
 * WHAT IT READS FROM THE PAGE
 *
 *   a link or button       the ring swells and fills
 *   [data-cursor="Open"]   the ring swells and takes that word as a label
 *   text input             both collapse to a caret bar
 *
 * The label is the part that earns the custom cursor: it says what the click
 * will do before the click happens.
 *
 * WHAT IT REFUSES TO DO
 *
 * It does not render at all on a coarse pointer (there is nothing to replace
 * on a touch screen) or when motion is off (a lagging object chasing the
 * pointer is exactly the kind of movement that preference exists to stop). In
 * both cases the native cursor is left alone -- the `cursor: none` rule is
 * added by this component at mount and removed when it unmounts, so a failure
 * to render can never leave a page with no pointer at all.
 *
 * It also never swallows a click: every layer is `pointer-events: none`.
 *
 * COLOUR
 *
 * It was drawn with `mix-blend-mode: difference`, which inverts whatever is
 * under it. That is legible everywhere without being told anything about the
 * backdrop, and it looks like nothing else in the product: a grey smear whose
 * colour is decided by whatever it happens to be passing over. It now uses the
 * theme's own accent and text tokens, so it belongs to the page it is on and
 * changes with the light.
 */

type Mode = "idle" | "action" | "text";

export default function Cursor() {
  const dotRef = useRef<HTMLDivElement>(null);
  const ringRef = useRef<HTMLDivElement>(null);
  const echoRef = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<Mode>("idle");
  const [label, setLabel] = useState("");
  const [visible, setVisible] = useState(false);
  /**
   * The motion preference, watched rather than sampled.
   *
   * This used to be read once inside the effect below, which had no
   * dependencies. On a machine whose OS asks for reduced motion -- which is
   * the default on a great many remote desktops, VMs and preview panes -- the
   * gate closed on the first paint and never reopened, so turning motion on
   * from the control did nothing until a reload. Holding it in state makes
   * the effect tear down and set up with the preference.
   */
  const [allowed, setAllowed] = useState(motionOn);
  useEffect(() => subscribePrefs((s) => setAllowed(s.motionOn)), []);

  useEffect(() => {
    const fine = window.matchMedia?.("(pointer: fine)").matches;
    if (!fine || !allowed) return;

    document.documentElement.classList.add("vf-cursor-on");

    // Target and current are kept out of React state: this runs on every
    // pointer event and every animation frame, and putting it through a
    // setState would re-render the tree a hundred times a second to move two
    // divs the compositor could move on its own.
    let tx = window.innerWidth / 2;
    let ty = window.innerHeight / 2;
    let rx = tx;
    let ry = ty;
    let angle = 0;          // radians, the ring's current heading
    let stretch = 0;        // 0..1, how far it is leaning
    let frame = 0;

    const tick = () => {
      // The ring eases toward the dot. 0.18 is the sweet spot: any lower and
      // it feels broken, any higher and there is no lag to notice.
      const dx = tx - rx;
      const dy = ty - ry;
      rx += dx * 0.18;
      ry += dy * 0.18;

      // Lean. `speed` is the distance still to close, which is a stand-in for
      // velocity that costs nothing and settles to zero on its own. It is
      // normalised against 90px and clamped, so the stretch tops out instead
      // of growing without bound on a fast flick.
      const speed = Math.min(1, Math.hypot(dx, dy) / 90);
      stretch += (speed - stretch) * 0.2;
      if (speed > 0.02) angle = Math.atan2(dy, dx);

      if (dotRef.current) {
        dotRef.current.style.transform =
          "translate3d(" + tx + "px," + ty + "px,0) translate(-50%,-50%)";
      }
      if (ringRef.current) {
        // The lean is for the plain ring only. Once the ring has swollen into
        // a labelled pill, rotating it would stand the word on its end, and
        // the swell is already saying what the ring is doing. Read from the
        // attribute React just wrote rather than from state, which this
        // closure captured at mount.
        const plain = ringRef.current.dataset.cursorMode === "idle"
          && ringRef.current.dataset.labelled !== "true";
        let t = "translate3d(" + rx + "px," + ry + "px,0) translate(-50%,-50%)";
        if (plain) {
          const along = 1 + stretch * 0.55;
          const across = 1 - stretch * 0.3;
          t += " rotate(" + angle + "rad) scale(" + along + "," + across + ")";
        } else {
          // Let the lean unwind while it is parked, so it does not snap back
          // into shape the moment the pointer leaves the button.
          stretch *= 0.85;
        }
        ringRef.current.style.transform = t;
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);

    const visibleRef = { current: false };

    const onMove = (e: PointerEvent) => {
      if (e.type === "pointermove") {
        tx = e.clientX;
        ty = e.clientY;
      }
      if (!visibleRef.current) {
        visibleRef.current = true;
        setVisible(true);
      }

      const el = e.target as HTMLElement | null;
      const interactive = el?.closest?.(
        'a, button, [role="button"], [data-cursor], input, textarea, select, summary',
      ) as HTMLElement | null;

      if (!interactive) {
        setMode("idle");
        setLabel("");
        return;
      }
      const tag = interactive.tagName.toLowerCase();
      if (tag === "input" || tag === "textarea") {
        setMode("text");
        setLabel("");
        return;
      }
      setMode("action");
      setLabel(interactive.dataset.cursor && interactive.dataset.cursor !== "true"
        ? interactive.dataset.cursor
        : "");
    };

    const onLeave = () => { visibleRef.current = false; setVisible(false); };
    const onDown = () => ringRef.current?.classList.add("is-down");

    /**
     * The echo.
     *
     * One ring per click, left at the point of contact and expanding away from
     * it. It exists because a click on a page that navigates elsewhere leaves
     * no evidence it registered, and a cursor that acknowledges the press is
     * the cheapest possible confirmation.
     *
     * The node removes itself when its animation ends, so a long session does
     * not accumulate a thousand dead divs.
     */
    const onUp = (e: PointerEvent) => {
      ringRef.current?.classList.remove("is-down");
      const host = echoRef.current;
      if (!host) return;
      const echo = document.createElement("span");
      echo.className = "vf-cur-echo";
      echo.style.left = e.clientX + "px";
      echo.style.top = e.clientY + "px";
      echo.addEventListener("animationend", () => echo.remove(), { once: true });
      host.appendChild(echo);
    };

    // Held locally: by cleanup the ref may already point at a later mount's
    // node, and emptying that one would delete a live layer.
    const echoLayer = echoRef.current;

    window.addEventListener("pointermove", onMove, { passive: true });
    // `pointerover` as well as `pointermove`: after a click navigates, the
    // element under a stationary pointer changes without the pointer moving,
    // and the ring would keep the label of a button that is no longer there.
    window.addEventListener("pointerover", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);
    window.addEventListener("pointerdown", onDown, { passive: true });
    window.addEventListener("pointerup", onUp, { passive: true });

    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerover", onMove);
      document.removeEventListener("pointerleave", onLeave);
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("pointerup", onUp);
      document.documentElement.classList.remove("vf-cursor-on");
      if (echoLayer) echoLayer.innerHTML = "";
      // The native pointer comes back with it, so switching motion off never
      // leaves a page with nothing to point with.
      setVisible(false);
    };
  }, [allowed]);

  return (
    <>
      <style>{`
        /* Only ever applied by the component itself, and removed on unmount:
           a stylesheet rule would hide the pointer even when this never
           mounted. */
        .vf-cursor-on, .vf-cursor-on * { cursor: none !important; }

        .vf-cur-dot, .vf-cur-ring {
          position: fixed; top: 0; left: 0; z-index: 9999;
          pointer-events: none;
          will-change: transform;
          opacity: 0;
          transition: opacity 240ms var(--ease-out);
        }
        .vf-cur-dot[data-on="true"], .vf-cur-ring[data-on="true"] { opacity: 1; }

        .vf-cur-dot {
          width: 5px; height: 5px; border-radius: 50%;
          background: var(--accent);
          box-shadow: 0 0 0 1px color-mix(in srgb, var(--bg) 70%, transparent);
        }

        .vf-cur-ring {
          width: 30px; height: 30px; border-radius: 50%;
          border: 1.25px solid color-mix(in srgb, var(--accent) 55%, transparent);
          background: color-mix(in srgb, var(--accent) 6%, transparent);
          display: grid; place-items: center;
          /* No transform here: the frame loop owns it. Only the shape
             transitions, or the lean would fight the easing. */
          transition: width 320ms var(--ease-spring), height 320ms var(--ease-spring),
                      background 260ms var(--ease-out), border-color 260ms var(--ease-out),
                      border-radius 260ms var(--ease-out), opacity 240ms var(--ease-out);
        }
        /* Pressed: the ring tightens onto the dot. The release is what fires
           the echo, so the two read as one gesture. */
        .vf-cur-ring.is-down {
          width: 20px; height: 20px;
          background: color-mix(in srgb, var(--accent) 26%, transparent);
          border-color: var(--accent);
        }

        .vf-cur-ring[data-cursor-mode="action"] {
          width: 48px; height: 48px;
          background: color-mix(in srgb, var(--accent) 14%, transparent);
          border-color: color-mix(in srgb, var(--accent) 85%, transparent);
          box-shadow: 0 0 0 1.5px color-mix(in srgb, var(--bg) 75%, transparent);
        }
        /* Carrying a word, the ring becomes a solid accent chip. An outlined
           one would leave the label sitting on whatever text is underneath. */
        .vf-cur-ring[data-cursor-mode="action"][data-labelled="true"] {
          width: auto; height: auto; min-width: 0;
          padding: 9px 15px; border-radius: 999px;
          background: var(--accent);
          border-color: transparent;
          /* A halo in the page's own colour. Without it the chip vanishes the
             moment it is over a control painted in the same accent -- which is
             every primary button in the product. */
          box-shadow: 0 0 0 2.5px var(--bg), var(--e-2);
        }
        .vf-cur-ring[data-cursor-mode="text"] {
          width: 2px; height: 24px; border-radius: 1px;
          background: var(--accent); border-color: transparent;
        }

        .vf-cur-label {
          font-family: var(--font-sans); font-size: 11px; font-weight: 600;
          letter-spacing: 0.1em; text-transform: uppercase; color: #fff;
          white-space: nowrap;
        }

        .vf-cur-echo-layer { position: fixed; inset: 0; z-index: 9998; pointer-events: none; }
        .vf-cur-echo {
          position: absolute;
          width: 22px; height: 22px; margin: -11px 0 0 -11px;
          border-radius: 50%;
          border: 1.5px solid var(--accent);
          animation: vf-cur-echo 520ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
        }
        @keyframes vf-cur-echo {
          from { transform: scale(0.4); opacity: 0.9; }
          to   { transform: scale(2.6); opacity: 0; }
        }
      `}</style>

      <div ref={ringRef} className="vf-cur-ring" data-on={visible} data-cursor-mode={mode} data-labelled={Boolean(label)} aria-hidden="true">
        {label && <span className="vf-cur-label">{label}</span>}
      </div>
      <div ref={dotRef} className="vf-cur-dot" data-on={visible} aria-hidden="true" />
      <div ref={echoRef} className="vf-cur-echo-layer" aria-hidden="true" />
    </>
  );
}
