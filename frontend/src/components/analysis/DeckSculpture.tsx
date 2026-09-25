import { useEffect, useRef } from "react";
import { motionOn } from "../../lib/prefs";
import { canvasInk, onInkChange } from "../../lib/canvasInk";

/**
 * The deck, as an object.
 *
 * WHAT IT IS
 *
 * Every page of the uploaded deck, drawn as a plane in space, arranged on a
 * slow helix. The planes the extractor actually read are lit; the ones that
 * reached no structured field are dark and hollow. So the sculpture states the
 * report's first and most important caveat -- how much of this deck did we
 * manage to read -- before a single word of it is on screen, and it states it
 * as a shape rather than as a percentage.
 *
 * WHY NOT AN ABSTRACT MESH
 *
 * The references this borrows from hang the page on one object: a twisted
 * ribbon, a volume of black glass. Those are buildings and houses, and the
 * object is the product. Here the product is the reading of a document, so the
 * document is the object. An abstract sculpture would have been the one thing
 * on screen that means nothing.
 *
 * WHY IT IS HAND-WRITTEN
 *
 * Three.js is ~160KB gzipped to draw thirty flat quads with one directional
 * light. This is a perspective projection, a painter's-algorithm depth sort
 * and a Lambert term: it costs nothing, runs on a phone, and it is the same
 * picture.
 *
 * HOW IT MOVES
 *
 * `spin` turns it continuously. `progress` (0-1, driven by the reader's scroll
 * through the opening act) opens the helix out and tips it, so leaving the act
 * takes the object apart rather than simply scrolling it away. The pointer
 * adds a few degrees of parallax and nothing more.
 */

export type DeckPage = {
  /** 1-based page number, as the extractor counted it. */
  slide: number;
  heading?: string;
  /** True when this page reached a structured field. */
  read: boolean;
};

type Vec = { x: number; y: number; z: number };

const rotY = (v: Vec, a: number): Vec => ({
  x: v.x * Math.cos(a) + v.z * Math.sin(a),
  y: v.y,
  z: -v.x * Math.sin(a) + v.z * Math.cos(a),
});

const rotX = (v: Vec, a: number): Vec => ({
  x: v.x,
  y: v.y * Math.cos(a) - v.z * Math.sin(a),
  z: v.y * Math.sin(a) + v.z * Math.cos(a),
});

const sub = (a: Vec, b: Vec): Vec => ({ x: a.x - b.x, y: a.y - b.y, z: a.z - b.z });

const cross = (a: Vec, b: Vec): Vec => ({
  x: a.y * b.z - a.z * b.y,
  y: a.z * b.x - a.x * b.z,
  z: a.x * b.y - a.y * b.x,
});

const norm = (v: Vec): Vec => {
  const l = Math.hypot(v.x, v.y, v.z) || 1;
  return { x: v.x / l, y: v.y / l, z: v.z / l };
};

