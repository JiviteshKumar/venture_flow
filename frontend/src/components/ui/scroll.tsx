import {
  useEffect, useRef, useState,
  type CSSProperties, type ReactNode,
} from "react";
import { motionOn } from "../../lib/prefs";

/**
 * The scroll vocabulary: reveal, pin, progress, tilt.
 *
 * WHY NOT FRAMER MOTION FOR THIS
 *
 * Framer's `whileInView` mounts an observer per element and animates inline
 * styles from JavaScript on every frame. That is fine for a handful of
 * elements and wasteful for a report with sixty of them, because each one
 * holds a render loop open. These use one IntersectionObserver and a CSS
 * class, so the animation runs on the compositor and JavaScript does nothing
 * after the class lands.
 *
 * WHY EVERYTHING DEGRADES TO "VISIBLE"
 *
 * The resting state of `.vf-reveal` is invisible. If the observer never fires
 * -- script blocked, an old browser, a JS error higher up the tree -- the
 * reader gets a blank page instead of an unanimated one. So every component
 * here falls back to the finished state rather than the starting one: on
 * reduced motion, and when IntersectionObserver is missing, the class is
 * applied immediately at mount.
 */

const supportsObserver =
  typeof window !== "undefined" && "IntersectionObserver" in window;

/** The product's motion preference, which defaults to the system's. */
function prefersReducedMotion() {
  return !motionOn();
}

/**
 * Adds `.is-in` the first time the element crosses into view, and never
 * removes it: content that fades back out as you scroll up reads as a fault,
 * not as an effect.
 */
export function Reveal({
  children,
  delay = 0,
  y,
  as: Tag = "div",
  className = "",
  style,
}: {
  children: ReactNode;
  /** Seconds to hold before this one starts, for staggering a row. */
  delay?: number;
  /** Distance travelled, in px. Default comes from the stylesheet. */
  y?: number;
  as?: "div" | "section" | "li" | "article" | "header";
  className?: string;
  style?: CSSProperties;
}) {
  const ref = useRef<HTMLElement | null>(null);
  const [shown, setShown] = useState(() => !supportsObserver || prefersReducedMotion());

  useEffect(() => {
    if (shown || !ref.current) return;
    const el = ref.current;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShown(true);
          observer.disconnect();
        }
      },
      // Fires a little before the element's top edge arrives, so the movement
      // finishes as it reaches comfortable reading position rather than
      // starting there.
      { rootMargin: "0px 0px -12% 0px", threshold: 0.08 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [shown]);

  return (
    <Tag
      ref={ref as never}
      className={`vf-reveal${shown ? " is-in" : ""} ${className}`.trim()}
      style={{
        transitionDelay: delay ? `${delay}s` : undefined,
        ...(y !== undefined && !shown ? { transform: `translate3d(0, ${y}px, 0)` } : null),
        ...style,
      }}
    >
      {children}
    </Tag>
  );
}

/**
 * How far the reader has travelled through an element, 0 to 1.
 *
 * Read on scroll through rAF rather than on every event: a wheel emits far
 * more events than the screen has frames, and doing layout reads in each one
 * is how a scroll-driven page starts to feel heavy.
 */
export function useScrollProgress(ref: React.RefObject<HTMLElement | null>) {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (prefersReducedMotion()) return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const el = ref.current;
      if (!el) return;
      const rect = el.getBoundingClientRect();
      const total = rect.height + window.innerHeight;
      const travelled = window.innerHeight - rect.top;
      setProgress(Math.max(0, Math.min(1, travelled / total)));
    };
    const onScroll = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    measure();
    // The report scrolls inside <main>, not the window, so both are watched.
    const scroller = ref.current?.closest("main") ?? window;
    scroller.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [ref]);

  return progress;
}

/**
 * A surface that turns slightly towards the pointer.
 *
 * Rotation is capped at a few degrees deliberately. Past about 8 the text on
 * the card visibly keystones and the browser re-rasterises it every frame,
 * which reads as blur -- the effect that makes 3D cards look cheap. Small
 * angles plus a moving highlight read as a physical object; large angles read
 * as a gimmick.
 */
