import { useEffect, useRef } from "react";
import { motionOn } from "../../lib/prefs";
import { canvasInk, onInkChange } from "../../lib/canvasInk";

/**
 * The comparables, in space.
 *
 * WHY THIS AND NOT AN ABSTRACT 3D OBJECT
 *
 * The reference work this borrows from hangs a whole page on one rotating
 * object, and the temptation is to drop in a decorative mesh. A decorative
 * mesh on this product would be the one thing on screen that means nothing --
 * on a tool whose argument is that it shows its working.
 *
 * So the object is the data. Every point is a real company the comparables
 * search returned. Distance from the centre is 1 - similarity, so the
 * companies most like this one sit closest. Colour is the recorded outcome:
 * green exited, red shut down, grey still operating or unknown. The company
 * being analysed is the ring at the centre.
 *
 * WHY IT IS HAND-ROLLED RATHER THAN THREE.JS
 *
 * Three would add ~150KB gzipped to a bundle this project spent a whole pass
 * cutting down, to draw perhaps forty points. This is a perspective
 * projection, a depth sort and one arc per point: about a hundred lines, no
 * dependency, and it runs on a phone.
 *
 * WHAT IT REFUSES TO DO
 *
 * It renders nothing when there are no comparables. An empty starfield would
 * imply a population that was searched and found wanting, when the truth is
 * usually that the search could not run.
 */

export type ComparablePoint = {
  name: string;
  similarity?: number;
  outcome?: string;
  population?: string;
};

type Projected = {
  x: number; y: number; scale: number; depth: number;
  radius: number; colour: string; label: string; alpha: number;
};

/** Which of the three recorded outcomes a comparable falls into. */
const OUTCOME = (outcome?: string): "good" | "bad" | "unknown" => {
  const o = (outcome || "").toLowerCase();
  if (o.includes("acquired") || o.includes("public") || o.includes("ipo") || o.includes("exit")) return "good";
  if (o.includes("shut") || o.includes("dead") || o.includes("closed") || o.includes("inactive")) return "bad";
  return "unknown";
};

