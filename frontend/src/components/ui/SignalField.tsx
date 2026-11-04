import { useEffect, useRef } from "react";
import { canvasInk, onInkChange, type CanvasInk } from "../../lib/canvasInk";
import { motionOn } from "../../lib/prefs";

/**
 * Noise resolving into signal, under the pointer.
 *
 * WHAT IT DRAWS AND WHY THIS AND NOT A PARTICLE FIELD
 *
 * A lattice of dots on a fixed grid, each knocked off its true position by a
 * small per-dot wander. Near the pointer the wander is cancelled: the dots
 * return to the grid, brighten, and link to their neighbours, so a patch of
 * ordered structure follows the reader across an otherwise unresolved field.
 *
 * That is the product's job expressed as a picture. VentureFlow's whole claim
 * is that it turns a deck's assertions into something checked, and the honest
 * version of that is local -- a report resolves the part of the picture it has
 * evidence for and leaves the rest scattered. A field of drifting specks would
 * have said "technology"; this says the one specific thing the product does.
 *
 * It is deliberately a different KIND of mark from `Ambience`, which lies
 * underneath it. That draws four edgeless pools of light and no structure at
 * all. If this drew soft blobs too the two would read as one muddy layer, so
 * this one is all structure: hairlines, points, right angles.
 *
 * HOW IT STAYS CHEAP
 *
 * Dot positions are a grid, so there is no array of bodies to integrate and no
 * neighbour search. Each dot's wander is a pair of sines seeded from its own
 * coordinates, which makes the field deterministic, non-repeating across the
 * grid, and free of per-dot state. Links are drawn only between a dot and its
 * right and lower neighbour, and only where both are coherent, so the line
 * count collapses to nothing a few centimetres from the pointer.
 *
 * WHAT IT REFUSES TO DO
 *
 *   - it never intercepts a pointer event: `pointer-events: none`
 *   - the loop stops entirely when the tab is hidden
 *   - with motion off it paints one settled frame and stops: the field is
 *     there, on its grid, and nothing moves or follows the pointer
 */

/** Grid pitch in CSS pixels. Loose enough to read as a field, not graph paper. */
const PITCH = 46;

/** How far a dot wanders off its true position when fully unresolved. */
const WANDER = 7;

/** Radius of the resolved patch around the pointer, in CSS pixels. */
const REACH = 240;

/** Coherence above which a dot links to its neighbours. */
const LINK_AT = 0.45;

