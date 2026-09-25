/**
 * Two preferences the whole product reads: theme, and motion.
 *
 * WHY THIS EXISTS RATHER THAN A `matchMedia` CALL PER COMPONENT
 *
 * A dozen components were each asking the browser directly whether motion was
 * allowed. That is correct behaviour and it had one bad consequence: a reader
 * whose operating system says "reduce motion" -- which is the default in a
 * good many remote-desktop, VM and preview environments, and was the default
 * in the one this was being reviewed in -- had no way to see the product move,
 * short of changing an OS setting.
 *
 * So the OS preference becomes the DEFAULT rather than the verdict. `auto`
 * follows the system, and a reader who wants motion can turn it on for this
 * product alone. Nothing is remembered on a server and nothing is guessed:
 * until someone chooses, the system's answer stands.
 *
 * HOW IT REACHES CSS
 *
 * Both preferences are written to attributes on <html>:
 *
 *   data-theme="dark" | "light"
 *   data-motion="on" | "off"
 *
 * Stylesheets key off those instead of the media query, so CSS and JavaScript
 * can never disagree about whether this page is allowed to move.
 */

export type ThemeChoice = "dark" | "light";
export type MotionChoice = "auto" | "on" | "off";

const THEME_KEY = "vf:theme";
const MOTION_KEY = "vf:motion";

type State = { theme: ThemeChoice; motion: MotionChoice; motionOn: boolean };

const listeners = new Set<(s: State) => void>();

function systemPrefersReduced(): boolean {
  return typeof window !== "undefined"
    && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
}

function read<T extends string>(key: string, fallback: T, valid: readonly T[]): T {
  try {
    const v = localStorage.getItem(key) as T | null;
    return v && valid.includes(v) ? v : fallback;
  } catch {
    return fallback;                       // private mode, blocked storage
  }
}

const state: State = {
  theme: read<ThemeChoice>(THEME_KEY, "dark", ["dark", "light"]),
  motion: read<MotionChoice>(MOTION_KEY, "auto", ["auto", "on", "off"]),
  motionOn: true,
};

function resolveMotion(): boolean {
  if (state.motion === "on") return true;
  if (state.motion === "off") return false;
  return !systemPrefersReduced();
}

function apply() {
  state.motionOn = resolveMotion();
  if (typeof document === "undefined") return;
  const root = document.documentElement;
  root.dataset.theme = state.theme;
  root.dataset.motion = state.motionOn ? "on" : "off";
  root.style.colorScheme = state.theme;
  listeners.forEach((fn) => fn({ ...state }));
}

/** Call once, as early as possible, so the first paint is already correct. */
export function initPrefs() {
  apply();
  // A reader who changes the OS setting mid-session, while on `auto`, should
  // see the product follow.
  window.matchMedia?.("(prefers-reduced-motion: reduce)")
    .addEventListener?.("change", () => { if (state.motion === "auto") apply(); });
}

export function getPrefs(): State {
  return { ...state };
}

export function setTheme(theme: ThemeChoice) {
  state.theme = theme;
  try { localStorage.setItem(THEME_KEY, theme); } catch { /* non-fatal */ }
  apply();
}

export function setMotion(motion: MotionChoice) {
  state.motion = motion;
  try { localStorage.setItem(MOTION_KEY, motion); } catch { /* non-fatal */ }
  apply();
}

export function subscribePrefs(fn: (s: State) => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/**
 * Whether this page may animate.
 *
 * The single question every motion component asks. It is a plain function
 * rather than a hook because most callers are inside a `useEffect` that sets
 * up a canvas or an observer, where a hook cannot go.
 */
export function motionOn(): boolean {
  return state.motionOn;
}