export default function Constellation({
  points,
  company,
  height = 420,
}: {
  points: ComparablePoint[];
  /** The company at the centre. */
  company: string;
  height?: number;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host || points.length === 0) return;

    const context = canvas.getContext("2d");
    if (!context) return;

    let reduced = !motionOn();
    let ink = canvasInk();
    const colourOf = (k: "good" | "bad" | "unknown") =>
      k === "good" ? `rgb(${ink.good})`
      : k === "bad" ? `rgb(${ink.bad})`
      : `rgba(${ink.line},0.55)`;

    // Positions are deterministic: the same report draws the same figure every
    // time it is opened. A seeded angle per index, rather than Math.random,
    // which would reshuffle the constellation on every render.
    const nodes = points.map((p, i) => {
      const golden = 2.399963;                      // radians, the golden angle
      const theta = i * golden;
      const phi = Math.acos(1 - (2 * (i + 0.5)) / points.length);
      // 1 - similarity: the closer the match, the closer to the centre.
      const distance = 0.34 + (1 - Math.max(0, Math.min(1, p.similarity ?? 0.5))) * 0.66;
      return {
        x: distance * Math.sin(phi) * Math.cos(theta),
        y: distance * Math.sin(phi) * Math.sin(theta) * 0.62,   // flattened: a sphere reads as a ball, an ellipsoid reads as a field
        z: distance * Math.cos(phi),
        outcome: OUTCOME(p.outcome),
        label: p.name,
        similarity: p.similarity ?? 0,
      };
    });

    let width = 0;
    let dpr = 1;
    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = host.clientWidth;
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();

    const observer = new ResizeObserver(resize);
    observer.observe(host);

    let pointer = { x: 0, y: 0 };
    const onPointer = (e: PointerEvent) => {
      const rect = host.getBoundingClientRect();
      pointer = {
        x: ((e.clientX - rect.left) / rect.width - 0.5) * 0.6,
        y: ((e.clientY - rect.top) / rect.height - 0.5) * 0.4,
      };
    };
    const onLeave = () => { pointer = { x: 0, y: 0 }; };
    host.addEventListener("pointermove", onPointer);
    host.addEventListener("pointerleave", onLeave);

    let frame = 0;
    let angle = 0;
    let tiltTarget = 0;
    let tilt = 0;

    const draw = () => {
      const cx = width / 2;
      const cy = height / 2;
      const scale = Math.min(width, height) * 0.42;

      // Rotation continues while visible; the pointer nudges it rather than
      // driving it, so the figure is never frozen waiting for a mouse.
      if (!reduced) angle += 0.0016;
      tiltTarget = pointer.y;
      tilt += (tiltTarget - tilt) * 0.06;
      const yaw = angle + pointer.x;

      context.clearRect(0, 0, width, height);

      const projected: Projected[] = [];
      for (const node of nodes) {
        // Yaw about the vertical axis, then pitch by the pointer.
        const x1 = node.x * Math.cos(yaw) - node.z * Math.sin(yaw);
        const z1 = node.x * Math.sin(yaw) + node.z * Math.cos(yaw);
        const y1 = node.y * Math.cos(tilt) - z1 * Math.sin(tilt);
        const z2 = node.y * Math.sin(tilt) + z1 * Math.cos(tilt);

        const perspective = 2.6 / (2.6 + z2);      // nearer points draw larger
        projected.push({
          x: cx + x1 * scale * perspective,
          y: cy + y1 * scale * perspective,
          scale: perspective,
          depth: z2,
          radius: (1.6 + node.similarity * 3.4) * perspective,
          colour: colourOf(node.outcome),
          label: node.label,
          alpha: 0.35 + perspective * 0.5,
        });
      }

      // Painter's algorithm: far points first, so near ones overlap them.
      projected.sort((a, b) => b.depth - a.depth);

      // Threads from the centre to the nearest matches. Only the closest few,
      // or the figure turns into a ball of wool.
      const strongest = [...projected].sort((a, b) => b.radius - a.radius).slice(0, 6);
      for (const p of strongest) {
        context.strokeStyle = `rgba(${ink.accent},${(0.05 + p.scale * 0.10) * ink.k})`;
        context.lineWidth = 0.6;
        context.beginPath();
        context.moveTo(cx, cy);
        context.lineTo(p.x, p.y);
        context.stroke();
      }

      for (const p of projected) {
        context.globalAlpha = Math.max(0.12, Math.min(1, p.alpha));
        context.fillStyle = p.colour;
        context.beginPath();
        context.arc(p.x, p.y, Math.max(0.6, p.radius), 0, Math.PI * 2);
        context.fill();

        // A halo on the near side only: it reads as light rather than as a
        // second, blurrier point.
        if (p.scale > 1.02) {
          context.globalAlpha = (p.scale - 1) * 1.6;
          context.beginPath();
          context.arc(p.x, p.y, p.radius * 3.4, 0, Math.PI * 2);
          context.fillStyle = p.colour;
          context.globalAlpha *= 0.12;
          context.fill();
        }
      }
      context.globalAlpha = 1;

      // The company itself: a ring, not a dot, because it is the subject
      // rather than another member of the population.
      context.strokeStyle = `rgba(${ink.line},0.85)`;
      context.lineWidth = 1.2;
      context.beginPath();
      context.arc(cx, cy, 9, 0, Math.PI * 2);
      context.stroke();
      context.fillStyle = `rgba(${ink.line},0.9)`;
      context.beginPath();
      context.arc(cx, cy, 2.4, 0, Math.PI * 2);
      context.fill();

      if (!reduced) frame = requestAnimationFrame(draw);
    };

    draw();

    // A canvas animating behind a page the reader has scrolled past is heat
    // with no picture, so it stops when it leaves the viewport.
    const visibility = new IntersectionObserver((entries) => {
      const visible = entries.some((e) => e.isIntersecting);
      if (visible && !frame && !reduced) {
        frame = requestAnimationFrame(draw);
      } else if (!visible && frame) {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    }, { threshold: 0.05 });
    visibility.observe(host);

    // Motion can be switched on after this mounted, so the scene owns a
    // restart rather than sampling the preference once and living with it.
    const unsubscribe = onInkChange((next, moving) => {
      ink = next;
      reduced = !moving;
      if (reduced) {
        if (frame) { cancelAnimationFrame(frame); frame = 0; }
        draw();
      } else if (!frame) {
        frame = requestAnimationFrame(draw);
      }
    });

    return () => {
      unsubscribe();
      if (frame) cancelAnimationFrame(frame);
      observer.disconnect();
      visibility.disconnect();
      host.removeEventListener("pointermove", onPointer);
      host.removeEventListener("pointerleave", onLeave);
    };
  }, [points, height]);

  if (points.length === 0) return null;

  return (
    <div ref={hostRef} style={{ position: "relative", width: "100%", height }}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={
          `${points.length} comparable companies plotted around ${company}. `
          + "Distance from the centre is how unlike this company each one is; "
          + "green marks an exit, red a shutdown. The same information is in the "
          + "comparables table below."
        }
        style={{ display: "block", width: "100%", height }}
      />
    </div>
  );
}
