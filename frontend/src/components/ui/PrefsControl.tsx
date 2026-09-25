import { useEffect, useState } from "react";
import { Moon, Sun, Waves, Minus } from "lucide-react";
import {
  getPrefs, setTheme, setMotion, subscribePrefs,
  type ThemeChoice, type MotionChoice,
} from "../../lib/prefs";

/**
 * Theme and motion, where the reader can reach them.
 *
 * Two toggles rather than a settings page, because there are two decisions and
 * both are reversible in one click. Each is a real toggle button with
 * `aria-pressed`, so a screen reader is told the current state rather than
 * being asked to infer it from an icon.
 *
 * THE MOTION CONTROL IS NOT A GIMMICK
 *
 * It exists because the operating-system preference is the default here, not
 * the verdict -- see `lib/prefs`. A reader on a machine that reports "reduce
 * motion" (common on remote desktops, VMs and preview environments) would
 * otherwise never be shown the product's motion at all, and a reader who finds
 * the motion tiring can switch it off without leaving the page. Three states
 * would be a worse control than two, so the button flips between `on` and
 * `off` and only starts from `auto`.
 */

export default function PrefsControl({ compact = false }: { compact?: boolean }) {
  const [prefs, setPrefs] = useState(getPrefs);
  useEffect(() => subscribePrefs(setPrefs), []);

  const nextTheme: ThemeChoice = prefs.theme === "dark" ? "light" : "dark";
  const nextMotion: MotionChoice = prefs.motionOn ? "off" : "on";

  return (
    <div className="vf-prefs" data-compact={compact}>
      <style>{`
        .vf-prefs { display: inline-flex; gap: 2px; padding: 2px; border-radius: 999px;
          border: 1px solid var(--line); background: var(--surface); }
        .vf-prefs-btn {
          display: grid; place-items: center;
          width: 28px; height: 28px; border-radius: 999px;
          border: 0; background: transparent; color: var(--text-2);
          cursor: pointer; transition: background var(--dur-fast) var(--ease-out),
            color var(--dur-fast) var(--ease-out), transform var(--dur-fast) var(--ease-out);
        }
        .vf-prefs-btn:hover { background: var(--surface-2); color: var(--text); transform: translateY(-1px); }
        .vf-prefs-btn[aria-pressed="true"] { color: var(--accent); }
        .vf-prefs[data-compact="true"] .vf-prefs-btn { width: 24px; height: 24px; }
        :root[data-motion="off"] .vf-prefs-btn:hover { transform: none; }
      `}</style>

      <button
        type="button"
        className="vf-prefs-btn"
        aria-pressed={prefs.theme === "light"}
        aria-label={"Switch to the " + nextTheme + " theme"}
        title={"Switch to the " + nextTheme + " theme"}
        data-cursor="Turn"
        onClick={() => setTheme(nextTheme)}
      >
        {prefs.theme === "dark" ? <Moon size={14} /> : <Sun size={14} />}
      </button>

      <button
        type="button"
        className="vf-prefs-btn"
        aria-pressed={prefs.motionOn}
        aria-label={prefs.motionOn ? "Turn motion off" : "Turn motion on"}
        title={prefs.motionOn ? "Motion is on" : "Motion is off"}
        data-cursor="Turn"
        onClick={() => setMotion(nextMotion)}
      >
        {prefs.motionOn ? <Waves size={14} /> : <Minus size={14} />}
      </button>
    </div>
  );
}
