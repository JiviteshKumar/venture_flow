import { useMemo, useState } from "react";
import { ExternalLink, ChevronDown } from "lucide-react";

/**
 * Every page the run actually opened, with a way to go and read it.
 *
 * WHY THIS EXISTS
 *
 * The product's whole argument is that it shows its working, and until now the
 * working stopped one step short: a claim was marked supported or refuted, the
 * evidence sentence was quoted, and the page that sentence came from was held
 * in the report and never shown. A reader who wanted to check the check had
 * nowhere to click. That is the difference between a tool that cites and a
 * tool that asserts.
 *
 * WHAT IT SHOWS
 *
 * One row per distinct host, because five links to the same publication is a
 * single source consulted five times and listing them separately overstates
 * how broadly the claim was checked. Each row opens to the individual pages,
 * and each page says which claim it was fetched for.
 *
 * WHERE THE URLS COME FROM
 *
 *   claims.details[].sources   pages fetched to verify one specific claim
 *   market.sources_consulted   pages the market agent read
 *   team.discovery_sources     pages the founder background check read
 *
 * All three are real URLs recorded by the agents at the time of the run; none
 * are reconstructed or guessed here.
 *
 * WHAT IT REFUSES TO DO
 *
 * It renders nothing at all when no source was recorded. A "Sources" heading
 * over an empty box would imply the run searched and found nothing, when the
 * honest reading is usually that the search never ran -- which the report says
 * elsewhere, in its own words.
 *
 * Links carry `rel="noopener noreferrer"` and open in a new tab: these are
 * arbitrary third-party pages the run happened to retrieve, and they should
 * not be able to reach back into the report that cites them.
 */

export type SourceRef = {
  url: string;
  /** What the run was checking when it fetched this. */
  context: string;
};

type Host = {
  host: string;
  refs: SourceRef[];
};

/** The bit a person recognises: "reuters.com", not "www.reuters.com/a/b?c=d". */
function hostOf(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    // Not a URL. Shown verbatim rather than dropped: something was recorded,
    // and silently discarding it would misstate how much was consulted.
    return url.slice(0, 60);
  }
}

/** The path, trimmed to something readable in a row. */
function pathOf(url: string): string {
  try {
    const u = new URL(url);
    const p = (u.pathname + u.search).replace(/\/$/, "");
    return p && p !== "/" ? decodeURIComponent(p).slice(0, 72) : u.hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 72);
  }
}

export default function SourceList({ sources }: { sources: SourceRef[] }) {
  const hosts = useMemo<Host[]>(() => {
    const byHost = new Map<string, SourceRef[]>();
    const seen = new Set<string>();
    for (const ref of sources) {
      if (!ref.url || seen.has(ref.url)) continue;   // the same page cited twice is one page
      seen.add(ref.url);
      const h = hostOf(ref.url);
      const list = byHost.get(h);
      if (list) list.push(ref);
      else byHost.set(h, [ref]);
    }
    return [...byHost.entries()]
      .map(([host, refs]) => ({ host, refs }))
      .sort((a, b) => b.refs.length - a.refs.length || a.host.localeCompare(b.host));
  }, [sources]);

  const [open, setOpen] = useState<string | null>(null);

  if (hosts.length === 0) return null;

  const total = hosts.reduce((n, h) => n + h.refs.length, 0);

  return (
    <div className="src">
      <style>{`
        .src { display: grid; gap: 8px; }
        .src-count {
          font-family: var(--font-sans); font-size: 12.5px; color: var(--text-3);
          margin-bottom: 2px;
        }
        .src-host {
          border: 1px solid var(--line); border-radius: var(--radius);
          background: var(--surface); overflow: hidden;
          transition: border-color var(--dur-fast) var(--ease-out),
                      box-shadow var(--dur-fast) var(--ease-out),
                      transform var(--dur-fast) var(--ease-out);
        }
        .src-host:hover { border-color: var(--line-strong); box-shadow: var(--e-1); }
        :root[data-motion="on"] .src-host:hover { transform: translateY(-1px); }

        .src-head {
          width: 100%; display: flex; align-items: center; gap: 10px;
          padding: 12px 14px; background: transparent; border: 0;
          text-align: left; cursor: pointer; color: var(--text);
          font-family: var(--font-sans); font-size: 13.5px; font-weight: 600;
        }
        .src-favicon {
          width: 22px; height: 22px; border-radius: 6px; flex-shrink: 0;
          display: grid; place-items: center;
          background: var(--surface-3); border: 1px solid var(--line);
          font-family: var(--font-sans); font-size: 10px; font-weight: 700;
          letter-spacing: 0.02em; color: var(--text-3);
        }
        .src-n {
          margin-left: auto; font-family: var(--font-sans); font-size: 12px;
          font-weight: 600; color: var(--text-3);
          background: var(--surface-2); border: 1px solid var(--line);
          padding: 2px 8px; border-radius: 999px;
        }
        .src-caret {
          color: var(--text-3); flex-shrink: 0;
          transition: transform var(--dur-base) var(--ease-out);
        }
        .src-head[aria-expanded="true"] .src-caret { transform: rotate(180deg); }

        .src-pages { border-top: 1px solid var(--line); }
        .src-page {
          display: flex; align-items: flex-start; gap: 10px;
          padding: 11px 14px; border-bottom: 1px solid var(--line);
          text-decoration: none; color: var(--text-2);
          transition: background var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
        }
        .src-page:last-child { border-bottom: 0; }
        .src-page:hover { background: var(--surface-2); color: var(--text); }
        .src-page-body { min-width: 0; flex: 1; }
        .src-page-path {
          font-family: var(--font-mono); font-size: 12px;
          overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
        }
        .src-page-ctx {
          font-family: var(--font-sans); font-size: 12px; color: var(--text-3);
          margin-top: 3px; line-height: 1.5;
        }
        .src-page svg { margin-top: 2px; flex-shrink: 0; opacity: 0.6; }
        .src-page:hover svg { opacity: 1; }
      `}</style>

      <p className="src-count">
        {total} {total === 1 ? "page" : "pages"} across {hosts.length}{" "}
        {hosts.length === 1 ? "site" : "sites"}. Every link below was opened during this run.
      </p>

      {hosts.map((h) => {
        const expanded = open === h.host;
        return (
          <div className="src-host" key={h.host}>
            <button
              type="button"
              className="src-head"
              aria-expanded={expanded}
              data-cursor={expanded ? "Close" : "Open"}
              onClick={() => setOpen(expanded ? null : h.host)}
            >
              {/* A monogram, not a favicon.
                  This asked Google's favicon service for each host's icon,
                  which meant every site the run consulted was announced to a
                  third party as soon as a reader opened the report -- the list
                  of companies someone is diligencing is exactly the sort of
                  thing that should not leave the page. It also 404'd for any
                  host without an icon, filling the console. Two letters off
                  the hostname carry the same "which site is this" signal at no
                  privacy cost and no request. */}
              <span className="src-favicon" aria-hidden="true">{h.host.slice(0, 2).toUpperCase()}</span>
              {h.host}
              <span className="src-n">{h.refs.length}</span>
              <ChevronDown className="src-caret" size={15} />
            </button>

            {expanded && (
              <div className="src-pages">
                {h.refs.map((ref) => (
                  <a
                    key={ref.url}
                    className="src-page"
                    href={ref.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-cursor="Visit"
                  >
                    <div className="src-page-body">
                      <div className="src-page-path" title={ref.url}>{pathOf(ref.url)}</div>
                      <div className="src-page-ctx">{ref.context}</div>
                    </div>
                    <ExternalLink size={13} />
                  </a>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
