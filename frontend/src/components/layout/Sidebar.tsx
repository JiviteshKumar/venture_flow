import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import {
  Upload, LayoutDashboard, BarChart3, Zap, Activity, Menu, X, LogOut,
} from "lucide-react";
import { useApp } from "../../context/AppContext";
import { formatElapsed, useElapsedSeconds } from "../../hooks/useElapsed";
import { useAuth } from "../../context/AuthContext";
import { useLocalStorage } from "../../hooks/useLocalStorage";
import { motion } from "framer-motion";
import PrefsControl from "../ui/PrefsControl";

const initialsOf = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();

const Sidebar = () => {
  const navigate = useNavigate();
  const { report, status, currentStage, progressPct, companyName, reset, startedAt } = useApp();

  // A label this browser remembers, not an identity. See the user row below.
  const [displayName, setDisplayName] = useLocalStorage<string>("vf.displayName", "");
  const { user, accountsEnabled, signOut } = useAuth();
  const handleSetName = () => {
    const next = window.prompt(
      "Display name shown in the sidebar.\n\nThis is a local label only — VentureFlow has no accounts and this identifies nobody.",
      displayName,
    );
    if (next !== null) setDisplayName(next.trim().slice(0, 40));
  };

  // Off-canvas drawer state for narrow viewports. Desktop ignores this.
  const [drawerOpen, setDrawerOpen] = useState(false);

  const isAnalyzing = status === "uploading" || status === "analyzing";
  const elapsed = useElapsedSeconds(isAnalyzing ? startedAt : null);
  const isDone = status === "done" && report !== null;

  const navItems = [
    { name: "Upload Deck", path: "/upload", icon: Upload },
    { name: "Dashboard",   path: "/",       icon: LayoutDashboard },
    { name: "Analysis",    path: "/analysis", icon: BarChart3 },
  ];

  // Derive active deck display values from real report
  const deckName    = report?.company || companyName || null;
  const deckScore   = report ? Math.round(report.final_score) : null;
  const deckRec     = report?.recommendation || null;
  // Same thresholds as `scoreTone` in components/ui/primitives.tsx. The
  // sidebar used to call 50-74 blue while every other surface called it amber,
  // so one score wore two colours depending on which panel you looked at.
  const scoreColor  = deckScore !== null
    ? (deckScore >= 70 ? "var(--positive)" : deckScore >= 45 ? "var(--caution)" : "var(--negative)")
    : "var(--accent)";

  return (
    <>
      <style>{`

        /* Colour tokens live in src/styles/tailwind.css. This component used
           to redeclare all twelve of them here, which meant two definitions
           of the same design system racing on load order. */

        .sb-root {
          width: 252px; min-width: 252px;
          background: var(--sb-bg);
          border-right: 1px solid var(--sb-border);
          display: flex; flex-direction: column;
          font-family: var(--font-sans);
          height: 100vh; overflow: hidden;
          position: relative;
        }

        /* A 2px blue-green-amber bar ran across the top of the sidebar:
           three accent colours in a two-pixel strip, carrying no meaning, on a
           product whose primary action is a fourth colour. The app has one
           accent, and it is the button. */

        .sb-logo-area {
          padding: 22px 18px 18px;
          border-bottom: 1px solid var(--sb-border);
          display: flex; align-items: center;
          justify-content: space-between;
          flex-shrink: 0;
        }

        .sb-logo-inner { display: flex; align-items: center; gap: 11px; }

        .sb-logo-icon {
          width: 36px; height: 36px;
          background: var(--sb-blue);
          border-radius: 10px;
          display: flex; align-items: center; justify-content: center;
          box-shadow: 0 2px 8px rgba(29,111,232,0.3), 0 0 0 1px rgba(29,111,232,0.15);
          flex-shrink: 0;
        }

        .sb-logo-name { font-size: 15px; font-weight: 700; color: var(--sb-text); letter-spacing: -0.3px; line-height: 1.1; }
        .sb-logo-tagline { font-family: var(--font-mono); font-size: 9px; color: var(--sb-muted); letter-spacing: 0.06em; margin-top: 1px; }

        .sb-version-chip {
          font-family: var(--font-mono); font-size: 8.5px;
          color: var(--sb-blue); background: rgba(29,111,232,0.07);
          border: 1px solid rgba(29,111,232,0.18);
          padding: 2px 7px; border-radius: 20px; letter-spacing: 0.04em;
        }

        .sb-agents {
          padding: 10px 16px; border-bottom: 1px solid var(--sb-border);
          display: flex; gap: 6px; flex-shrink: 0;
        }

        .sb-agent-pill {
          flex: 1; display: flex; align-items: center; justify-content: center;
          gap: 4px; padding: 5px 0; border-radius: 7px;
          font-family: var(--font-mono); font-size: 8.5px;
          font-weight: 600; letter-spacing: 0.04em;
          cursor: default; transition: transform 0.15s ease;
        }

        .sb-agent-pill:hover { transform: translateY(-1px); }

        .sb-agent-dot { width: 5px; height: 5px; border-radius: 50%; }

        .sb-agent-bull { background: rgba(14,166,106,0.08); color: #0EA66A; border: 1px solid rgba(14,166,106,0.2); }
        .sb-agent-bear { background: rgba(217,48,37,0.07); color: #D93025; border: 1px solid rgba(217,48,37,0.18); }
        .sb-agent-dot-bull { background: #0EA66A; animation: sb-pulse 2s ease-in-out infinite; }
        .sb-agent-dot-bear { background: #D93025; animation: sb-pulse 2.2s ease-in-out infinite 0.3s; }
        .sb-agent-dot-live { background: #1D6FE8; animation: sb-pulse 1.6s ease-in-out infinite 0.1s; }

        @keyframes sb-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }

        .sb-nav-area { padding: 14px 12px 10px; flex-shrink: 0; }

        .sb-nav-label {
          font-family: var(--font-mono); font-size: 9px;
          color: var(--sb-muted); letter-spacing: 0.14em;
          text-transform: uppercase; padding: 0 8px; margin-bottom: 5px;
        }

        .sb-link {
          display: flex; align-items: center; gap: 10px;
          padding: 9px 10px; border-radius: 9px;
          text-decoration: none; font-size: 13.5px; font-weight: 500;
          letter-spacing: -0.1px; transition: background 0.12s ease, color 0.12s ease;
          margin-bottom: 1px; color: var(--sb-secondary); position: relative;
        }

        .sb-link:hover { background: var(--sb-surface); color: var(--sb-text); }

        .sb-link-active { background: rgba(29,111,232,0.07) !important; color: var(--sb-blue) !important; }

        .sb-link-active::before {
          content: ''; position: absolute;
          left: 0; top: 50%; transform: translateY(-50%);
          width: 3px; height: 18px;
          background: var(--sb-blue); border-radius: 0 3px 3px 0;
        }

        .sb-link-label { display: inline; min-width: 0; }
        .sb-link-icon { display: flex; align-items: center; justify-content: center; flex-shrink: 0; opacity: 0.7; }
        .sb-link-active .sb-link-icon { opacity: 1; }

        .sb-scroll-area {
          flex: 1; overflow-y: auto; overflow-x: hidden;
          padding: 0 12px 12px;
          scrollbar-width: thin; scrollbar-color: rgba(15,23,42,0.1) transparent;
        }

        .sb-scroll-area::-webkit-scrollbar { width: 3px; }
        .sb-scroll-area::-webkit-scrollbar-thumb { background: rgba(15,23,42,0.1); border-radius: 2px; }

        .sb-section-divider { height: 1px; background: var(--sb-border); margin: 10px 0; }

        .sb-stats-row { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-bottom: 14px; }

        .sb-stat-card {
          background: var(--sb-surface); border: 1px solid var(--sb-border);
          border-radius: 9px; padding: 10px 12px; cursor: default;
          transition: border-color 0.15s ease, transform 0.15s ease;
        }

        .sb-stat-card:hover { border-color: var(--sb-border-strong); transform: translateY(-1px); }

        .sb-stat-label { font-family: var(--font-mono); font-size: 8.5px; color: var(--sb-muted); letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 5px; }
        .sb-stat-value { font-family: var(--font-display); font-size: 18px; color: var(--sb-text); line-height: 1; letter-spacing: -0.01em; }
        .sb-stat-sub { font-family: var(--font-mono); font-size: 8.5px; color: var(--sb-muted); margin-top: 2px; }

        .sb-section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }

        .sb-section-title { font-family: var(--font-mono); font-size: 9px; color: var(--sb-muted); letter-spacing: 0.14em; text-transform: uppercase; }

        .sb-see-all { font-family: var(--font-mono); font-size: 9px; color: var(--sb-blue); cursor: pointer; transition: opacity 0.14s ease; background: none; border: none; padding: 0; }
        .sb-see-all:hover { opacity: 0.7; }

        .sb-active-card {
          appearance: none; font: inherit; color: inherit;
          width: 100%; text-align: left; display: block;
          background: var(--sb-surface); border: 1px solid var(--sb-border);
          border-radius: 11px; padding: 14px; margin-bottom: 12px;
          position: relative; overflow: hidden; cursor: pointer;
          transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }

        .sb-active-card:hover { border-color: var(--sb-border-strong); box-shadow: 0 2px 8px rgba(15,23,42,0.06); }

        .sb-active-card::before {
          content: ''; position: absolute; top: 0; left: 0;
          width: 3px; height: 100%;
          background: var(--sb-green); border-radius: 0 2px 2px 0;
        }

        .sb-active-label {
          font-family: var(--font-sans); font-size: 11px; font-weight: 600;
          letter-spacing: 0.07em; text-transform: uppercase;
          color: var(--sb-muted); margin-bottom: 9px;
          display: flex; align-items: center; gap: 5px;
        }

        .sb-active-label-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--sb-green); animation: sb-pulse 2s ease-in-out infinite; }

        .sb-active-deck-name { font-size: 13.5px; font-weight: 700; color: var(--sb-text); letter-spacing: -0.2px; margin-bottom: 2px; }
        .sb-active-deck-meta { font-family: var(--font-sans); font-size: 12px; color: var(--sb-muted); margin-bottom: 11px; }

        .sb-active-score-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }

        .sb-score-chip { font-family: var(--font-mono); font-size: 10px; font-weight: 600; padding: 3px 9px; border-radius: 20px; }

        .sb-risk-chip { font-family: var(--font-mono); font-size: 9.5px; padding: 3px 9px; border-radius: 20px; }

        .sb-active-progress { height: 3px; background: var(--sb-border); border-radius: 3px; overflow: hidden; }
        .sb-active-progress-fill { height: 100%; border-radius: 3px; }
        .sb-active-progress-label { font-family: var(--font-mono); font-size: 8.5px; color: var(--sb-muted); margin-top: 5px; text-align: right; }

        /* ANALYZING STATE */
        .sb-analyzing-card {
          background: rgba(29,111,232,0.04); border: 1px solid rgba(29,111,232,0.18);
          border-radius: 11px; padding: 14px; margin-bottom: 12px;
          position: relative; overflow: hidden;
        }

        .sb-analyzing-card::before {
          content: ''; position: absolute; top: 0; left: 0;
          width: 3px; height: 100%;
          background: var(--sb-blue); border-radius: 0 2px 2px 0;
        }

        .sb-bottom-area { padding: 12px 16px 16px; border-top: 1px solid var(--sb-border); flex-shrink: 0; }

        .sb-clear-btn {
          display: flex; align-items: center; justify-content: center; gap: 7px;
          width: 100%; margin-bottom: 10px; padding: 8px 10px;
          font-family: var(--font-sans); font-size: 12.5px; font-weight: 500;
          color: var(--sb-muted); background: var(--sb-surface);
          border: 1px solid var(--sb-border); border-radius: 8px; cursor: pointer;
          transition: color var(--dur-fast) var(--ease-out),
                      border-color var(--dur-fast) var(--ease-out);
        }
        .sb-clear-btn:hover { color: var(--text-primary); border-color: var(--sb-border-strong); }

        .sb-actions-row { display: flex; gap: 6px; margin-bottom: 12px; }

        .sb-action-btn {
          flex: 1; display: flex; align-items: center; justify-content: center;
          padding: 8px; border-radius: 8px; background: var(--sb-surface);
          border: 1px solid var(--sb-border); color: var(--sb-secondary);
          cursor: pointer; transition: all 0.12s ease; position: relative;
        }

        .sb-action-btn:hover { background: #EBEBF0; color: var(--sb-text); border-color: var(--sb-border-strong); transform: translateY(-1px); }

        .sb-notif-badge { position: absolute; top: 4px; right: 4px; width: 6px; height: 6px; border-radius: 50%; background: var(--sb-red); border: 1.5px solid white; }

        .sb-prefs-row { display: flex; justify-content: center; padding: 2px 0 8px; }
        .sb-user-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 9px; cursor: pointer; transition: background 0.12s ease; border: 1px solid transparent; }

        .sb-user-row:hover { background: var(--sb-surface); border-color: var(--sb-border); }

        .sb-user-avatar { width: 30px; height: 30px; border-radius: 8px; background: linear-gradient(135deg, rgba(29,111,232,0.15), rgba(14,166,106,0.15)); border: 1px solid var(--sb-border); display: flex; align-items: center; justify-content: center; font-family: var(--font-mono); font-size: 10px; font-weight: 600; color: var(--sb-blue); flex-shrink: 0; }

        .sb-user-name { font-size: 12.5px; font-weight: 600; color: var(--sb-text); letter-spacing: -0.1px; }
        .sb-user-role { font-family: var(--font-sans); font-size: 11.5px; color: var(--sb-muted); }
        .sb-user-caret { margin-left: auto; color: var(--sb-muted); }

        /* ── Identity row ──────────────────────────────────────────────── */
        .sb-user-copy { min-width: 0; flex: 1; }
        .sb-user-setname {
          background: none; border: none; padding: 0; cursor: pointer;
          font-family: var(--font-sans); font-size: 12px; font-weight: 600;
          color: var(--sb-blue); text-align: left;
        }
        .sb-user-setname:hover { text-decoration: underline; }
        .sb-user-role { display: flex; align-items: center; gap: 6px; }
        .sb-demo-badge {
          font-family: var(--font-sans); font-size: 12px; font-weight: 600;
          letter-spacing: 0.08em; text-transform: uppercase;
          color: var(--sb-amber); background: rgba(196,122,10,0.10);
          border: 1px solid rgba(196,122,10,0.22);
          border-radius: 4px; padding: 1px 5px;
        }
        .sb-user-role-note {
          font-family: var(--font-sans); font-size: 11.5px; color: var(--text-muted);
        }
        .sb-user-caret-btn {
          background: none; border: none; padding: 4px; cursor: pointer;
          display: flex; align-items: center; color: var(--text-muted);
        }

        /* ── Responsive ────────────────────────────────────────────────────
           The sidebar was pinned to 252px at every width, so on a phone it
           consumed two thirds of the viewport and the content beside it was
           unusable. Two steps: an icon rail on tablets, and a real off-canvas
           drawer on phones. The drawer is rendered in the same DOM order and
           simply translated off-screen, so focus order and screen-reader
           order are unchanged.
           ──────────────────────────────────────────────────────────────── */
        .sb-drawer-toggle { display: none; }

        @media (max-width: 1024px) {
          .sb-root { width: 68px; min-width: 68px; }
          .sb-root .sb-link-label,
          .sb-root .sb-logo-name,
          .sb-root .sb-logo-tagline,
          .sb-root .sb-version-chip,
          .sb-root .sb-nav-label,
          .sb-root .sb-section-title,
          .sb-root .sb-section-header,
          .sb-root .sb-active-card,
          .sb-root .sb-analyzing-card,
          .sb-root .sb-user-copy,
          .sb-root .sb-user-caret-btn { display: none; }
          .sb-root .sb-link { justify-content: center; padding: 9px 0; }
          .sb-root .sb-logo-area { padding: 18px 0; justify-content: center; }
          .sb-root .sb-actions-row { flex-direction: column; gap: 6px; }
          .sb-root .sb-user-row { justify-content: center; }
          .sb-root .sb-scroll-area { padding: 0 8px 12px; }
        }

        @media (max-width: 640px) {
          .sb-drawer-toggle {
            display: flex; align-items: center; justify-content: center;
            position: fixed; top: 12px; left: 12px; z-index: 60;
            width: 40px; height: 40px; border-radius: 10px;
            background: var(--surface); color: var(--sb-text);
            border: 1px solid var(--sb-border); box-shadow: var(--sb-shadow);
            cursor: pointer;
          }
          .sb-root {
            position: fixed; top: 0; left: 0; z-index: 55;
            width: 252px; min-width: 252px;
            transform: translateX(-100%);
            transition: transform 180ms ease;
            box-shadow: var(--shadow-lifted, 0 12px 40px rgba(15,23,42,0.18));
          }
          .sb-root[data-open="true"] { transform: translateX(0); }
          /* Inside the drawer the sidebar is full width again, so everything
             the icon rail hid comes back. */
          .sb-root .sb-link-label,
          .sb-root .sb-logo-name,
          .sb-root .sb-logo-tagline,
          .sb-root .sb-version-chip,
          .sb-root .sb-nav-label,
          .sb-root .sb-section-title,
          .sb-root .sb-section-header,
          .sb-root .sb-active-card,
          .sb-root .sb-analyzing-card,
          .sb-root .sb-user-copy,
          .sb-root .sb-user-caret-btn { display: revert; }
          .sb-root .sb-link { justify-content: flex-start; padding: 9px 10px; }
          .sb-root .sb-logo-area { padding: 22px 18px 18px; justify-content: space-between; }
          .sb-root .sb-actions-row { flex-direction: row; }
          .sb-root .sb-user-row { justify-content: flex-start; }
          .sb-scrim {
            position: fixed; inset: 0; z-index: 50;
            background: rgba(11,17,32,0.45);
          }
        }

        :root[data-motion="off"] .sb-root { transition: none; }
        
      `}</style>

      <button
        type="button"
        className="sb-drawer-toggle"
        aria-label={drawerOpen ? "Close navigation menu" : "Open navigation menu"}
        aria-expanded={drawerOpen}
        aria-controls="vf-sidebar"
        onClick={() => setDrawerOpen((o) => !o)}
      >
        {drawerOpen ? <X size={18} strokeWidth={1.9} /> : <Menu size={18} strokeWidth={1.9} />}
      </button>

      {drawerOpen && (
        <div
          className="sb-scrim"
          role="button"
          tabIndex={0}
          aria-label="Close navigation menu"
          onClick={() => setDrawerOpen(false)}
          onKeyDown={(e) => {
            if (e.key === "Escape" || e.key === "Enter" || e.key === " ") setDrawerOpen(false);
          }}
        />
      )}

      <aside
        id="vf-sidebar"
        className="sb-root"
        data-open={drawerOpen}
        aria-label="Primary navigation"
      >
        {/* LOGO */}
        <div className="sb-logo-area">
          <div className="sb-logo-inner">
            <div className="sb-logo-icon">
              <Zap size={17} color="#fff" strokeWidth={2.2} fill="#fff" />
            </div>
            <div className="sb-logo-name">VentureFlow</div>
          </div>
        </div>

        {/* The BULL / BEAR / LIVE pills stood here.
            Three permanently-lit, permanently-pulsing chips that showed the
            same state whether an analysis was running, finished or had never
            started. They conveyed no information and animated forever at the
            top of every screen, which is the worst combination available: they
            drew the eye repeatedly and never rewarded it. "LIVE" in particular
            asserted something about the system that nothing checked.
            The bull and bear agents' actual output has a home -- the Summary
            tab, where their findings are, with evidence attached. */}

        {/* NAV */}
        <div className="sb-nav-area">
          {/* A "MENU" label above three links: the links are self-evidently
              the menu, and it cost a line of uppercase type on every screen. */}
          <nav>
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <NavLink
                  key={item.name}
                  to={item.path}
                  end={item.path === "/"}
                  className={({ isActive }) => `sb-link${isActive ? " sb-link-active" : ""}`}
                >
                  <span className="sb-link-icon">
                    <Icon size={15} strokeWidth={1.75} />
                  </span>
                  <span className="sb-link-label">{item.name}</span>
                </NavLink>
              );
            })}
          </nav>
        </div>

        {/* SCROLLABLE MIDDLE */}
        <div className="sb-scroll-area">
          <div className="sb-section-divider" />

          {/* "Decks Today" and "Avg Score" stood here, and neither was what
              its label said. Decks Today rendered `isDone ? "1" : "0"` -- not a
              count of anything, just whether a report happened to be loaded in
              this browser tab. Avg Score showed the current deck's score under
              the word "average", which is an average of one.
              Both are removed rather than repaired: the active-deck card below
              already carries the score of the deck actually in hand, and a
              real per-user count needs a query nobody has written. A number
              that is wrong is worse than an empty space. */}

          {/* ANALYZING STATE */}
          {isAnalyzing && (
            <div className="sb-analyzing-card">
              <div className="vf-label" style={{ color: "var(--accent)", marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
                <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }} style={{ display: "flex" }}>
                  <Activity size={11} color="var(--accent)" />
                </motion.div>
                Analyzing…
              </div>
              <div style={{ fontSize: 13.5, fontWeight: 600, color: "var(--text-primary)", marginBottom: 4 }}>
                {companyName || "Your deck"}
              </div>
              <div style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 10, lineHeight: 1.5 }}>
                {currentStage}
                <br />
                <span className="vf-num">{formatElapsed(elapsed)}</span> elapsed
              </div>
              <div style={{ height: 3, background: "rgba(15,23,42,0.07)", borderRadius: 3, overflow: "hidden" }}>
                <motion.div
                  style={{ height: "100%", background: "var(--accent)", borderRadius: 3 }}
                  animate={{ width: `${progressPct}%` }}
                  transition={{ duration: 0.5 }}
                />
              </div>
              <div className="vf-num" style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6, textAlign: "right" }}>
                {progressPct}%
              </div>
            </div>
          )}

          {/* ACTIVE DECK CARD */}
          {isDone && deckName && (
            <button type="button" className="sb-active-card" onClick={() => navigate("/analysis")} aria-label={`Open analysis for ${deckName}`}>
              {/* This card used to state one score four times: a "52 / 100"
                  chip, a bar filled to 52%, the line "52% investment score",
                  and a risk chip repeating the report header -- all beside a
                  Recent Decks entry for the same deck, showing 52 again. It is
                  a door to the report, so it carries only enough to say which
                  report is behind it. */}
              <div className="sb-active-label">Open report</div>
              <div className="sb-active-deck-name">{deckName}</div>
              <div className="sb-active-score-row" style={{ marginBottom: 0 }}>
                <span className="sb-active-deck-meta" style={{ marginBottom: 0 }}>{deckRec || "Analysed"}</span>
                <span className="sb-score-chip" style={{ color: scoreColor, background: "var(--surface-2)", border: "1px solid var(--border)" }}>
                  {deckScore}
                </span>
              </div>
            </button>
          )}

          {/* PLACEHOLDER when idle */}
          {!isAnalyzing && !isDone && (
            <button type="button" className="sb-active-card" onClick={() => navigate("/upload")} aria-label="Upload a deck to get started" style={{ cursor: "pointer", borderStyle: "dashed", background: "transparent", width: "100%", textAlign: "inherit" }}>
              <div style={{ textAlign: "center", padding: "8px 0" }}>
                <div style={{ fontSize: 12.5, color: "var(--text-muted)", lineHeight: 1.6 }}>
                  No deck open<br />
                  <span style={{ color: "var(--accent)", fontWeight: 600 }}>Upload one to start →</span>
                </div>
              </div>
            </button>
          )}

          {/* A "Recent Decks" list stood here. It had exactly one entry --
              the deck already named in the card above it -- repeating that
              deck's name, its score, and the word "Today". A list of one, of
              the thing directly above it. The dashboard is the list of past
              analyses, and it is one click away. */}

          {/* A "Starred" section with a dashed empty box reading "Star a deck
              from the Dashboard to pin it here" stood here. Nothing in this
              application can star a deck -- a search of the whole frontend
              finds no star action, no starred state and no storage for one. It
              was an empty box advertising a feature that does not exist, on
              every screen, forever. */}

        </div>

        {/* BOTTOM */}
        <div className="sb-bottom-area">
          {/* Three icon buttons stood here. Notifications opened nothing and
              carried a red unread dot that was permanently lit; Portfolio
              trends opened nothing at all; and the third, drawn as a settings
              gear, silently discarded the open analysis. A control that lies
              about what it does is worse than no control, and two that do
              nothing teach people not to trust the rest.

              What is left is the one action that existed: clearing the deck in
              hand, labelled as that, and only shown when there is one. */}
          {(isDone || isAnalyzing) && (
            <button
              type="button"
              className="sb-clear-btn"
              onClick={reset}
              title="Clear the deck currently open in this browser"
            >
              <X size={13} strokeWidth={1.9} />
              Clear current deck
            </button>
          )}
          {/* Real identity, at last.
              This row used to read "James Dolan / Partner, VC" -- a fictional
              person presented as the signed-in user, on a tool whose entire
              value proposition is not making things up. It was then replaced by
              a Demo Mode badge and a localStorage display name that identified
              nobody and gated nothing, with a note that real auth was deferred.
              It is no longer deferred: this is the account, and signing out
              ends the session server-side. */}
          <div className="sb-prefs-row">
            <PrefsControl compact />
          </div>
          <div className="sb-user-row">
            <div className="sb-user-avatar" aria-hidden="true">
              {user ? initialsOf(user.display_name || user.email) : (displayName ? initialsOf(displayName) : "?")}
            </div>
            <div className="sb-user-copy">
              {user ? (
                <>
                  <div className="sb-user-name" title={user.email}>
                    {user.display_name || user.email.split("@")[0]}
                  </div>
                  <div className="sb-user-role">
                    <span className="sb-user-role-note" title={user.email}>{user.email}</span>
                  </div>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    className="sb-user-setname"
                    onClick={() => navigate("/signin")}
                  >
                    Sign in
                  </button>
                  <div className="sb-user-role">
                    <span className="sb-user-role-note">
                      {accountsEnabled ? "not signed in" : "accounts unavailable"}
                    </span>
                  </div>
                </>
              )}
            </div>
            {user && (
              <button
                type="button"
                className="sb-user-caret-btn"
                onClick={async () => { await signOut(); navigate("/signin"); }}
                aria-label={`Sign out of ${user.email}`}
                title="Sign out"
              >
                <LogOut size={13} strokeWidth={1.6} />
              </button>
            )}
          </div>
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
