import { useEffect, useRef } from "react";
import { motionOn } from "../../lib/prefs";
import { canvasInk, onInkChange } from "../../lib/canvasInk";

/**
 * The aperture a deck is dropped into.
 *
 * WHY THERE IS NOTHING IN IT TO BEGIN WITH
 *
 * The obvious move is to float a stock 3D document here so the screen looks
 * full before anyone has done anything. That would be the one object in this
 * product that depicts data nobody supplied. The frame is therefore empty and
 * says so: it is an intake, and it fills with the reader's own deck the moment
 * there is one -- at which point `DeckSculpture` takes over with the real page
 * count and the real read/unread state.
 *
 * WHAT IT DOES SHOW
 *
 * A rectangular aperture drawn in perspective, with a scanning sweep and a
 * field of drifting motes. `state` drives all three:
 *
 *   idle      slow drift, sweep parked
 *   armed     a file is over the target: the frame opens and brightens
 *   reading   the sweep runs top to bottom, continuously
 *
 * Canvas rather than DOM because the sweep, the frame and the motes share one
 * perspective transform; doing that with elements means three transforms that
 * drift apart at the edges.
 */

export type IntakeState = "idle" | "armed" | "reading";

export default function IntakePortal({
  state = "idle",
  height = 320,
}: {
  state?: IntakeState;
  height?: number;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef<IntakeState>(state);
  stateRef.current = state;

  useEffect(() => {
    const host = hostRef.current;
    const canvas = canvasRef.current;
    if (!host || !canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let reduced = !motionOn();
    let ink = canvasInk();

    let w = 0, h = 0;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = host.clientWidth; h = host.clientHeight;
      canvas.width = Math.max(1, w * dpr);
      canvas.height = Math.max(1, h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(() => { resize(); if (reduced) draw(0); });
    ro.observe(host);

    // Deterministic motes: the same aperture every time it is opened, rather
    // than a different one per mount.
    const MOTES = 34;
    const motes = Array.from({ length: MOTES }, (_, i) => ({
      x: ((i * 0.6180339887) % 1) * 2 - 1,
      y: ((i * 0.3819660113) % 1) * 2 - 1,
      z: ((i * 0.2360679775) % 1),
      s: 0.4 + ((i * 7) % 10) / 14,
    }));

    let raf = 0;
    let t = 0;

    const draw = (time: number) => {
      const mode = stateRef.current;
      const cx = w / 2, cy = h / 2;
      const openTarget = mode === "idle" ? 0.78 : 0.92;
      const glow = mode === "idle" ? 0.28 : mode === "armed" ? 0.75 : 0.55;

      ctx.clearRect(0, 0, w, h);

      const half = Math.min(w * 0.32, h * 0.42) * openTarget;
      const depth = half * 0.55;

      // Motes first: they sit behind the frame.
      for (const m of motes) {
        const drift = (m.z + time * 0.00004) % 1;
        const px = cx + m.x * half * 1.5;
        const py = cy + ((m.y + 1) / 2 + drift) % 1 * h - h / 2;
        const scale = 0.35 + m.z * 0.65;
        ctx.globalAlpha = (0.10 + m.z * 0.20) * ink.k;
        ctx.fillStyle = "rgb(" + ink.accent + ")";
        ctx.beginPath();
        ctx.arc(px, py, m.s * scale * 1.6, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // The aperture: a rectangle and its perspective twin, corners joined.
      const front = [
        [cx - half, cy - half * 0.62], [cx + half, cy - half * 0.62],
        [cx + half, cy + half * 0.62], [cx - half, cy + half * 0.62],
      ];
      const back = front.map(([x, y]) => [
        cx + (x - cx) * 0.62,
        cy + (y - cy) * 0.62 - depth * 0.18,
      ]);

      ctx.lineWidth = 1;
      ctx.strokeStyle = `rgba(${ink.accent},${(0.10 + glow * 0.16) * (0.5 + ink.k * 0.5)})`;
      for (let i = 0; i < 4; i++) {
        ctx.beginPath();
        ctx.moveTo(front[i][0], front[i][1]);
        ctx.lineTo(back[i][0], back[i][1]);
        ctx.stroke();
      }

      const ring = (pts: number[][], alpha: number, width: number) => {
        ctx.beginPath();
        ctx.moveTo(pts[0][0], pts[0][1]);
        for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
        ctx.closePath();
        ctx.strokeStyle = `rgba(${ink.line},${alpha})`;
        ctx.lineWidth = width;
        ctx.stroke();
      };
      ring(back, 0.10 + glow * 0.18, 1);
      ring(front, 0.26 + glow * 0.5, 1.4);

      // Corner ticks: the frame reads as an instrument rather than a box.
      const tick = half * 0.18;
      ctx.strokeStyle = `rgba(${ink.accent},${0.45 + glow * 0.5})`;
      ctx.lineWidth = 1.8;
      for (const [x, y] of front) {
        const dx = x < cx ? 1 : -1;
        const dy = y < cy ? 1 : -1;
        ctx.beginPath();
        ctx.moveTo(x, y); ctx.lineTo(x + dx * tick, y);
        ctx.moveTo(x, y); ctx.lineTo(x, y + dy * tick);
        ctx.stroke();
      }

      // The sweep. Parked at the top when idle; running when a deck is being
      // read, so the motion means "this is happening" rather than "this is a
      // loading animation".
      if (mode !== "idle") {
        const period = mode === "reading" ? 1600 : 2600;
        const p = ((time % period) / period);
        const y = cy - half * 0.62 + p * half * 1.24;
        const grad = ctx.createLinearGradient(cx - half, y, cx + half, y);
        grad.addColorStop(0, `rgba(${ink.accent},0)`);
        grad.addColorStop(0.5, `rgba(${ink.accent},${(mode === "reading" ? 0.55 : 0.3) * ink.k})`);
        grad.addColorStop(1, `rgba(${ink.accent},0)`);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(cx - half, y);
        ctx.lineTo(cx + half, y);
        ctx.stroke();
      }
    };

    // Hoisted out of the branch below: the restart handler needs to be able
    // to start this loop when motion is switched on later.
    const loop = (now: number) => {
      t = now;
      draw(t);
      raf = requestAnimationFrame(loop);
    };

    if (reduced) draw(0);
    else raf = requestAnimationFrame(loop);

    // A theme change has to repaint even when the loop is parked.
    // Motion can be switched on after this mounted, so the scene owns a
    // restart rather than sampling the preference once and living with it.
    const unsubscribe = onInkChange((next, moving) => {
      ink = next;
      reduced = !moving;
      if (reduced) {
        if (raf) { cancelAnimationFrame(raf); raf = 0; }
        draw(0);
      } else if (!raf) {
        raf = requestAnimationFrame(loop);
      }
    });

    return () => {
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect();
      unsubscribe();
    };
  }, []);

  return (
    <div ref={hostRef} style={{ position: "absolute", inset: 0, pointerEvents: "none" }}>
      <canvas ref={canvasRef} aria-hidden="true" style={{ display: "block", width: "100%", height }} />
    </div>
  );
}
