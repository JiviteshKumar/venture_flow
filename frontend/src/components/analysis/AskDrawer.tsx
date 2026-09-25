import { useEffect, useRef, useState, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { MessageSquare, X } from "lucide-react";
import { DURATION, EASE_OUT } from "../ui/Motion";

/**
 * The chat and the notes, docked.
 *
 * WHY THEY LEFT THE PAGE
 *
 * They lived in a 320px column pinned beside the report for its entire
 * length. On a report that is mostly one column of findings that column was
 * empty below its first 500 pixels -- and it cost the findings a quarter of
 * the width, which is the difference between a table that fits and a table
 * that scrolls sideways.
 *
 * Docking them costs one click and returns the page to a single measure,
 * which is what the chaptered layout needs. The button says what is behind
 * it, and the panel remembers nothing: it is the same chat, mounted once and
 * hidden, so a conversation survives being closed.
 */
export default function AskDrawer({
  chat,
  notes,
}: {
  chat: ReactNode;
  notes: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const reduced = useReducedMotion();
  const panelRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // Escape closes, and focus returns to the button that opened it -- a panel
  // that traps a keyboard user is worse than no panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <>
      <style>{`
        .ad-fab {
          position: fixed; right: 26px; bottom: 26px; z-index: 60;
          display: inline-flex; align-items: center; gap: 9px;
          padding: 13px 20px; border-radius: 999px; cursor: pointer;
          border: 1px solid color-mix(in srgb, var(--text-on-ink) 16%, transparent);
          background: var(--ink-1); color: var(--text-on-ink);
          font-family: var(--font-sans); font-size: 13.5px; font-weight: 600;
          box-shadow: var(--e-2);
          transition: transform var(--dur-fast) var(--ease-out),
                      box-shadow var(--dur-base) var(--ease-out);
        }
        .ad-fab:hover { transform: translateY(-2px); box-shadow: var(--e-3); }

        .ad-scrim {
          position: fixed; inset: 0; z-index: 70;
          background: rgba(5,7,13,0.42); backdrop-filter: blur(2px);
        }

        .ad-panel {
          position: fixed; top: 0; right: 0; bottom: 0; z-index: 71;
          width: min(420px, 100vw);
          background: var(--surface);
          border-left: 1px solid var(--border);
          box-shadow: -24px 0 60px rgba(15,23,42,0.18);
          display: flex; flex-direction: column;
        }
        .ad-head {
          display: flex; align-items: center; justify-content: space-between;
          padding: 18px 20px; border-bottom: 1px solid var(--border);
        }
        .ad-body { flex: 1; overflow-y: auto; padding: 16px 20px 28px; }
        .ad-close {
          display: inline-flex; padding: 7px; border-radius: 8px; cursor: pointer;
          background: transparent; border: 1px solid var(--border); color: var(--text-muted);
          transition: color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
        }
        .ad-close:hover { color: var(--text-primary); border-color: var(--border-strong); }

        @media (max-width: 640px) { .ad-fab { right: 16px; bottom: 16px; } }
      `}</style>

      <button
        ref={buttonRef}
        type="button"
        className="ad-fab"
        data-cursor="Ask"
        onClick={() => setOpen(true)}
        aria-expanded={open}
        aria-haspopup="dialog"
      >
        <MessageSquare size={16} />
        Ask this deck
      </button>

      <AnimatePresence>
        {open && (
          <>
            <motion.div
              className="ad-scrim"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: reduced ? 0 : DURATION.fast }}
              onClick={() => setOpen(false)}
            />
            <motion.div
              ref={panelRef}
              className="ad-panel"
              role="dialog"
              aria-label="Ask this deck, and notes"
              initial={reduced ? { opacity: 0 } : { x: "100%" }}
              animate={reduced ? { opacity: 1 } : { x: 0 }}
              exit={reduced ? { opacity: 0 } : { x: "100%" }}
              transition={{ duration: reduced ? 0 : DURATION.base, ease: EASE_OUT }}
            >
              <div className="ad-head">
                <div style={{ fontSize: 15, fontWeight: 600 }}>This deck</div>
                <button
                  type="button"
                  className="ad-close"
                  onClick={() => { setOpen(false); buttonRef.current?.focus(); }}
                  aria-label="Close"
                >
                  <X size={15} />
                </button>
              </div>
              <div className="ad-body">
                {chat}
                {notes}
              </div>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </>
  );
}
