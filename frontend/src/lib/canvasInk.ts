import { getPrefs, subscribePrefs } from "./prefs";

/**
 * Colour for the things drawn on a canvas.
 *
 * WHY THIS EXISTS
 *
 * The rest of the product themes itself with CSS custom properties, which a
 * canvas cannot read: `ctx.strokeStyle` wants a colour, not a `var()`. So the
 * four hand-drawn scenes -- the intake aperture, the deck sculpture, the
 * comparables constellation and the room behind everything -- each had a
 * palette baked in, tuned for a near-black page. On white those scenes were
 * pale blue on pale grey, which is to say invisible.
 *
 * They now ask here instead. Components are given channel triples ("r,g,b")
 * rather than finished colours, because every one of them composes its own
 * alpha per stroke -- depth, shading, a fade -- and a finished `rgba()` string
 * cannot be re-alphaed without string surgery.
 *
 * `k` is the one concession to how the two themes actually behave: light
 * subtracts and dark adds, and a stroke that reads clearly on black is far too
 * heavy on white, so each scene multiplies its alphas by it.
 */

export type CanvasInk = {
  /** The surface being drawn on, for knocking holes in things. */
  page: string;
  /** The main drawing colour: hairlines, edges, labels. */
  line: string;
  /** The accent, for anything the reader is meant to follow. */
  accent: string;
  /** Recorded outcomes. */
  good: string;
  bad: string;
  /** Multiplier applied to every alpha in the scene. */
  k: number;
};

const DARK: CanvasInk = {
  page: "10,14,24",
  line: "226,238,255",
  accent: "143,182,255",
  good: "53,208,141",
  bad: "255,124,110",
  k: 1,
};

const LIGHT: CanvasInk = {
  page: "255,255,255",
  line: "24,36,60",
  accent: "47,107,255",
  good: "4,120,87",
  bad: "190,45,38",
  // Ink on paper carries at well under half the weight light needs on black.
  k: 0.62,
};

export function canvasInk(): CanvasInk {
  return getPrefs().theme === "light" ? LIGHT : DARK;
}

/**
 * Run `fn` whenever either preference changes, with the palette to draw in
 * and whether the scene is allowed to move. Returns the unsubscribe, so an
 * effect can hand it straight back.
 *
 * Both arrive together because a scene that repaints on a theme change but
 * not on a motion change is the bug this pass was chasing: the reader turns
 * motion on and the picture sits there, frozen, until the page is reloaded.
 */
export function onInkChange(fn: (ink: CanvasInk, moving: boolean) => void): () => void {
  return subscribePrefs((s) => fn(s.theme === "light" ? LIGHT : DARK, s.motionOn));
}
