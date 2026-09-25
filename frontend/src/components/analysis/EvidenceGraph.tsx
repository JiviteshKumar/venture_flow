import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle, ArrowUpRight, Check, CircleHelp, Database, FileSearch, Gavel, X,
} from "lucide-react";
import type { ClaimDetail } from "../../services/apiClient";
import { Badge, type Tone } from "../ui/Surface";
import { motionOn } from "../../lib/prefs";

/**
 * Why the system reached its verdict, claim by claim.
 *
 * WHAT IT IS
 *
 * Every claim the pipeline checked is a node. Selecting one traces the chain
 * that produced its verdict, in the order it happened:
 *
 *   the claim as the deck stated it
 *     -> the evidence the search actually returned
 *       -> the sources that evidence came from
 *         -> the verdict, and how confident the model was in it
 *
 * WHY THE CHAIN IS DRAWN RATHER THAN LISTED
 *
 * A table of verdicts asks the reader to trust the column. This product's
 * argument is that they should not have to: the whole point of a diligence
 * tool is that a partner can follow any conclusion back to the page it came
 * from and disagree with it. So the route from claim to source is the primary
 * object on screen, and the verdict is the end of it rather than the headline.
 *
 * WHAT IT REFUSES TO FLATTEN
 *
 *   - NOT_ENOUGH_INFO is not a failure and is never drawn as one. For an
 *     internal metric -- ARR, headcount, burn -- no public source exists to
 *     confirm it, and the router says so in `claim_kind`. Marking that red
 *     would tell a reader the company had been caught out.
 *   - A cached verdict says it is cached. It was reached earlier, against
 *     sources that may since have changed.
 *   - Zero sources is stated as zero sources, not hidden behind a confidence
 *     percentage.
 */

type Props = {
  claims: ClaimDetail[];
  /** When verification never ran at all, the graph says that instead of
   *  rendering an empty frame that looks like "nothing was found". */
  degraded?: boolean;
};

const VERDICT: Record<string, { tone: Tone; label: string; icon: typeof Check }> = {
  SUPPORTS:        { tone: "verified", label: "Supported",  icon: Check },
  REFUTES:         { tone: "critical", label: "Refuted",    icon: X },
  NOT_ENOUGH_INFO: { tone: "neutral",  label: "Unsettled",  icon: CircleHelp },
};

const verdictOf = (c: ClaimDetail) => VERDICT[c.verdict] ?? VERDICT.NOT_ENOUGH_INFO;

const hostOf = (url: string) => {
  try { return new URL(url).hostname.replace(/^www\./, ""); }
  catch { return url.slice(0, 40); }
};

