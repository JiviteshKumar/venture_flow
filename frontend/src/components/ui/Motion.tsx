import { motion, useReducedMotion, useInView, type Variants } from "framer-motion";
import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

/**
 * The app's motion vocabulary, in one place.
 *
 * WHY THIS EXISTS
 *
 * Animation was previously written inline, per component, with whatever
 * duration and easing each one happened to type -- 0.2s here, 0.5s there,
 * default easing in most places. The result is an interface where nothing
 * moves at the same tempo, which reads as unfinished even when every
 * individual animation is fine. These primitives are the tempo.
 *
 * REDUCED MOTION IS HONOURED IN JAVASCRIPT, NOT ONLY IN CSS
 *
 * `tailwind.css` already collapses CSS animations under
 * `prefers-reduced-motion`, but Framer Motion animates inline styles from JS,
 * which that media query cannot reach. Every component here calls
 * `useReducedMotion` and degrades to an instant, non-moving state: content
 * still appears, it simply does not travel. Vestibular-disorder guidance is
 * that large-area movement is the problem, not the interface responding.
 *
 * THE HOUSE RULES
 *
 *   - Entry animations move a short distance (8-16px) and fade in. Anything
 *     that flies further reads as decoration rather than as the page settling.
 *   - Easing is `ease-out` on entry so a thing arrives fast and lands gently.
 *   - Nothing loops. A permanently animating element is a permanent
 *     distraction, and this is a tool people read carefully.
 */

// Matches the --dur-* and --ease-* tokens in tailwind.css. Duplicated as
// numbers here because Framer Motion needs seconds, not CSS strings.
export const DURATION = { fast: 0.16, base: 0.24, slow: 0.42 } as const;
export const EASE_OUT = [0.16, 1, 0.3, 1] as const;
export const EASE_SPRING = [0.34, 1.56, 0.64, 1] as const;

/**
 * Fade and rise. The default entry for anything that appears on load.
 *
 * `delay` staggers a handful of siblings by hand; for a list, use
 * `<Stagger>` instead, which does not require every child to know its index.
 */
export function FadeIn({
  children,
  delay = 0,
  y = 12,
  duration = DURATION.base,
  className,
  style,
}: {
  children: ReactNode;
  delay?: number;
  y?: number;
  duration?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      style={style}
      initial={reduced ? { opacity: 0 } : { opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: reduced ? DURATION.fast : duration, delay, ease: EASE_OUT }}
    >
      {children}
    </motion.div>
  );
}

/** Container whose children animate in one after another. Pair with `<StaggerItem>`. */
export function Stagger({
  children,
  gap = 0.05,
  delay = 0,
  className,
  style,
}: {
  children: ReactNode;
  gap?: number;
  delay?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const reduced = useReducedMotion();
  const variants: Variants = {
    hidden: {},
    show: {
      transition: {
        staggerChildren: reduced ? 0 : gap,
        delayChildren: reduced ? 0 : delay,
      },
    },
  };
  return (
    <motion.div
      className={className}
      style={style}
      variants={variants}
      initial="hidden"
      animate="show"
    >
      {children}
    </motion.div>
  );
}

export function StaggerItem({
  children,
  y = 10,
  className,
  style,
}: {
  children: ReactNode;
  y?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const reduced = useReducedMotion();
  const variants: Variants = {
    hidden: reduced ? { opacity: 0 } : { opacity: 0, y },
    show: {
      opacity: 1,
      y: 0,
      transition: { duration: DURATION.base, ease: EASE_OUT },
    },
  };
  return (
    <motion.div className={className} style={style} variants={variants}>
      {children}
    </motion.div>
  );
}

/**
 * Animates in the first time it scrolls into view, then stops watching.
 *
 * `once: true` matters: an element that re-animates every time it re-enters
 * the viewport turns ordinary scrolling into a light show, and on a long
 * report that is actively unpleasant to read.
 */
export function Reveal({
  children,
  y = 16,
  className,
  style,
}: {
  children: ReactNode;
  y?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const reduced = useReducedMotion();
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, margin: "-60px" });
  return (
    <motion.div
      ref={ref}
      className={className}
      style={style}
      initial={reduced ? { opacity: 0 } : { opacity: 0, y }}
      animate={inView ? { opacity: 1, y: 0 } : undefined}
      transition={{ duration: DURATION.slow, ease: EASE_OUT }}
    >
      {children}
    </motion.div>
  );
}

/**
 * Counts up to a number.
 *
 * Used for scores, which are the thing a reader looks at first. The count is
 * deliberately short and eases out, so the final value is legible almost
 * immediately rather than being withheld for effect.
 *
 * Under reduced motion the final value is rendered directly -- a number
 * changing 40 times a second is exactly the kind of movement the preference
 * exists to stop.
 */
export function CountUp({
  value,
  duration = 0.9,
  decimals = 0,
  className,
  style,
}: {
  value: number;
  duration?: number;
  decimals?: number;
  className?: string;
  style?: CSSProperties;
}) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(reduced ? value : 0);

  useEffect(() => {
    if (reduced) {
      setShown(value);
      return;
    }
    let frame = 0;
    const started = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - started) / (duration * 1000));
      // easeOutCubic: fast at first, settles onto the value.
      setShown(value * (1 - Math.pow(1 - t, 3)));
      if (t < 1) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value, duration, reduced]);

  return (
    <span className={className} style={style}>
      {shown.toFixed(decimals)}
    </span>
  );
}

/**
 * A surface that lifts slightly under the pointer.
 *
 * Hover feedback is suppressed on touch devices via `@media (hover: hover)` in
 * the caller's CSS where it matters; here the transform is cheap enough
 * (compositor-only) that a stray hover state costs nothing.
 */
export function Lift({
  children,
  className,
  style,
  disabled = false,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  disabled?: boolean;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      style={style}
      whileHover={disabled || reduced ? undefined : { y: -2 }}
      whileTap={disabled || reduced ? undefined : { scale: 0.995 }}
      transition={{ duration: DURATION.fast, ease: EASE_OUT }}
    >
      {children}
    </motion.div>
  );
}

/**
 * A bar that grows to `pct` on first paint.
 *
 * Width is animated rather than transform-scaled because the bar has a rounded
 * cap: scaling would squash the radius, which looks wrong at small sizes.
 */
export function GrowBar({
  pct,
  color,
  height = 4,
  delay = 0,
  track = "rgba(15,23,42,0.07)",
}: {
  pct: number;
  color: string;
  height?: number;
  delay?: number;
  track?: string;
}) {
  const reduced = useReducedMotion();
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div
      style={{
        height, background: track, borderRadius: height,
        overflow: "hidden", width: "100%",
      }}
    >
      <motion.div
        style={{ height: "100%", background: color, borderRadius: height }}
        initial={{ width: reduced ? `${clamped}%` : 0 }}
        animate={{ width: `${clamped}%` }}
        transition={{ duration: reduced ? 0 : DURATION.slow, delay, ease: EASE_OUT }}
      />
    </div>
  );
}
