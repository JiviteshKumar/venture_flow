import { useEffect, useRef } from "react";
import { motionOn, subscribePrefs, getPrefs } from "../../lib/prefs";

/**
 * The room the product sits in.
 *
 * One fixed canvas behind every screen, carrying four things:
 *
 *   a lattice   a perspective grid receding to a horizon, which gives the page
 *               a floor and therefore a sense of depth
 *   a drift     motes at three depths, parallaxed against the pointer so the
 *               space reacts to where the reader is looking
 *   a pool      a soft light that follows the pointer; motes near it lean
 *               toward it and link to each other, so the cursor is something
 *               the room can feel rather than an overlay on top of it
 *   a wake      scrolling tilts the lattice and stretches the motes in the
 *               direction of travel, then settles -- so moving through the
 *               document feels like moving, not like repainting
 *
 * WHY ONE LAYER FOR THE WHOLE APP
 *
 * Every screen shared a flat background before this, and each scene had to
 * invent its own atmosphere. A single persistent layer means the dashboard,
 * the upload and the report are demonstrably the same place: navigating
 * between them moves the camera rather than swapping the set.
 *
 * THEME
 *
 * The room is lit differently in each theme, and it is not a colour swap. On
 * dark it ADDS light (`screen`); on light it REMOVES it (`multiply`), because
 * a pale wash over a white page is invisible and a grey one is grime. Each
 * theme therefore gets its own palette and its own blend mode, and the layer
 * re-lights itself when the preference changes rather than on reload.
 *
 * WHAT KEEPS IT CHEAP
 *
 *   - one canvas, one rAF loop, no per-element animation
 *   - the loop stops entirely when the tab is hidden
 *   - motes are floats in a typed array, not objects
 *   - links are only tested among motes already near the pointer
 *   - it never intercepts a pointer event: `pointer-events: none`
 *   - with motion off it draws a single static frame and stops
 */

const MOTES = 120;

type Palette = {
  blend: "screen" | "multiply";
  grid: string;
  band: string;
  bandEdge: string;
  moteNear: string;
  moteFar: string;
  link: string;          // "r,g,b"
  pool: string;          // "r,g,b"
  alpha: number;         // master opacity: light needs a far lighter touch
};

const PALETTES: Record<"dark" | "light", Palette> = {
  dark: {
    blend: "screen",
    grid: "rgba(92,148,255,0.055)",
    band: "rgba(47,107,255,0.05)",
    bandEdge: "rgba(5,8,15,0)",
    moteNear: "#9CC0FF",
    moteFar: "#E8EEF9",
    link: "154,190,255",
    pool: "120,170,255",
    alpha: 1,
  },
  light: {
    // The same figure on white, drawn in ink rather than in light.
    blend: "multiply",
    grid: "rgba(47,107,255,0.075)",
    band: "rgba(47,107,255,0.045)",
    bandEdge: "rgba(255,255,255,0)",
    moteNear: "#2F6BFF",
    moteFar: "#8194B5",
    link: "47,107,255",
    pool: "47,107,255",
    alpha: 0.62,
  },
};