export default function EvidenceGraph({ claims, degraded = false }: Props) {
  const [selected, setSelected] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const active = claims[selected];

  // Roving focus: one tab stop for the whole list, arrows move within it.
  const onKeyDown = (e: React.KeyboardEvent) => {
    let next = selected;
    if (e.key === "ArrowDown" || e.key === "ArrowRight") next = (selected + 1) % claims.length;
    else if (e.key === "ArrowUp" || e.key === "ArrowLeft") next = (selected - 1 + claims.length) % claims.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = claims.length - 1;
    else return;
    e.preventDefault();
    setSelected(next);
    itemRefs.current[next]?.focus();
  };

  const counts = useMemo(() => ({
    supported: claims.filter((c) => c.verdict === "SUPPORTS").length,
    refuted: claims.filter((c) => c.verdict === "REFUTES").length,
    unsettled: claims.filter((c) => c.verdict === "NOT_ENOUGH_INFO").length,
  }), [claims]);

  if (degraded) {
    return (
      <div className="eg-empty">
        <style>{EG_CSS}</style>
        <AlertTriangle size={18} color="var(--caution)" />
        <div>
          <div style={{ fontWeight: 600, fontSize: 14.5, marginBottom: 4 }}>
            Claim verification did not run
          </div>
          <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.65, color: "var(--text-2)", maxWidth: "58ch" }}>
            The language model was unavailable while this deck was analysed, so no claim
            was checked against public sources. Nothing was established either way, and
            the score has not been reduced for it. Re-running the analysis will check them.
          </p>
        </div>
      </div>
    );
  }

  if (claims.length === 0) {
    return (
      <div className="eg-empty">
        <style>{EG_CSS}</style>
        <FileSearch size={18} color="var(--text-3)" />
        <div>
          <div style={{ fontWeight: 600, fontSize: 14.5, marginBottom: 4 }}>
            No checkable claim was found in this deck
          </div>
          <p style={{ margin: 0, fontSize: 13.5, lineHeight: 1.65, color: "var(--text-2)", maxWidth: "58ch" }}>
            A claim has to be specific enough to search for. Decks made largely of
            positioning statements produce none, which is a fact about the deck rather
            than a finding about the company.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="eg-root">
      <style>{EG_CSS}</style>

      <div className="eg-summary">
        <Badge tone="verified" size="sm">{counts.supported} supported</Badge>
        {counts.refuted > 0 && <Badge tone="critical" size="sm">{counts.refuted} refuted</Badge>}
        {counts.unsettled > 0 && <Badge tone="neutral" size="sm">{counts.unsettled} unsettled</Badge>}
      </div>

      <div className="eg-grid">
        {/* ── The claims ─────────────────────────────────────────────────── */}
        {/* Roving tabindex, not aria-activedescendant: the options are real
            buttons that take focus themselves, so the list is one tab stop and
            the arrow keys move within it. Mixing the two patterns is what the
            lint rule is there to catch. */}
        <div ref={listRef} className="eg-list" role="listbox" aria-label="Checked claims">
          {claims.map((c, i) => {
            const v = verdictOf(c);
            const Icon = v.icon;
            const on = i === selected;
            return (
              <button
                key={`${c.claim}-${i}`}
                id={`eg-claim-${i}`}
                ref={(el) => { itemRefs.current[i] = el; }}
                role="option"
                aria-selected={on}
                tabIndex={on ? 0 : -1}
                className="eg-claim"
                data-on={on}
                data-tone={v.tone}
                data-cursor="Trace"
                onClick={() => setSelected(i)}
                onKeyDown={onKeyDown}
              >
                <span className="eg-claim-index vf-num">{String(i + 1).padStart(2, "0")}</span>
                <span className="eg-claim-body">
                  <span className="eg-claim-text">{c.claim}</span>
                  <span className="eg-claim-meta">
                    <Icon size={12} />
                    {v.label}
                    <span className="eg-dot" />
                    {c.total_sources ?? c.sources?.length ?? 0} source
                    {(c.total_sources ?? c.sources?.length ?? 0) === 1 ? "" : "s"}
                  </span>
                </span>
                <span className="eg-claim-conf" aria-hidden="true">
                  <span className="eg-conf-track">
                    <span className="eg-conf-fill" style={{ width: `${Math.round((c.confidence ?? 0) * 100)}%` }} />
                  </span>
                </span>
              </button>
            );
          })}
        </div>

        {/* ── The chain ──────────────────────────────────────────────────── */}
        <div className="eg-detail" key={selected}>
          <Chain claim={active} index={selected} />
        </div>
      </div>
    </div>
  );
}

// ── The chain for one claim ──────────────────────────────────────────────────