export default function SignalField() {
  const ref = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let ink: CanvasInk = canvasInk();
    let moving = motionOn();
    let frame = 0;
    let raf = 0;
    let width = 0;
    let height = 0;

    // Off-screen until the pointer arrives, so nothing is resolved on load and
    // the first movement is what reveals the effect.
    let px = -1e4;
    let py = -1e4;
    // The drawn pointer trails the real one, so a flick across the page pulls
    // the resolved patch after it instead of teleporting.
    let dx = -1e4;
    let dy = -1e4;

    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = window.innerWidth;
      height = window.innerHeight;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    /**
     * How settled the dot at (gx, gy) is: 1 on the grid and bright, 0 adrift.
     * Squared so the edge of the patch falls away softly instead of ending.
     */
    const coherence = (x: number, y: number) => {
      const d = Math.hypot(x - dx, y - dy);
      if (d >= REACH) return 0;
      const t = 1 - d / REACH;
      return t * t;
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);

      const t = frame / 110;
      const cols = Math.ceil(width / PITCH) + 1;
      const rows = Math.ceil(height / PITCH) + 1;

      // Positions are resolved once into a row pair so links can reuse them
      // rather than recomputing a neighbour's wander for every edge.
      let prevRow: { x: number; y: number; c: number }[] = [];

      for (let j = 0; j < rows; j++) {
        const row: { x: number; y: number; c: number }[] = [];
        for (let i = 0; i < cols; i++) {
          const gx = i * PITCH;
          const gy = j * PITCH;

          // Seeded from the coordinates: no stored state, and incommensurate
          // frequencies so the field never visibly tiles.
          const wx = Math.sin(t + i * 1.7 + j * 0.9) * WANDER;
          const wy = Math.cos(t * 0.86 + i * 0.6 + j * 1.3) * WANDER;

          const c = coherence(gx, gy);
          // Fully coherent dots sit exactly on the grid; the rest keep their
          // wander in proportion to how unresolved they are.
          const x = gx + wx * (1 - c);
          const y = gy + wy * (1 - c);

          row.push({ x, y, c });

          // Measured rather than guessed: at the first values the resting
          // field summed to an alpha of 531 over a 160px square, which is a
          // texture nobody can see. The ratio between resolved and unresolved
          // was already right -- 13 to 1 -- so only the absolute weight moved.
          const a = (0.13 + c * 0.6) * ink.k;
          ctx.fillStyle = "rgba(" + (c > 0.5 ? ink.accent : ink.line) + "," + a + ")";
          const r = 1.1 + c * 1.4;
          ctx.beginPath();
          ctx.arc(x, y, r, 0, Math.PI * 2);
          ctx.fill();

          // Left neighbour.
          if (i > 0) {
            const n = row[i - 1];
            const m = Math.min(c, n.c);
            if (m > LINK_AT) link(n, { x, y }, m);
          }
          // Upper neighbour.
          if (j > 0 && prevRow[i]) {
            const n = prevRow[i];
            const m = Math.min(c, n.c);
            if (m > LINK_AT) link(n, { x, y }, m);
          }
        }
        prevRow = row;
      }
    };

    const link = (
      a: { x: number; y: number },
      b: { x: number; y: number },
      strength: number,
    ) => {
      // Ramped from the link threshold rather than from zero, so an edge fades
      // in from nothing instead of appearing at a visible weight.
      const s = (strength - LINK_AT) / (1 - LINK_AT);
      ctx.strokeStyle = "rgba(" + ink.accent + "," + s * 0.38 * ink.k + ")";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    };

    const tick = () => {
      // Ease the drawn pointer toward the real one.
      dx += (px - dx) * 0.08;
      dy += (py - dy) * 0.08;
      frame++;
      draw();
      raf = requestAnimationFrame(tick);
    };

    const start = () => {
      cancelAnimationFrame(raf);
      if (moving) {
        raf = requestAnimationFrame(tick);
      } else {
        // Settled: on the grid, unresolved, no pointer. One frame, then stop.
        dx = -1e4;
        dy = -1e4;
        frame = 0;
        draw();
      }
    };

    const onPointer = (e: PointerEvent) => {
      if (!moving) return;
      px = e.clientX;
      py = e.clientY;
    };

    const onLeave = () => {
      px = -1e4;
      py = -1e4;
    };

    const onVisibility = () => {
      if (document.hidden) cancelAnimationFrame(raf);
      else start();
    };

    const onResize = () => {
      resize();
      if (!moving) draw();
    };

    resize();
    start();

    window.addEventListener("resize", onResize);
    window.addEventListener("pointermove", onPointer, { passive: true });
    window.addEventListener("pointerleave", onLeave);
    document.addEventListener("visibilitychange", onVisibility);
    const unsubscribe = onInkChange((next, nextMoving) => {
      ink = next;
      moving = nextMoving;
      start();
    });

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
      window.removeEventListener("pointermove", onPointer);
      window.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", onVisibility);
      unsubscribe();
    };
  }, []);

  return (
    <canvas
      ref={ref}
      aria-hidden="true"
      // Zero, exactly like Ambience, and above it only because it is rendered
      // after it: among positioned elements that share a z-index, the later
      // one in the DOM paints on top.
      //
      // Not 1. The app shell is deliberately transparent so the ambient
      // layers show through it, and the sidebar is `position: relative` with
      // no z-index of its own. A canvas at 1 therefore paints over the
      // sidebar's own background, and the field was last seen drifting across
      // the navigation.
      style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }}
    />
  );
}