export default function Ambience() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    let reduced = !motionOn();
    let paint = PALETTES[getPrefs().theme];
    canvas.style.mixBlendMode = paint.blend;

    let w = 0, h = 0, dpr = 1;
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = Math.max(1, w * dpr);
      canvas.height = Math.max(1, h * dpr);
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    // Deterministic placement: the same room every visit rather than a
    // different one per reload.
    const mote = new Float32Array(MOTES * 4);   // x, y, depth, size
    for (let i = 0; i < MOTES; i++) {
      const t = i / MOTES;
      mote[i * 4 + 0] = ((i * 0.6180339887) % 1);
      mote[i * 4 + 1] = ((i * 0.3819660113) % 1);
      mote[i * 4 + 2] = 0.25 + ((i * 0.2360679775) % 1) * 0.75;
      mote[i * 4 + 3] = 0.5 + (t * 7 % 1) * 1.4;
    }
    // Scratch space for the pointer's neighbourhood, reused every frame so the
    // link pass allocates nothing.
    const nearX = new Float32Array(MOTES);
    const nearY = new Float32Array(MOTES);

    let pointerX = 0.5, pointerY = 0.5;
    let px = 0.5, py = 0.5;
    let pointerSeen = false;
    const onPointer = (e: PointerEvent) => {
      pointerX = e.clientX / window.innerWidth;
      pointerY = e.clientY / window.innerHeight;
      pointerSeen = true;
    };
    window.addEventListener("pointermove", onPointer, { passive: true });

    /**
     * Scroll wake.
     *
     * `velocity` is signed and decays: scrolling down pushes it positive,
     * scrolling up negative, and it returns to zero when the reader stops. The
     * lattice tilts by it and the motes stretch along it, so the direction of
     * travel is visible rather than merely the fact of it.
     */
    let lastScroll = 0;
    let velocity = 0;
    const readScroll = () => {
      const el = document.getElementById("vf-scroller");
      const top = el ? el.scrollTop : window.scrollY;
      velocity += (top - lastScroll) * 0.06;
      lastScroll = top;
    };
    const attachScroll = () => {
      const el = document.getElementById("vf-scroller");
      (el ?? window).addEventListener("scroll", readScroll, { passive: true });
      return () => (el ?? window).removeEventListener("scroll", readScroll);
    };
    // The scroller belongs to whichever route is mounted, so it is re-attached
    // when the route changes rather than captured once at mount.
    let detachScroll = attachScroll();
    const reattach = window.setInterval(() => {
      detachScroll();
      detachScroll = attachScroll();
    }, 2000);

    let raf = 0;
    let t = 0;

    const draw = () => {
      t += 1;
      px += (pointerX - px) * 0.035;
      py += (pointerY - py) * 0.035;
      velocity *= 0.90;
      const wake = Math.max(-26, Math.min(26, velocity));
      const pxAbs = px * w;
      const pyAbs = py * h;

      ctx.clearRect(0, 0, w, h);
      ctx.globalAlpha = paint.alpha;

      // -- The floor ------------------------------------------------------
      // A grid in one-point perspective. The horizon rises and falls with the
      // pointer and leans with the wake.
      const horizon = h * (0.52 + (py - 0.5) * 0.06) + wake * 0.6;
      const vanish = w * (0.5 + (px - 0.5) * 0.18);

      ctx.lineWidth = 1;
      ctx.strokeStyle = paint.grid;
      ctx.beginPath();
      for (let i = -10; i <= 10; i++) {
        const x = vanish + i * (w * 0.14);
        ctx.moveTo(vanish + i * 8, horizon);
        ctx.lineTo(x, h + 40);
      }
      // Depth lines: spacing grows with distance below the horizon, which is
      // what makes it read as a receding plane rather than as a fan.
      for (let i = 1; i <= 14; i++) {
        const k = i / 14;
        const y = horizon + Math.pow(k, 2.1) * (h - horizon + 60);
        ctx.moveTo(0, y);
        ctx.lineTo(w, y);
      }
      ctx.stroke();

      // A soft band along the horizon, so the grid fades into the room rather
      // than stopping at a line.
      const band = ctx.createLinearGradient(0, horizon - h * 0.22, 0, horizon + h * 0.1);
      band.addColorStop(0, paint.bandEdge);
      band.addColorStop(0.72, paint.band);
      band.addColorStop(1, paint.bandEdge);
      ctx.fillStyle = band;
      ctx.fillRect(0, horizon - h * 0.22, w, h * 0.32);

      // -- The pool -------------------------------------------------------
      // A light the pointer carries. It exists so the cursor is part of the
      // room rather than a thing floating over it, and it appears only once a
      // pointer has actually moved, so a touch reader never sees a stray glow.
      const radius = Math.min(w, h) * 0.34;
      if (pointerSeen) {
        const pool = ctx.createRadialGradient(pxAbs, pyAbs, 0, pxAbs, pyAbs, radius);
        pool.addColorStop(0, "rgba(" + paint.pool + ",0.10)");
        pool.addColorStop(0.55, "rgba(" + paint.pool + ",0.035)");
        pool.addColorStop(1, "rgba(" + paint.pool + ",0)");
        ctx.fillStyle = pool;
        ctx.fillRect(pxAbs - radius, pyAbs - radius, radius * 2, radius * 2);
      }

      // -- The drift ------------------------------------------------------
      const reach = Math.min(w, h) * 0.22;         // how far the pointer pulls
      let near = 0;

      for (let i = 0; i < MOTES; i++) {
        const depth = mote[i * 4 + 2];
        const parallax = (depth - 0.5) * 2;
        const driftY = ((mote[i * 4 + 1] + t * 0.00012 * depth) % 1);
        let x = mote[i * 4 + 0] * w + (px - 0.5) * -70 * parallax;
        let y = driftY * h + wake * parallax * 1.6;
        const r = mote[i * 4 + 3] * depth;

        // Attraction. Motes near the pointer lean toward it -- more the nearer
        // they are to the camera, so the pull reads as depth rather than as a
        // flat magnet.
        let pull = 0;
        if (pointerSeen) {
          const dx = pxAbs - x;
          const dy = pyAbs - y;
          const dist = Math.hypot(dx, dy);
          if (dist < reach) {
            pull = 1 - dist / reach;
            const lean = pull * pull * 26 * depth;
            x += (dx / (dist || 1)) * lean;
            y += (dy / (dist || 1)) * lean;
            nearX[near] = x; nearY[near] = y; near++;
          }
        }

        ctx.globalAlpha = (0.05 + depth * 0.22 + pull * 0.35) * paint.alpha;
        ctx.fillStyle = depth > 0.82 ? paint.moteNear : paint.moteFar;

        if (Math.abs(wake) > 3) {
          // Stretched into a streak along the direction of travel.
          ctx.beginPath();
          ctx.ellipse(x, y, r, r + Math.abs(wake) * 0.5 * depth, 0, 0, Math.PI * 2);
          ctx.fill();
        } else {
          ctx.beginPath();
          ctx.arc(x, y, r + pull * 1.2, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // -- The links ------------------------------------------------------
      // Only among the motes already inside the pointer's reach, and only the
      // short edges: a full pass over every pair would be both slower and a
      // cobweb.
      if (near > 1) {
        const limit = reach * 0.42;
        ctx.lineWidth = 0.7;
        ctx.strokeStyle = "rgb(" + paint.link + ")";
        for (let a = 0; a < near; a++) {
          for (let b = a + 1; b < near; b++) {
            const dx = nearX[a] - nearX[b];
            const dy = nearY[a] - nearY[b];
            const d = Math.hypot(dx, dy);
            if (d > limit) continue;
            ctx.globalAlpha = (1 - d / limit) * 0.18 * paint.alpha;
            ctx.beginPath();
            ctx.moveTo(nearX[a], nearY[a]);
            ctx.lineTo(nearX[b], nearY[b]);
            ctx.stroke();
          }
        }
      }

      ctx.globalAlpha = 1;
      raf = requestAnimationFrame(draw);
    };

    const start = () => {
      if (raf) { cancelAnimationFrame(raf); raf = 0; }
      if (reduced) {
        // One frame, then stop: the room still has depth, it just holds still.
        draw();
        cancelAnimationFrame(raf);
        raf = 0;
      } else {
        raf = requestAnimationFrame(draw);
      }
    };
    start();

    // Theme and motion can both change while the room is on screen.
    const unsubscribe = subscribePrefs((s) => {
      paint = PALETTES[s.theme];
      canvas.style.mixBlendMode = paint.blend;
      reduced = !s.motionOn;
      start();
    });

    // A hidden tab should not be rendering a room nobody is in.
    const onVisibility = () => {
      if (document.hidden) {
        if (raf) { cancelAnimationFrame(raf); raf = 0; }
      } else if (!raf && !reduced) {
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