export function Tilt({
  children,
  max = 5,
  className = "",
  style,
  glare = true,
}: {
  children: ReactNode;
  max?: number;
  className?: string;
  style?: CSSProperties;
  glare?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [tilt, setTilt] = useState({ x: 0, y: 0, gx: 50, gy: 50, on: false });
  const reduced = prefersReducedMotion();

  const onMove = (e: React.PointerEvent) => {
    // Coarse pointers have no hover: on a phone this would fire on tap and
    // leave the card stuck at an angle.
    if (reduced || e.pointerType !== "mouse" || !ref.current) return;
    const rect = ref.current.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width;
    const py = (e.clientY - rect.top) / rect.height;
    setTilt({
      x: (0.5 - py) * max * 2,
      y: (px - 0.5) * max * 2,
      gx: px * 100,
      gy: py * 100,
      on: true,
    });
  };

  const reset = () => setTilt({ x: 0, y: 0, gx: 50, gy: 50, on: false });

  return (
    <div
      ref={ref}
      className={`vf-tilt ${className}`.trim()}
      onPointerMove={onMove}
      onPointerLeave={reset}
      style={{
        transform: `perspective(900px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)`,
        transition: tilt.on ? "transform 90ms linear" : "transform 500ms var(--ease-out)",
        transformStyle: "preserve-3d",
        position: "relative",
        ...style,
      }}
    >
      {children}
      {glare && !reduced && (
        <span
          aria-hidden="true"
          style={{
            position: "absolute", inset: 0, borderRadius: "inherit",
            pointerEvents: "none",
            opacity: tilt.on ? 1 : 0,
            transition: "opacity 300ms var(--ease-out)",
            background: `radial-gradient(420px circle at ${tilt.gx}% ${tilt.gy}%, rgba(255,255,255,0.10), transparent 60%)`,
          }}
        />
      )}
    </div>
  );
}

/**
 * Display type that assembles itself, word by word.
 *
 * Words, not characters. A character-level reveal on a company name spells it
 * out like a slot machine, and a screen reader announces the letters
 * individually; wrapping each word keeps the name a name. The whole string
 * stays in the DOM, so find-in-page and copy still work.
 */
export function SplitWords({
  text,
  className = "",
  style,
  delay = 0,
  stagger = 0.06,
}: {
  text: string;
  className?: string;
  style?: CSSProperties;
  delay?: number;
  stagger?: number;
}) {
  const words = text.split(" ");
  return (
    <span className={className} style={{ display: "inline-block", ...style }}>
      {words.map((word, i) => (
        <span
          key={`${word}-${i}`}
          style={{
            display: "inline-block",
            // The clip box is what lets a word rise into view from nowhere.
            // Left at the line box it also cut the descenders off -- the g in
            // "investigate" lost its tail. The box is therefore extended below
            // the baseline and pulled back by the same amount, so the clipping
            // edge clears the descenders while the layout is unchanged. The
            // word is at zero opacity for the whole rise, so the taller box
            // never reveals it early.
            overflow: "hidden",
            paddingBottom: "0.22em",
            marginBottom: "-0.22em",
            verticalAlign: "bottom",
          }}
        >
          <Reveal
            as="div"
            delay={delay + i * stagger}
            y={40}
            style={{ display: "inline-block", whiteSpace: "pre" }}
          >
            {word}
            {i < words.length - 1 ? " " : ""}
          </Reveal>
        </span>
      ))}
    </span>
  );
}

/**
 * A pinned act.
 *
 * A scene, one screen tall, whose contents receive a 0-to-1 arrival value
 * as the reader travels through it. That is the mechanic every reference site
 * is built on: the page stops, the content changes, the page resumes. It is
 * what makes a scroll read as a sequence of scenes rather than as a long page.
 *
 * Under reduced motion the act collapses to a single screen with its contents
 * at the end state: no pinning, no scrub, nothing that moves while the reader
 * is trying to read it.
 */
export function Act({
  children,
  length: _length = 2,
  className = "",
  id,
}: {
  /**
   * Called with 0-1 progress and whether motion is suppressed. Keep it cheap:
   * it runs on scroll frames.
   *
   * The second argument matters more than it looks. Under reduced motion the
   * act reports progress 1 -- the end of the scene -- so that everything
   * staged to *arrive* is present. Anything staged to *depart* must therefore
   * check this flag and stay put, or it renders its own exit: which is
   * precisely what happened here. The opening act faded its contents out as it
   * was left behind, so with reduced motion it displayed an empty black
   * screen, and every reader with that OS setting saw nothing at all.
   */
  children: (progress: number, reduced: boolean) => ReactNode;
  /**
   * Retained so callers do not have to change, and no longer used.
   *
   * It set the section's height in viewport heights, which only meant
   * anything while the scene was pinned and the scroll through that height
   * was what scrubbed it. Scenes are one screen each now.
   */
  length?: number;
  className?: string;
  id?: string;
}) {
  const outer = useRef<HTMLElement | null>(null);
  const [progress, setProgress] = useState(0);
  const reduced = prefersReducedMotion();

  useEffect(() => {
    if (reduced) { setProgress(1); return; }
    const el = outer.current;
    if (!el) return;

    let frame = 0;
    const measure = () => {
      frame = 0;
      const rect = el.getBoundingClientRect();
      /**
       * How far this scene has ARRIVED, 0 to 1.
       *
       * 0 when its top edge is at the bottom of the viewport, 1 once its top
       * edge reaches the top. After that it simply scrolls away like any other
       * part of the page, which is why nothing here needs a departure value.
       */
      const travel = Math.max(1, window.innerHeight);
      setProgress(Math.max(0, Math.min(1, 1 - rect.top / travel)));
    };
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(measure); };

    measure();
    const scroller: HTMLElement | Window =
      (el.closest("#vf-scroller") as HTMLElement | null) ?? window;
    scroller.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      scroller.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [reduced]);

  /**
   * WHY THIS IS NO LONGER PINNED
   *
   * It used to be a sticky 100vh child inside a section of length*100vh: the
   * scene held still while the page scrolled past it, and its contents were
   * scrubbed by that scroll. Two faults, and the second was caused by fixing
   * the first.
   *
   * The sticky child is pinned for (length - 1) * 100vh and then slides out
   * over the remaining 100vh. During that slide the act's progress has already
   * reached 1, so its content had finished departing -- and the next scene's
   * content, centred in its own 100vh child, was still below the fold. That
   * was a full screen of nothing between every pair of scenes, eight times
   * down the film.
   *
   * Pulling each section up by a viewport closed the gap and produced
   * something worse: two scenes on screen at once, superimposed, with the
   * bull/bear columns printing through the claims headline. A reader cannot
   * unpick that, and a diligence report is the last place to ask them to.
   *
   * So the pinning is gone. Each scene is one screen tall, they stack, and
   * they scroll past the way a page does -- one at a time, always readable,
   * with no gap to fall into and nothing to overlap. `progress` now measures
   * arrival rather than scrub, so the staging still plays as a scene comes up;
   * it simply leaves by scrolling, like everything else.
   */
  return (
    <section
      id={id}
      ref={outer as never}
      className={`vf-act ${className}`.trim()}
      style={{
        position: "relative",
        minHeight: reduced ? "auto" : "100vh",
        display: "flex",
        flexDirection: "column",
        justifyContent: "center",
      }}
    >
      {children(progress, reduced)}
    </section>
  );
}

/**
 * Kept as a no-op export so pages that mount it do not have to change.
 *
 * It used to carry `.vf-act + .vf-act { margin-top: -100vh }`, the overlap
 * that put two scenes on screen at once. Acts no longer overlap and need no
 * rule of their own.
 */
export function ActStyles() {
  return null;
}

/** Maps a sub-range of an act's progress to 0-1, for staging beats within it. */
export function beat(progress: number, from: number, to: number) {
  if (to <= from) return progress >= to ? 1 : 0;
  return Math.max(0, Math.min(1, (progress - from) / (to - from)));
}

/** Ease for scrubbed values: fast in, settles. */
export const easeOut = (t: number) => 1 - Math.pow(1 - t, 3);

/**
 * A control that leans towards the pointer as it approaches.
 *
 * The element moves a fraction of the distance between its own centre and the
 * pointer, but only once the pointer is inside `radius`. That threshold is the
 * whole trick: an element that reacts from across the screen feels like a bug,
 * and one that reacts only on hover has already been reached. Catching the
 * pointer in the last forty pixels reads as attraction.
 *
 * Mouse only, and nothing at all under reduced motion -- on a touch screen
 * there is no approach to detect, and a control that moves as a finger lands
 * on it is a control that gets missed.
 */
export function Magnetic({
  children,
  radius = 90,
  pull = 0.32,
  className = "",
  style,
}: {
  children: ReactNode;
  radius?: number;
  /** Fraction of the distance travelled. Past ~0.4 the element outruns the pointer. */
  pull?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (prefersReducedMotion() || !window.matchMedia?.("(pointer: fine)").matches) return;

    let frame = 0;
    let tx = 0, ty = 0, cx = 0, cy = 0;

    const tick = () => {
      cx += (tx - cx) * 0.18;
      cy += (ty - cy) * 0.18;
      el.style.transform = `translate3d(${cx.toFixed(2)}px, ${cy.toFixed(2)}px, 0)`;
      // Stop the loop once it has effectively arrived, rather than burning a
      // frame a second forever on a button nobody is near.
      if (Math.abs(tx - cx) > 0.1 || Math.abs(ty - cy) > 0.1) {
        frame = requestAnimationFrame(tick);
      } else {
        frame = 0;
      }
    };

    const onMove = (e: PointerEvent) => {
      const r = el.getBoundingClientRect();
      const dx = e.clientX - (r.left + r.width / 2);
      const dy = e.clientY - (r.top + r.height / 2);
      const near = Math.hypot(dx, dy) < radius + Math.max(r.width, r.height) / 2;
      tx = near ? dx * pull : 0;
      ty = near ? dy * pull : 0;
      if (!frame) frame = requestAnimationFrame(tick);
    };

    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [radius, pull]);

  return (
    <span
      ref={ref}
      className={className}
      style={{ display: "inline-block", willChange: "transform", ...style }}
    >
      {children}
    </span>
  );
}

/**
 * Moves its children against the pointer, by a few pixels.
 *
 * For background objects only. The depth cue works because near things move
 * further than far ones, so `depth` should be larger for whatever is meant to
 * feel closest -- and small everywhere, because a background that visibly
 * swims under the text makes the text hard to read.
 */
export function PointerParallax({
  children,
  depth = 14,
  className = "",
  style,
}: {
  children: ReactNode;
  depth?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (prefersReducedMotion() || !window.matchMedia?.("(pointer: fine)").matches) return;

    let frame = 0;
    let tx = 0, ty = 0, cx = 0, cy = 0;
    const tick = () => {
      cx += (tx - cx) * 0.06;
      cy += (ty - cy) * 0.06;
      el.style.transform = `translate3d(${cx.toFixed(2)}px, ${cy.toFixed(2)}px, 0)`;
      frame = (Math.abs(tx - cx) > 0.05 || Math.abs(ty - cy) > 0.05)
        ? requestAnimationFrame(tick)
        : 0;
    };
    const onMove = (e: PointerEvent) => {
      tx = ((e.clientX / window.innerWidth) - 0.5) * -depth * 2;
      ty = ((e.clientY / window.innerHeight) - 0.5) * -depth * 2;
      if (!frame) frame = requestAnimationFrame(tick);
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    return () => {
      window.removeEventListener("pointermove", onMove);
      if (frame) cancelAnimationFrame(frame);
    };
  }, [depth]);

  return <div ref={ref} className={className} style={{ willChange: "transform", ...style }}>{children}</div>;
}