function Chain({ claim, index }: { claim: ClaimDetail; index: number }) {
  const v = verdictOf(claim);
  const Icon = v.icon;
  const sources = claim.sources ?? [];
  const confidence = Math.round((claim.confidence ?? 0) * 100);

  // Each link draws in after the one above it, so the eye follows the route
  // rather than arriving at five boxes.
  const [drawn, setDrawn] = useState(0);
  useEffect(() => {
    if (!motionOn()) { setDrawn(5); return; }
    setDrawn(0);
    const timers = [1, 2, 3, 4, 5].map((n) =>
      window.setTimeout(() => setDrawn(n), n * 110));
    return () => timers.forEach(window.clearTimeout);
  }, [index]);

  const link = (n: number) => ({ className: "eg-link", "data-in": drawn >= n });

  return (
    <>
      <div {...link(1)}>
        <span className="eg-link-rail"><span className="eg-link-node"><FileSearch size={13} /></span></span>
        <div className="eg-link-body">
          <div className="vf-label">The claim, as the deck states it</div>
          <p className="eg-claim-quote">&ldquo;{claim.claim}&rdquo;</p>
          {claim.claim_kind && (
            <div className="eg-note">
              Routed as <b>{claim.claim_kind}</b>
              {claim.routing_reason ? ` — ${claim.routing_reason}` : ""}
            </div>
          )}
        </div>
      </div>

      <div {...link(2)}>
        <span className="eg-link-rail"><span className="eg-link-node"><Database size={13} /></span></span>
        <div className="eg-link-body">
          <div className="vf-label">What the search returned</div>
          <p className="eg-body">
            {claim.key_evidence?.trim()
              || "Nothing specific enough to bear on the claim was returned."}
          </p>
          {typeof claim.full_pages_read === "number" && claim.full_pages_read > 0 && (
            <div className="eg-note">
              {claim.full_pages_read} page{claim.full_pages_read === 1 ? "" : "s"} read in full
              {claim.search_mode ? ` · ${claim.search_mode}` : ""}
            </div>
          )}
        </div>
      </div>

      <div {...link(3)}>
        <span className="eg-link-rail"><span className="eg-link-node"><ArrowUpRight size={13} /></span></span>
        <div className="eg-link-body">
          <div className="vf-label">
            {sources.length > 0 ? `Sources (${claim.total_sources ?? sources.length})` : "Sources"}
          </div>
          {sources.length > 0 ? (
            <ul className="eg-sources">
              {sources.slice(0, 6).map((url) => (
                <li key={url}>
                  <a href={url} target="_blank" rel="noopener noreferrer" data-cursor="Open">
                    {hostOf(url)}
                    <ArrowUpRight size={12} />
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="eg-body">
              No source was reachable for this claim. That is a statement about the
              search, not about the company.
            </p>
          )}
        </div>
      </div>

      <div {...link(4)}>
        <span className="eg-link-rail"><span className="eg-link-node"><Gavel size={13} /></span></span>
        <div className="eg-link-body">
          <div className="vf-label">Reasoning</div>
          <p className="eg-body">
            {claim.reasoning?.trim() || "No reasoning was recorded for this verdict."}
          </p>
        </div>
      </div>

      <div {...link(5)} data-last="true">
        <span className="eg-link-rail">
          <span className="eg-link-node" data-tone={v.tone}><Icon size={13} /></span>
        </span>
        <div className="eg-link-body">
          <div className="vf-label">Verdict</div>
          <div className="eg-verdict">
            <Badge tone={v.tone} dot>{v.label}</Badge>
            {claim.cached && (
              <Badge tone="neutral" size="sm" title="Reused from an earlier identical check, within seven days">
                Cached
              </Badge>
            )}
            <span className="eg-conf-value">
              <span className="vf-num">{confidence}%</span> confidence
            </span>
          </div>
          {claim.verdict === "NOT_ENOUGH_INFO" && (
            <div className="eg-note">
              {claim.claim_kind === "internal"
                ? "Private companies do not publish this, so no search can settle it. It is not counted against the company."
                : "Public sources had nothing specific enough to confirm or contradict this."}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

const EG_CSS = `
  .eg-root { width: 100%; }
  .eg-summary { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }

  .eg-grid { display: grid; grid-template-columns: minmax(0, 0.92fr) minmax(0, 1.08fr); gap: 20px; align-items: start; }
  @media (max-width: 900px) { .eg-grid { grid-template-columns: 1fr; } }

  .eg-list { display: grid; gap: 8px; }

  .eg-claim {
    display: grid; grid-template-columns: 26px minmax(0, 1fr) 46px;
    align-items: center; gap: 12px; width: 100%; text-align: left;
    padding: 13px 15px; font: inherit; cursor: pointer;
    background: var(--surface); border: 1px solid var(--line);
    border-radius: var(--r-md);
    transition: border-color var(--dur-fast) var(--ease-out),
                background var(--dur-fast) var(--ease-out),
                transform var(--dur-fast) var(--ease-out);
  }
  .eg-claim:hover { border-color: var(--line-strong); transform: translateX(2px); }
  .eg-claim[data-on="true"] { border-color: var(--accent); background: var(--accent-quiet); }
  .eg-claim[data-on="true"][data-tone="verified"] { border-color: var(--verified-line); background: var(--verified-quiet); }
  .eg-claim[data-on="true"][data-tone="critical"] { border-color: var(--critical-line); background: var(--critical-quiet); }

  .eg-claim-index { font-size: 12px; color: var(--text-faint); }
  .eg-claim-body { min-width: 0; }
  .eg-claim-text {
    display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
    font-size: var(--t-small); line-height: 1.5; color: var(--text);
  }
  .eg-claim-meta {
    display: flex; align-items: center; gap: 6px; margin-top: 6px;
    font-size: var(--t-micro); color: var(--text-3);
  }
  .eg-dot { width: 3px; height: 3px; border-radius: 50%; background: var(--text-faint); }

  .eg-conf-track { display: block; height: 3px; border-radius: 3px; background: var(--surface-3); overflow: hidden; }
  .eg-conf-fill { display: block; height: 100%; border-radius: 3px; background: var(--accent); }

  /* The chain. One rail, five stops. */
  .eg-detail {
    padding: 22px 24px; background: var(--surface);
    border: 1px solid var(--line); border-radius: var(--r-lg);
  }
  .eg-link {
    display: grid; grid-template-columns: 26px minmax(0, 1fr); gap: 14px;
    opacity: 0; transform: translateY(8px);
    transition: opacity var(--dur-base) var(--ease-out), transform var(--dur-base) var(--ease-out);
  }
  .eg-link[data-in="true"] { opacity: 1; transform: none; }
  .eg-link-rail { position: relative; display: flex; justify-content: center; }
  .eg-link:not([data-last="true"]) .eg-link-rail::after {
    content: ''; position: absolute; top: 26px; bottom: -14px; width: 1px;
    background: var(--line-strong);
  }
  .eg-link-node {
    display: grid; place-items: center; width: 26px; height: 26px; border-radius: 50%;
    background: var(--surface-2); border: 1px solid var(--line-strong); color: var(--text-3);
    flex-shrink: 0;
  }
  .eg-link-node[data-tone="verified"] { color: var(--verified); border-color: var(--verified-line); background: var(--verified-quiet); }
  .eg-link-node[data-tone="critical"] { color: var(--critical); border-color: var(--critical-line); background: var(--critical-quiet); }
  .eg-link-body { padding-bottom: 20px; min-width: 0; }
  .eg-link[data-last="true"] .eg-link-body { padding-bottom: 0; }

  .eg-claim-quote {
    margin: 8px 0 0; font-family: var(--font-display); font-size: 19px;
    line-height: 1.32; letter-spacing: -0.01em; color: var(--text);
  }
  .eg-body { margin: 8px 0 0; font-size: var(--t-small); line-height: 1.68; color: var(--text-2); }
  .eg-note { margin-top: 8px; font-size: var(--t-micro); line-height: 1.55; color: var(--text-3); }

  .eg-sources { list-style: none; margin: 10px 0 0; padding: 0; display: flex; flex-wrap: wrap; gap: 7px; }
  .eg-sources a {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 5px 11px; border-radius: var(--r-pill);
    background: var(--surface-2); border: 1px solid var(--line);
    font-size: var(--t-micro); color: var(--text-2); text-decoration: none;
    transition: color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
  }
  .eg-sources a:hover { color: var(--accent); border-color: var(--accent-line); }

  .eg-verdict { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px; }
  .eg-conf-value { font-size: var(--t-small); color: var(--text-3); }

  .eg-empty {
    display: flex; gap: 14px; align-items: flex-start;
    padding: 20px 22px; border-radius: var(--r-lg);
    background: var(--surface); border: 1px solid var(--line);
  }

  :root[data-motion="off"] .eg-link { opacity: 1; transform: none; transition: none; }:root[data-motion="off"] .eg-claim:hover { transform: none; }
  
`;
