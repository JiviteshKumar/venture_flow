import { NavLink, useNavigate } from "react-router-dom";
import { Upload, LayoutDashboard, BarChart3, TrendingUp, Settings, Bell, Zap, Clock, ChevronRight, Star, Activity } from "lucide-react";
import { useApp } from "../../context/AppContext";
import { motion } from "framer-motion";

const Sidebar = () => {
  const navigate = useNavigate();
  const { report, status, currentStage, progressPct, companyName, reset } = useApp();

  const isAnalyzing = status === "uploading" || status === "analyzing";
  const isDone = status === "done" && report !== null;

  const navItems = [
    { name: "Upload Deck", path: "/upload", icon: Upload },
    { name: "Dashboard",   path: "/",       icon: LayoutDashboard },
    { name: "Analysis",    path: "/analysis", icon: BarChart3 },
  ];

  // Derive active deck display values from real report
  const deckName    = report?.company || companyName || null;
  const deckScore   = report ? Math.round(report.final_score) : null;
  const deckRisk    = report?.risk_level || null;
  const deckRec     = report?.recommendation || null;
  const scoreColor  = deckScore
    ? (deckScore >= 75 ? "#0EA66A" : deckScore >= 50 ? "#1D6FE8" : "#D93025")
    : "#1D6FE8";
  const riskColor   = deckRisk === "HIGH" ? "#D93025" : deckRisk === "MEDIUM" ? "#C47A0A" : "#0EA66A";
  const initials    = deckName
    ? deckName.split(" ").map((w: string) => w[0]).join("").slice(0, 2).toUpperCase()
    : "—";

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=IBM+Plex+Mono:wght@300;400;500;600&family=Figtree:wght@300;400;500;600;700&display=swap');

        :root {
          --sb-bg: #FFFFFF;
          --sb-border: rgba(15,23,42,0.08);
          --sb-border-strong: rgba(15,23,42,0.13);
          --sb-surface: #F7F8FA;
          --sb-text: #0B1120;
          --sb-muted: #94A3B8;
          --sb-secondary: #4A5568;
          --sb-blue: #1D6FE8;
          --sb-green: #0EA66A;
          --sb-amber: #C47A0A;
          --sb-red: #D93025;
          --sb-shadow: 0 1px 3px rgba(15,23,42,0.06), 0 4px 12px rgba(15,23,42,0.04);
        }

        .sb-root {
          width: 252px; min-width: 252px;
          background: var(--sb-bg);
          border-right: 1px solid var(--sb-border);
          display: flex; flex-direction: column;
          font-family: 'Figtree', sans-serif;
          height: 100vh; overflow: hidden;
          position: relative;
        }

        .sb-root::before {
          content: '';
          position: absolute;
          top: 0; left: 0; right: 0;
          height: 2px;
          background: linear-gradient(90deg, var(--sb-blue), var(--sb-green), var(--sb-amber));
          z-index: 10;
        }

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
        .sb-logo-tagline { font-family: 'IBM Plex Mono', monospace; font-size: 9px; color: var(--sb-muted); letter-spacing: 0.06em; margin-top: 1px; }

        .sb-version-chip {
          font-family: 'IBM Plex Mono', monospace; font-size: 8.5px;
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
          font-family: 'IBM Plex Mono', monospace; font-size: 8.5px;
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
          font-family: 'IBM Plex Mono', monospace; font-size: 9px;
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

        .sb-stat-label { font-family: 'IBM Plex Mono', monospace; font-size: 8.5px; color: var(--sb-muted); letter-spacing: 0.08em; text-transform: uppercase; margin-bottom: 5px; }
        .sb-stat-value { font-family: 'DM Serif Display', serif; font-size: 18px; color: var(--sb-text); line-height: 1; letter-spacing: -0.01em; }
        .sb-stat-sub { font-family: 'IBM Plex Mono', monospace; font-size: 8.5px; color: var(--sb-muted); margin-top: 2px; }

        .sb-section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }

        .sb-section-title { font-family: 'IBM Plex Mono', monospace; font-size: 9px; color: var(--sb-muted); letter-spacing: 0.14em; text-transform: uppercase; }

        .sb-see-all { font-family: 'IBM Plex Mono', monospace; font-size: 9px; color: var(--sb-blue); cursor: pointer; transition: opacity 0.14s ease; background: none; border: none; padding: 0; }
        .sb-see-all:hover { opacity: 0.7; }

        .sb-active-card {
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
          font-family: 'IBM Plex Mono', monospace; font-size: 8.5px;
          letter-spacing: 0.12em; text-transform: uppercase;
          color: var(--sb-muted); margin-bottom: 9px;
          display: flex; align-items: center; gap: 5px;
        }

        .sb-active-label-dot { width: 5px; height: 5px; border-radius: 50%; background: var(--sb-green); animation: sb-pulse 2s ease-in-out infinite; }

        .sb-active-deck-name { font-size: 13.5px; font-weight: 700; color: var(--sb-text); letter-spacing: -0.2px; margin-bottom: 2px; }
        .sb-active-deck-meta { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: var(--sb-muted); margin-bottom: 11px; }

        .sb-active-score-row { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }

        .sb-score-chip { font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600; padding: 3px 9px; border-radius: 20px; }

        .sb-risk-chip { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; padding: 3px 9px; border-radius: 20px; }

        .sb-active-progress { height: 3px; background: var(--sb-border); border-radius: 3px; overflow: hidden; }
        .sb-active-progress-fill { height: 100%; border-radius: 3px; }
        .sb-active-progress-label { font-family: 'IBM Plex Mono', monospace; font-size: 8.5px; color: var(--sb-muted); margin-top: 5px; text-align: right; }

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

        .sb-actions-row { display: flex; gap: 6px; margin-bottom: 12px; }

        .sb-action-btn {
          flex: 1; display: flex; align-items: center; justify-content: center;
          padding: 8px; border-radius: 8px; background: var(--sb-surface);
          border: 1px solid var(--sb-border); color: var(--sb-secondary);
          cursor: pointer; transition: all 0.12s ease; position: relative;
        }

        .sb-action-btn:hover { background: #EBEBF0; color: var(--sb-text); border-color: var(--sb-border-strong); transform: translateY(-1px); }

        .sb-notif-badge { position: absolute; top: 4px; right: 4px; width: 6px; height: 6px; border-radius: 50%; background: var(--sb-red); border: 1.5px solid white; }

        .sb-user-row { display: flex; align-items: center; gap: 10px; padding: 8px 10px; border-radius: 9px; cursor: pointer; transition: background 0.12s ease; border: 1px solid transparent; }

        .sb-user-row:hover { background: var(--sb-surface); border-color: var(--sb-border); }

        .sb-user-avatar { width: 30px; height: 30px; border-radius: 8px; background: linear-gradient(135deg, rgba(29,111,232,0.15), rgba(14,166,106,0.15)); border: 1px solid var(--sb-border); display: flex; align-items: center; justify-content: center; font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600; color: var(--sb-blue); flex-shrink: 0; }

        .sb-user-name { font-size: 12.5px; font-weight: 600; color: var(--sb-text); letter-spacing: -0.1px; }
        .sb-user-role { font-family: 'IBM Plex Mono', monospace; font-size: 9px; color: var(--sb-muted); }
        .sb-user-caret { margin-left: auto; color: var(--sb-muted); }
      `}</style>

      <aside className="sb-root">
        {/* LOGO */}
        <div className="sb-logo-area">
          <div className="sb-logo-inner">
            <div className="sb-logo-icon">
              <Zap size={17} color="#fff" strokeWidth={2.2} fill="#fff" />
            </div>
            <div>
              <div className="sb-logo-name">VentureFlow</div>
              <div className="sb-logo-tagline">Investment AI</div>
            </div>
          </div>
          <span className="sb-version-chip">v2.1</span>
        </div>

        {/* AGENT STATUS */}
        <div className="sb-agents">
          <div className="sb-agent-pill sb-agent-bull">
            <div className="sb-agent-dot sb-agent-dot-bull" />
            BULL
          </div>
          <div className="sb-agent-pill sb-agent-bear">
            <div className="sb-agent-dot sb-agent-dot-bear" />
            BEAR
          </div>
          <div className="sb-agent-pill" style={{ flex: 1, background: "rgba(29,111,232,0.07)", color: "#1D6FE8", border: "1px solid rgba(29,111,232,0.18)", fontSize: "8.5px", fontFamily: "'IBM Plex Mono', monospace", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", gap: 4, padding: "5px 0", borderRadius: 7 }}>
            <div className="sb-agent-dot sb-agent-dot-live" />
            LIVE
          </div>
        </div>

        {/* NAV */}
        <div className="sb-nav-area">
          <div className="sb-nav-label">Menu</div>
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
                  {item.name}
                </NavLink>
              );
            })}
          </nav>
        </div>

        {/* SCROLLABLE MIDDLE */}
        <div className="sb-scroll-area">
          <div className="sb-section-divider" />

          {/* STATS */}
          <div className="sb-stats-row">
            <div className="sb-stat-card">
              <div className="sb-stat-label">Decks Today</div>
              <div className="sb-stat-value">{isDone ? "1" : "0"}</div>
              <div className="sb-stat-sub">{isDone ? "+1 today" : "Upload first"}</div>
            </div>
            <div className="sb-stat-card">
              <div className="sb-stat-label">Avg Score</div>
              <div className="sb-stat-value" style={{ color: isDone ? scoreColor : "#94A3B8" }}>
                {deckScore ?? "—"}
              </div>
              <div className="sb-stat-sub">out of 100</div>
            </div>
          </div>

          {/* ANALYZING STATE */}
          {isAnalyzing && (
            <div className="sb-analyzing-card">
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 8.5, color: "#1D6FE8", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 8, display: "flex", alignItems: "center", gap: 5 }}>
                <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}>
                  <Activity size={9} color="#1D6FE8" />
                </motion.div>
                Analyzing…
              </div>
              <div style={{ fontSize: 13, fontWeight: 600, color: "#0B1120", marginBottom: 3 }}>
                {companyName || "Processing deck"}
              </div>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9.5, color: "#94A3B8", marginBottom: 10 }}>
                {currentStage}
              </div>
              <div style={{ height: 3, background: "rgba(15,23,42,0.07)", borderRadius: 3, overflow: "hidden" }}>
                <motion.div
                  style={{ height: "100%", background: "linear-gradient(90deg, #1D6FE8, #60A5FA)", borderRadius: 3 }}
                  animate={{ width: `${progressPct}%` }}
                  transition={{ duration: 0.5 }}
                />
              </div>
              <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 8.5, color: "#94A3B8", marginTop: 5, textAlign: "right" }}>
                {progressPct}%
              </div>
            </div>
          )}

          {/* ACTIVE DECK CARD */}
          {isDone && deckName && (
            <div className="sb-active-card" onClick={() => navigate("/analysis")}>
              <div className="sb-active-label">
                <div className="sb-active-label-dot" />
                Active Deck
              </div>
              <div className="sb-active-deck-name">{deckName}</div>
              <div className="sb-active-deck-meta">{deckRec || "Analyzed"}</div>
              <div className="sb-active-score-row">
                <span className="sb-score-chip" style={{ background: `${scoreColor}12`, color: scoreColor, border: `1px solid ${scoreColor}28` }}>
                  {deckScore} / 100
                </span>
                {deckRisk && (
                  <span className="sb-risk-chip" style={{ color: riskColor, background: `${riskColor}10`, border: `1px solid ${riskColor}25` }}>
                    {deckRisk} Risk
                  </span>
                )}
              </div>
              <div className="sb-active-progress">
                <div className="sb-active-progress-fill" style={{ width: `${deckScore}%`, background: `linear-gradient(90deg, ${scoreColor}, ${scoreColor}99)` }} />
              </div>
              <div className="sb-active-progress-label">{deckScore}% investment score</div>
            </div>
          )}

          {/* PLACEHOLDER when idle */}
          {!isAnalyzing && !isDone && (
            <div className="sb-active-card" onClick={() => navigate("/upload")} style={{ cursor: "pointer", borderStyle: "dashed", background: "transparent" }}>
              <div style={{ textAlign: "center", padding: "8px 0" }}>
                <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9.5, color: "#94A3B8", lineHeight: 1.6 }}>
                  No active deck<br />
                  <span style={{ color: "#1D6FE8" }}>Upload one to get started →</span>
                </div>
              </div>
            </div>
          )}

          {/* RECENT DECKS */}
          {isDone && report && (
            <>
              <div className="sb-section-divider" />
              <div className="sb-section-header">
                <div className="sb-section-title">
                  <Clock size={9} style={{ display: "inline", marginRight: 4, verticalAlign: "middle" }} />
                  Recent Decks
                </div>
              </div>
              <div style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "9px 10px", borderRadius: 9, cursor: "pointer",
                background: "rgba(29,111,232,0.04)", border: "1px solid rgba(29,111,232,0.15)",
                marginBottom: 2,
              }} onClick={() => navigate("/analysis")}>
                <div style={{
                  width: 32, height: 32, borderRadius: 8, background: "#F7F8FA",
                  border: "1px solid rgba(15,23,42,0.08)", display: "flex",
                  alignItems: "center", justifyContent: "center",
                  fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, fontWeight: 600, color: "#4A5568",
                }}>{initials}</div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 12.5, fontWeight: 600, color: "#0B1120", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {deckName}
                  </div>
                  <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9, color: "#94A3B8" }}>
                    Today
                  </div>
                </div>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 11, fontWeight: 600, color: scoreColor }}>
                  {deckScore}
                </span>
              </div>
            </>
          )}

          <div className="sb-section-divider" />

          <div className="sb-section-header">
            <div className="sb-section-title">
              <Star size={9} style={{ display: "inline", marginRight: 4, verticalAlign: "middle" }} />
              Starred
            </div>
          </div>
          <div style={{ padding: "8px 10px", borderRadius: 9, background: "rgba(15,23,42,0.02)", border: "1px dashed rgba(15,23,42,0.1)", textAlign: "center" }}>
            <div style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9.5, color: "#94A3B8", lineHeight: 1.5 }}>
              Star a deck from the<br />Dashboard to pin it here
            </div>
          </div>
        </div>

        {/* BOTTOM */}
        <div className="sb-bottom-area">
          <div className="sb-actions-row">
            <button className="sb-action-btn" title="Notifications">
              <Bell size={13} strokeWidth={1.75} />
              <div className="sb-notif-badge" />
            </button>
            <button className="sb-action-btn" title="Portfolio trends">
              <TrendingUp size={13} strokeWidth={1.75} />
            </button>
            <button className="sb-action-btn" title="Settings" onClick={reset}>
              <Settings size={13} strokeWidth={1.75} />
            </button>
          </div>
          <div className="sb-user-row">
            <div className="sb-user-avatar">JD</div>
            <div>
              <div className="sb-user-name">James Dolan</div>
              <div className="sb-user-role">Partner, VC</div>
            </div>
            <ChevronRight size={13} className="sb-user-caret" strokeWidth={1.5} />
          </div>
        </div>
      </aside>
    </>
  );
};

export default Sidebar;