export default function DeckSculpture({
  pages,
  progress = 0,
  align = "right",
  className,
}: {
  pages: DeckPage[];
  /** 0 at the top of the opening act, 1 as it leaves. */
  progress?: number;
  /**
   * Where the object sits in its frame. The report's opening scene puts it
   * right of centre so the company name owns the left third; the upload target
   * has nothing beside it, so it centres.
   */
  align?: "right" | "center";
  className?: string;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Written by React on every scroll frame, read by the render loop: passing
  // it through state would re-render the component sixty times a second to
  // change one number the canvas owns anyway.
  const progressRef = useRef(progress);
  progressRef.current = progress;

  useEffect(() => {
    const host = hostRef.current;
    const canvas = canvasRef.current;
    if (!host || !canvas || pages.length === 0) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let reduced = !motionOn();
    let ink = canvasInk();

    let width = 0;
    let height = 0;
    const resize = () => {
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      width = host.clientWidth;
      height = host.clientHeight;
      canvas.width = Math.max(1, width * dpr);
      canvas.height = Math.max(1, height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(() => {
      resize();
      if (reduced) renderRef.current?.();
    });
    ro.observe(host);

    let pointer = { x: 0, y: 0 };
    const onMove = (e: PointerEvent) => {
      const r = host.getBoundingClientRect();
      pointer = {
        x: ((e.clientX - r.left) / r.width - 0.5) * 0.5,
        y: ((e.clientY - r.top) / r.height - 0.5) * 0.35,
      };
    };
    const onLeave = () => { pointer = { x: 0, y: 0 }; };
    window.addEventListener("pointermove", onMove, { passive: true });
    host.addEventListener("pointerleave", onLeave);

    // The light, fixed in the scene: a low key from the upper left, which is
    // what gives the lit faces their falloff as the helix turns.
    const light = norm({ x: -0.45, y: 0.72, z: 0.52 });

    const n = pages.length;

    /**
     * A helix for a deck, a fan for a handful.
     *
     * A twenty-five page deck wrapped around two turns reads as a document
     * with depth. The same arrangement with three pages puts each sheet on a
     * different side of the axis, so at any moment most of them are edge-on
     * and the object looks like a few slivers of glass. Below five pages the
     * spread collapses to a shallow fan facing the camera, which is what a
     * short document actually looks like when you hold it.
     */
    // Up to eight pages, a helix puts most sheets edge-on at any moment and
    // the object reads as slivers rather than as a document.
    const few = n <= 8;
    const SPREAD = few ? 0.62 : Math.PI * 2 * 2.1;
    const PLANE_W = few ? 0.78 : n > 18 ? 0.40 : 0.52;
    const PLANE_H = PLANE_W * 0.62;

    let frame = 0;
    let spin = 0;
    let tiltX = 0;
    let tiltY = 0;

    const renderRef: { current: (() => void) | null } = { current: null };

    const render = () => {
      const p = progressRef.current;
      // Eased so the object holds its shape for the first third of the act and
      // then opens; a linear scrub feels like dragging, not like motion.
      const open = p * p;

      if (!reduced) spin += 0.0032;
      tiltX += (pointer.y - tiltX) * 0.05;
      tiltY += (pointer.x - tiltY) * 0.05;

      const yaw = spin + tiltY + open * 0.9;
      const pitch = -0.32 + tiltX + open * 0.55;

      ctx.clearRect(0, 0, width, height);

      // Right of centre on a wide screen when something shares the frame with
      // it; centred otherwise, and always centred when there is no room.
      const offset = align === "right" && width > 900 ? width * 0.2 : 0;
      const cx = width / 2 + offset;
      const cy = height / 2;
      const scale = Math.min(width * 0.30, height * 0.62);
      const focal = 5.4;

      type Face = {
        pts: Array<{ x: number; y: number }>;
        depth: number;
        shade: number;
        page: DeckPage;
        scale: number;
      };
      const faces: Face[] = [];

      for (let i = 0; i < n; i++) {
        const t = n === 1 ? 0.5 : i / (n - 1);
        const angle = few ? (t - 0.5) * SPREAD : t * SPREAD;
        // The arrangement opens outwards and stretches as the act is left behind.
        const radius = few
          ? 0.34 + open * 0.3
          : (0.86 + open * 0.5) * (1 + Math.sin(t * Math.PI) * 0.16);
        const rise = (t - 0.5) * (few ? 0.42 + open * 0.5 : 1.95 + open * 0.8);

        const centre: Vec = {
          x: Math.cos(angle) * radius,
          y: rise,
          z: Math.sin(angle) * radius,
        };

        // Each plane faces outwards along its own radius, with a slight cant
        // so the stack catches the light rather than presenting edge-on.
        const local = [
          { x: -PLANE_W / 2, y: -PLANE_H / 2, z: 0 },
          { x: PLANE_W / 2, y: -PLANE_H / 2, z: 0 },
          { x: PLANE_W / 2, y: PLANE_H / 2, z: 0 },
          { x: -PLANE_W / 2, y: PLANE_H / 2, z: 0 },
        ];

        const world = local.map((corner) => {
          let v = rotX(corner, -0.42);
          v = rotY(v, -angle + Math.PI / 2);
          v = { x: v.x + centre.x, y: v.y + centre.y, z: v.z + centre.z };
          v = rotY(v, yaw);
          v = rotX(v, pitch);
          return v;
        });

        const normal = norm(cross(sub(world[1], world[0]), sub(world[3], world[0])));
        const lambert = Math.max(0, normal.x * light.x + normal.y * light.y + normal.z * light.z);

        const depth = world.reduce((sum, v) => sum + v.z, 0) / 4;
        const persp = focal / (focal + depth);
        if (persp <= 0) continue;

        faces.push({
          pts: world.map((v) => ({
            x: cx + v.x * scale * persp,
            y: cy + v.y * scale * persp,
          })),
          depth,
          shade: lambert,
          page: pages[i],
          scale: persp,
        });
      }

      faces.sort((a, b) => b.depth - a.depth);

      for (const face of faces) {
        const { pts, shade, page, scale: persp } = face;
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let k = 1; k < pts.length; k++) ctx.lineTo(pts[k].x, pts[k].y);
        ctx.closePath();

        if (page.read) {
          // A read page is a solid sheet catching the light.
          const lit = 0.16 + shade * 0.84;
          const g = ctx.createLinearGradient(pts[0].x, pts[0].y, pts[2].x, pts[2].y);
          g.addColorStop(0, `rgba(${ink.line},${(0.10 + lit * 0.62) * ink.k})`);
          g.addColorStop(1, `rgba(${ink.accent},${(0.06 + lit * 0.34) * ink.k})`);
          ctx.fillStyle = g;
          ctx.fill();
          ctx.strokeStyle = `rgba(${ink.line},${(0.22 + lit * 0.5) * ink.k})`;
          ctx.lineWidth = 0.9;
          ctx.stroke();
        } else {
          // An unread page is a hollow frame: present in the deck, absent from
          // the findings. It must not read as "missing" -- it is there, we
          // just could not get anything structured out of it.
          ctx.fillStyle = `rgba(${ink.page},0.55)`;
          ctx.fill();
          ctx.setLineDash([3 * persp, 5 * persp]);
          // Not scaled by ink.k: this edge is the only thing marking an
          // unread page, and it has to survive on both grounds.
          ctx.strokeStyle = `rgba(${ink.bad},${0.18 + shade * 0.34})`;
          ctx.lineWidth = 0.8;
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }

      if (!reduced) frame = requestAnimationFrame(render);
    };

    renderRef.current = render;
    render();

    // Stop when it is not on screen: an animating canvas behind a section the
    // reader has left is heat with no picture.
    const vis = new IntersectionObserver(([entry]) => {
      if (entry.isIntersecting && !frame && !reduced) frame = requestAnimationFrame(render);
      if (!entry.isIntersecting && frame) { cancelAnimationFrame(frame); frame = 0; }
    }, { threshold: 0.02 });
    vis.observe(host);

    // Repaint on a theme change even when the loop is parked.
    // Motion can be switched on after this mounted, so the scene owns a
    // restart rather than sampling the preference once and living with it.
    const unsubscribe = onInkChange((next, moving) => {
      ink = next;
      reduced = !moving;
      if (reduced) {
        if (frame) { cancelAnimationFrame(frame); frame = 0; }
        render();                       // one frame, so the figure still reads
      } else if (!frame) {
        frame = requestAnimationFrame(render);
      }
    });

    return () => {
      unsubscribe();
      if (frame) cancelAnimationFrame(frame);
      ro.disconnect();
      vis.disconnect();
      window.removeEventListener("pointermove", onMove);
      host.removeEventListener("pointerleave", onLeave);
    };
  }, [pages, align]);

  const readCount = pages.filter((p) => p.read).length;

  return (
    <div ref={hostRef} className={className} style={{ position: "absolute", inset: 0 }}>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={
          `The uploaded deck drawn as ${pages.length} pages in space. `
          + `${readCount} are lit, meaning the extractor read them; `
          + `${pages.length - readCount} are outlined, meaning nothing from them `
          + "reached the findings. The same figures are stated in the coverage section."
        }
        style={{ display: "block", width: "100%", height: "100%" }}
      />
    </div>
  );
}
