import { useEffect, useRef } from "react";
import { motionOn, subscribePrefs, getPrefs } from "../../lib/prefs";

/**
 * The light behind the product.
 *
 * WHAT IT IS NOW, AND WHAT IT WAS
 *
 * This used to draw a perspective lattice and a hundred and twenty drifting
 * motes. Two things were wrong with that. It was busy -- a grid reads as graph
 * paper, and specks read as dust -- and on the light theme it was tuned so far
 * down (a 0.075 stroke multiplied by a 0.62 master alpha, so 0.046 against a
 * near-white page) that it painted nothing a person could see. Motion nobody
 * can see is not restraint, it is a bug.
 *
 * What replaces it is four very large, very soft pools of colour drifting on
 * slow independent paths. No edges, no repeating structure, nothing to count
 * or focus on: the page looks lit rather than decorated, which is the thing a
 * background can do without competing with the text on top of it.
 *
 * HOW IT STAYS SOFT AND CHEAP AT THE SAME TIME
 *
 * The pools are drawn into a buffer a fifth of the viewport's size and scaled
 * up. Upscaling is a blur -- a free one, done by the compositor -- so there is
 * no filter to run and the per-frame cost is four gradients over roughly
 * 380x190 pixels regardless of how large the window is.
 *
 * WHAT IT RESPONDS TO
 *
 *   the pointer   the pools lean away from it and a fifth pool follows it, so
 *                 the light moves with the reader rather than past them
 *   the scroll    a signed, decaying velocity pushes the pools against the
 *                 direction of travel, so the page has parallax depth and
 *                 settles when the reader stops
 *
 * WHAT IT REFUSES TO DO
 *
 *   - it never intercepts a pointer event: `pointer-events: none`
 *   - the loop stops entirely when the tab is hidden
 *   - with motion off it paints one frame and stops, so the page is still lit
 *     but nothing moves
 */

type Pool = {
  /** Hue, as "r,g,b". */
  c: string;
  /** Centre of its drift, in viewport fractions. */
  x: number;
  y: number;
  /** How far it wanders from that centre. */
  ax: number;
  ay: number;
  /**
   * Radians per frame on each axis, deliberately incommensurate so the
   * arrangement never visibly repeats.
   *
   * These are calibrated to a period, not picked by feel. At ~60fps a value
   * of 0.0031 is one cycle every 34 seconds; the first draft used 0.00042,
   * which is one cycle every FOUR AND A HALF MINUTES. The loop was running
   * the whole time and a pixel measured 1.4 seconds apart was bit-identical,
   * so the layer was static in every way a person could detect. Slow is the
   * point; stopped is a bug. Keep every period between roughly 20 and 45
   * seconds.
   */
  sx: number;
  sy: number;
  /** Radius as a fraction of the viewport's larger side. */
  r: number;
  /** Peak opacity at the centre of the pool. */
  a: number;
};

type Palette = {
  pools: Pool[];
  /** The pointer's own pool. */
  cursor: string;
  cursorA: number;
};

/**
 * Two palettes rather than one with an opacity dial.
 *
 * On near-black, colour has to be added and can be relatively saturated. On
 * near-white the same colour at the same weight is a stain, so the light set
 * is both paler and wider -- larger, weaker pools, which reads as daylight
 * through a window rather than as ink spilled on the page.
 */
const PALETTES: Record<"dark" | "light", Palette> = {
  dark: {
    cursor: "120,170,255",
    cursorA: 0.10,
    pools: [
      { c: "47,107,255",  x: 0.22, y: 0.28, ax: 0.15, ay: 0.11, sx: 0.00310, sy: 0.00227, r: 0.62, a: 0.30 },
      { c: "124,92,255",  x: 0.78, y: 0.22, ax: 0.13, ay: 0.14, sx: 0.00212, sy: 0.00345, r: 0.55, a: 0.24 },
      { c: "20,150,190",  x: 0.68, y: 0.80, ax: 0.16, ay: 0.10, sx: 0.00271, sy: 0.00183, r: 0.58, a: 0.20 },
      { c: "60,60,160",   x: 0.16, y: 0.82, ax: 0.12, ay: 0.13, sx: 0.00168, sy: 0.00287, r: 0.50, a: 0.22 },
    ],
  },
  light: {
    cursor: "47,107,255",
    cursorA: 0.07,
    pools: [
      { c: "47,107,255",  x: 0.20, y: 0.26, ax: 0.15, ay: 0.11, sx: 0.00310, sy: 0.00227, r: 0.74, a: 0.15 },
      { c: "124,92,255",  x: 0.80, y: 0.20, ax: 0.13, ay: 0.14, sx: 0.00212, sy: 0.00345, r: 0.66, a: 0.12 },
      { c: "26,160,200",  x: 0.70, y: 0.82, ax: 0.16, ay: 0.10, sx: 0.00271, sy: 0.00183, r: 0.70, a: 0.10 },
      { c: "120,140,255", x: 0.14, y: 0.84, ax: 0.12, ay: 0.13, sx: 0.00168, sy: 0.00287, r: 0.62, a: 0.11 },
    ],
  },
};

/** The buffer is this fraction of the viewport on each axis. */
const SCALE = 0.2;

