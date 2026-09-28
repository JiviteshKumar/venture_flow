import { useEffect, useRef } from "react";
import { Search, Globe, AlertCircle } from "lucide-react";
import type { ActivityEntry } from "../../services/apiClient";

/**
 * What the pipeline is reading, while it reads it.
 *
 * WHY THIS EXISTS
 *
 * The run reports seven stage labels over five to ten minutes. Between
 * "Verifying claims against live web search" and the next one, the product
 * goes quiet for minutes while it runs dozens of real searches and opens
 * dozens of real pages -- and the screen showed a spinner and a word. A reader
 * watching that cannot tell a slow analysis from a hung one, and gets no sense
 * that anything is being looked up at all. The work is the most interesting
 * thing this product does and it was the least visible part of it.
 *
 * EVERY ROW IS A NETWORK CALL THAT HAPPENED
 *
 * Nothing here is generated to fill the panel. The server records each search
 * and each page fetch at the moment it makes it (see `live_activity.py`) and
 * this renders that list. When the pipeline is thinking rather than fetching,
 * no new row appears -- which is the truth, and the alternative would be a
 * progress animation pretending to be evidence.
 *
 * Failed fetches are shown too. A feed of nothing but successes would imply a
 * tidier run than actually happened, and "this page would not load" is a real
 * thing to know about a source.
 *
 * WHY IT DOES NOT SCROLL ITSELF WHEN YOU ARE READING IT
 *
 * New rows arrive every few seconds. Jumping to the bottom regardless would
 * snatch the panel away from someone who scrolled up to look at a URL, so it
 * follows only while already at the bottom -- the rule a chat log uses, for
 * the same reason.
 */

function relative(at: number, now: number): string {
  const s = Math.max(0, Math.round(now - at));
  if (s < 2) return "just now";
  if (s < 60) return `${s}s ago`;
  return `${Math.floor(s / 60)}m ago`;
}

export default function LiveFeed({ entries }: { entries: ActivityEntry[] }) {
  const scroller = useRef<HTMLDivElement>(null);
  const pinned = useRef(true);

  // Follow the tail, unless the reader has scrolled away from it.
  useEffect(() => {
    const el = scroller.current;
    if (!el || !pinned.current) return;
    el.scrollTop = el.scrollHeight;
  }, [entries]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 28;
  };

  if (entries.length === 0) return null;

  const now = Date.now() / 1000;

  return (
    <div className="lf">
      <style>{`
        .lf { margin-top: 14px; }
        .lf-head {
          display: flex; align-items: center; gap: 8px;
          font-family: var(--font-sans); font-size: 11px; font-weight: 600;
          letter-spacing: 0.12em; text-transform: uppercase; color: var(--text-3);
          margin-bottom: 8px;
        }
        .lf-live {
          width: 6px; height: 6px; border-radius: 50%; background: var(--accent);
          animation: lf-pulse 1.6s ease-in-out infinite;
        }
        @keyframes lf-pulse {
          0%, 100% { opacity: 0.35; transform: scale(0.85); }
          50%      { opacity: 1;    transform: scale(1.15); }
        }
        :root[data-motion="off"] .lf-live { animation: none; opacity: 1; }

        .lf-scroll {
          max-height: 176px; overflow-y: auto;
          border: 1px solid var(--line); border-radius: var(--radius);
          background: var(--surface);
        }
        .lf-row {
          display: flex; align-items: baseline; gap: 9px;
          padding: 8px 12px;
          border-bottom: 1px solid var(--line);
          font-family: var(--font-sans); font-size: 12.5px;
          animation: lf-in 420ms var(--ease-out) both;
        }
        .lf-row:last-child { border-bottom: 0; }
        @keyframes lf-in {
          from { opacity: 0; transform: translate3d(0, 6px, 0); }
          to   { opacity: 1; transform: none; }
        }
        :root[data-motion="off"] .lf-row { animation: none; }

        .lf-icon { flex-shrink: 0; position: relative; top: 2px; color: var(--text-3); }
        .lf-row[data-kind="search"] .lf-icon { color: var(--accent); }
        .lf-row[data-failed="true"] .lf-icon { color: var(--caution); }

        .lf-body { min-width: 0; flex: 1; }
        .lf-what { color: var(--text-2); }
        .lf-host {
          color: var(--text); font-weight: 600;
          overflow-wrap: anywhere;
        }
        .lf-link { color: var(--accent); text-decoration: none; }
        .lf-link:hover { text-decoration: underline; }
        .lf-when {
          flex-shrink: 0; font-size: 11px; color: var(--text-faint);
          font-variant-numeric: tabular-nums;
        }
      `}</style>

      <div className="lf-head">
        <span className="lf-live" aria-hidden="true" />
        Live — {entries.length} {entries.length === 1 ? "call" : "calls"} so far
      </div>

      <div
        className="lf-scroll"
        ref={scroller}
        onScroll={onScroll}
        role="log"
        aria-live="polite"
        aria-label="What the analysis is fetching"
      >
        {entries.map((e, i) => {
          const failed = e.ok === false;
          return (
            <div
              className="lf-row"
              key={`${e.at}-${i}`}
              data-kind={e.kind}
              data-failed={failed}
            >
              <span className="lf-icon" aria-hidden="true">
                {e.kind === "search"
                  ? <Search size={13} />
                  : failed ? <AlertCircle size={13} /> : <Globe size={13} />}
              </span>
              <span className="lf-body">
                {e.kind === "search" ? (
                  <>
                    <span className="lf-what">Searched </span>
                    <span className="lf-host">{e.detail}</span>
                  </>
                ) : (
                  <>
                    <span className="lf-what">{e.detail} </span>
                    {e.url ? (
                      <a
                        className="lf-link"
                        href={e.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        data-cursor="Visit"
                        title={e.url}
                      >
                        {e.host || e.url}
                      </a>
                    ) : (
                      <span className="lf-host">{e.host}</span>
                    )}
                  </>
                )}
              </span>
              <span className="lf-when">{relative(e.at, now)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