export default function Ambience() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    let moving = motionOn();
    let paint = PALETTES[getPrefs().theme];

    // The small buffer everything is actually drawn into.
    const buffer = document.createElement("canvas");
    const bctx = buffer.getContext("2d", { alpha: true });
    if (!bctx) return;

    let w = 0, h = 0, bw = 0, bh = 0;
    const resize = () => {
      w = window.innerWidth;
      h = window.innerHeight;
      // Deliberately NOT devicePixelRatio: the image is upscaled from a fifth
      // of this and has no detail to preserve, so a retina backing store would
      // be four times the work for a blur nobody can resolve.
      canvas.width = Math.max(1, w);
      canvas.height = Math.max(1, h);
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      bw = Math.max(1, Math.round(w * SCALE));
      bh = Math.max(1, Math.round(h * SCALE));
      buffer.width = bw;
      buffer.height = bh;
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";
    };
    resize();
    window.addEventListener("resize", resize);

    let pointerX = 0.5, pointerY = 0.4;
    let px = 0.5, py = 0.4;
    let pointerSeen = false;
    const onPointer = (e: PointerEvent) => {
      pointerX = e.clientX / window.innerWidth;
      pointerY = e.clientY / window.innerHeight;
      pointerSeen = true;
    };
    window.addEventListener("pointermove", onPointer, { passive: true });

    /**
     * Scroll drift.
     *
     * Signed and decaying: down pushes it positive, up negative, and it
     * returns to zero when the reader stops. The pools move against it, which
     * is parallax -- the light is further away than the page.
     */
    let lastScroll = 0;
    let velocity = 0;
    const readScroll = () => {
      const el = document.getElementById("vf-scroller");
      const top = el ? el.scrollTop : window.scrollY;
      velocity += (top - lastScroll) * 0.05;
      lastScroll = top;
    };
    const attachScroll = () => {
      const el = document.getElementById("vf-scroller");
      (el ?? window).addEventListener("scroll", readScroll, { passive: true });
      return () => (el ?? window).removeEventListener("scroll", readScroll);
    };
    // The scroller belongs to whichever route is mounted, so it is re-attached
    // rather than captured once.
    let detachScroll = attachScroll();
    const reattach = window.setInterval(() => {
      detachScroll();
      detachScroll = attachScroll();
    }, 2000);

    let raf = 0;
    let t = 0;

    /** One soft pool, in buffer coordinates. */
    const pool = (x: number, y: number, r: number, colour: string, alpha: number) => {
      const g = bctx.createRadialGradient(x, y, 0, x, y, r);
      g.addColorStop(0, "rgba(" + colour + "," + alpha + ")");
      // Three stops rather than two: a linear ramp to zero has a visible edge
      // where it lands, and the whole point of this layer is that it has none.
      g.addColorStop(0.45, "rgba(" + colour + "," + alpha * 0.42 + ")");
      g.addColorStop(1, "rgba(" + colour + ",0)");
      bctx.fillStyle = g;
      bctx.fillRect(x - r, y - r, r * 2, r * 2);
    };

    const draw = () => {
      t += 1;
      px += (pointerX - px) * 0.03;
      py += (pointerY - py) * 0.03;
      velocity *= 0.92;
      const wake = Math.max(-40, Math.min(40, velocity)) * SCALE;

      bctx.clearRect(0, 0, bw, bh);
      // Additive, so where two pools overlap the light gets brighter rather
      // than one simply covering the other.
      bctx.globalCompositeOperation = "lighter";

      const reach = Math.max(bw, bh);
      for (const p of paint.pools) {
        const x = (p.x + Math.sin(t * p.sx) * p.ax + (px - 0.5) * -0.06) * bw;
        const y = (p.y + Math.cos(t * p.sy) * p.ay + (py - 0.5) * -0.05) * bh - wake;
        pool(x, y, reach * p.r, p.c, p.a);
      }

      // The pointer's own pool, so the light acknowledges where the reader is.
      if (pointerSeen) {
        pool(px * bw, py * bh, reach * 0.34, paint.cursor, paint.cursorA);
      }

      bctx.globalCompositeOperation = "source-over";

      // Upscale. This is the blur.
      ctx.clearRect(0, 0, w, h);
      ctx.drawImage(buffer, 0, 0, bw, bh, 0, 0, w, h);

      raf = requestAnimationFrame(draw);
    };

    const start = () => {
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      if (moving) {
        raf = requestAnimationFrame(draw);
      } else {
        // One frame: the page keeps its light, it just holds still.
        draw();
        cancelAnimationFrame(raf);
        raf = 0;
      }
    };
    start();

    const unsubscribe = subscribePrefs((s) => {
      paint = PALETTES[s.theme];
      moving = s.motionOn;
      start();
    });

    // A hidden tab should not be lighting a room nobody is in.
    const onVisibility = () => {
      if (document.hidden) {
        if (raf) { cancelAnimationFrame(raf); raf = 0; }
      } else if (!raf && moving) {
        raf = requestAnimationFrame(draw);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      if (raf) cancelAnimationFrame(raf);
      unsubscribe();
      window.removeEventListener("resize", resize);
      window.removeEventListener("pointermove", onPointer);
      document.removeEventListener("visibilitychange", onVisibility);
      window.clearInterval(reattach);
      detachScroll();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{ position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none" }}
    />
  );
}
