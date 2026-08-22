import { useState, useRef, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useNavigate } from "react-router-dom";
import {
  Upload, FileText, X, Zap, BarChart2, Users, Shield,
  TrendingUp, CheckCircle, ArrowRight, Clock, TrendingDown,
  Search, Globe, AlertTriangle, Database, ChevronRight,
  Activity, Eye, Layers, Target
} from "lucide-react";
import { useApp } from "../context/AppContext";

// ─── DATA ────────────────────────────────────────────────────────────────────

const analysisFeatures = [
  {
    icon: TrendingUp, label: "Market Validation",
    desc: "TAM/SAM/SOM sizing & growth signals",
    color: "#0EA66A", bg: "rgba(14,166,106,0.08)", border: "rgba(14,166,106,0.18)",
  },
  {
    icon: Users, label: "Founder Analysis",
    desc: "Team capability & experience mapping",
    color: "#1D6FE8", bg: "rgba(29,111,232,0.08)", border: "rgba(29,111,232,0.18)",
  },
  {
    icon: BarChart2, label: "Competitive Intel",
    desc: "Landscape threats & differentiation",
    color: "#C47A0A", bg: "rgba(196,122,10,0.08)", border: "rgba(196,122,10,0.18)",
  },
  {
    icon: Shield, label: "Risk Assessment",
    desc: "Multi-factor risk scoring 0–100",
    color: "#D93025", bg: "rgba(217,48,37,0.07)", border: "rgba(217,48,37,0.16)",
  },
];

const analysisSteps = [
  { label: "Parsing document structure", pct: 16, icon: Layers },
  { label: "Extracting market signals", pct: 32, icon: Globe },
  { label: "Running Bull/Bear agents", pct: 50, icon: Activity },
  { label: "Fact-checking claims", pct: 65, icon: Search },
  { label: "Evaluating team profile", pct: 78, icon: Users },
  { label: "Running risk models", pct: 90, icon: AlertTriangle },
  { label: "Generating report", pct: 100, icon: Database },
];

const howItWorksSteps = [
  {
    number: "01", icon: Upload, title: "Upload Deck",
    desc: "Drop your pitch deck in PDF. Our parser extracts text, charts, tables, and embedded data.",
    color: "#1D6FE8", bg: "rgba(29,111,232,0.07)",
  },
  {
    number: "02", icon: Activity, title: "Dual-Agent Scan",
    desc: "Bull & Bear agents independently stress-test every claim — market size, revenue projections, competitive moats.",
    color: "#0EA66A", bg: "rgba(14,166,106,0.07)",
  },
  {
    number: "03", icon: Globe, title: "Live Fact-Check",
    desc: "Cross-referenced against real-time databases: Crunchbase, PitchBook signals, SEC filings, and news.",
    color: "#C47A0A", bg: "rgba(196,122,10,0.07)",
  },
  {
    number: "04", icon: Target, title: "VC-Grade Report",
    desc: "Structured memo with conviction score, red flags, comps, and suggested due diligence questions.",
    color: "#9B59B6", bg: "rgba(155,89,182,0.07)",
  },
];

const miniPreviewCards = [
  {
    label: "Bull Case", icon: TrendingUp, color: "#0EA66A",
    bg: "rgba(14,166,106,0.06)", border: "rgba(14,166,106,0.18)",
    tag: "BULL", tagBg: "rgba(14,166,106,0.12)", tagColor: "#0EA66A",
    snippet: "Claims verified. Market signals strong. Proprietary data moat confirmed.",
    score: 74,
  },
  {
    label: "Bear Case", icon: TrendingDown, color: "#D93025",
    bg: "rgba(217,48,37,0.05)", border: "rgba(217,48,37,0.16)",
    tag: "BEAR", tagBg: "rgba(217,48,37,0.1)", tagColor: "#D93025",
    snippet: "Risk signals detected. Burn rate and concentration risks flagged.",
    score: 38,
  },
  {
    label: "Fact Check", icon: Search, color: "#1D6FE8",
    bg: "rgba(29,111,232,0.05)", border: "rgba(29,111,232,0.16)",
    tag: "VERIFIED", tagBg: "rgba(29,111,232,0.1)", tagColor: "#1D6FE8",
    snippet: "Web-verified across 15+ sources per claim. Groq AI cross-checked.",
    score: 86,
  },
];

// ─── SVG ILLUSTRATION ─────────────────────────────────────────────────────────

const DeckIllustration = () => (
  <svg width="100%" viewBox="0 0 320 190" fill="none" xmlns="http://www.w3.org/2000/svg"
    style={{ display: "block", maxWidth: 320, margin: "0 auto" }}>
    <ellipse cx="160" cy="140" rx="120" ry="30" fill="rgba(29,111,232,0.06)" />
    <rect x="56" y="34" width="208" height="140" rx="10" fill="rgba(15,23,42,0.04)" />
    <g transform="rotate(-4 160 104)">
      <rect x="60" y="32" width="200" height="134" rx="9" fill="#F7F8FA" stroke="rgba(15,23,42,0.09)" strokeWidth="1" />
      <rect x="74" y="50" width="80" height="8" rx="3" fill="rgba(196,122,10,0.18)" />
      <rect x="74" y="66" width="120" height="5" rx="2.5" fill="rgba(15,23,42,0.07)" />
      <rect x="74" y="76" width="96" height="5" rx="2.5" fill="rgba(15,23,42,0.05)" />
    </g>
    <g transform="rotate(-1.5 160 104)">
      <rect x="62" y="28" width="196" height="130" rx="9" fill="#FFFFFF" stroke="rgba(15,23,42,0.1)" strokeWidth="1" />
      <rect x="76" y="46" width="70" height="9" rx="3" fill="rgba(29,111,232,0.2)" />
      <rect x="76" y="62" width="140" height="4" rx="2" fill="rgba(15,23,42,0.07)" />
      <rect x="76" y="72" width="112" height="4" rx="2" fill="rgba(15,23,42,0.05)" />
      <rect x="76" y="88" width="14" height="32" rx="2" fill="rgba(14,166,106,0.5)" />
      <rect x="94" y="100" width="14" height="20" rx="2" fill="rgba(14,166,106,0.35)" />
      <rect x="112" y="96" width="14" height="24" rx="2" fill="rgba(14,166,106,0.45)" />
      <rect x="130" y="84" width="14" height="36" rx="2" fill="rgba(14,166,106,0.6)" />
      <rect x="148" y="78" width="14" height="42" rx="2" fill="rgba(14,166,106,0.75)" />
    </g>
    <rect x="58" y="22" width="204" height="134" rx="10" fill="#FFFFFF" stroke="rgba(15,23,42,0.12)" strokeWidth="1.2" />
    <rect x="58" y="22" width="204" height="28" rx="10" fill="rgba(29,111,232,0.05)" />
    <rect x="58" y="38" width="204" height="12" fill="rgba(29,111,232,0.05)" />
    <circle cx="74" cy="36" r="3.5" fill="rgba(217,48,37,0.4)" />
    <circle cx="85" cy="36" r="3.5" fill="rgba(196,122,10,0.4)" />
    <circle cx="96" cy="36" r="3.5" fill="rgba(14,166,106,0.4)" />
    <rect x="72" y="58" width="88" height="9" rx="3" fill="rgba(15,23,42,0.15)" />
    <rect x="72" y="72" width="56" height="5" rx="2" fill="rgba(15,23,42,0.07)" />
    <polyline points="72,130 95,118 118,122 140,108 162,98 185,90 208,76 232,68"
      stroke="#1D6FE8" strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    <polyline points="72,130 95,118 118,122 140,108 162,98 185,90 208,76 232,68 232,130"
      fill="rgba(29,111,232,0.06)" />
    <line x1="72" y1="130" x2="235" y2="130" stroke="rgba(15,23,42,0.08)" strokeWidth="1" />
    <line x1="72" y1="80" x2="72" y2="130" stroke="rgba(15,23,42,0.08)" strokeWidth="1" />
    <motion.rect x="58" y="22" width="204" height="3" rx="1.5" fill="rgba(29,111,232,0.35)"
      animate={{ y: [22, 150, 22] }} transition={{ repeat: Infinity, duration: 3.2, ease: "easeInOut" }} />
    <g transform="translate(218, 52)">
      <rect x="0" y="0" width="42" height="18" rx="5" fill="rgba(14,166,106,0.12)" stroke="rgba(14,166,106,0.3)" strokeWidth="1" />
      <text x="8" y="12.5" fontFamily="'IBM Plex Mono', monospace" fontSize="7.5" fontWeight="600" fill="#0EA66A">BULL</text>
      <circle cx="36" cy="9" r="3" fill="#0EA66A" opacity="0.8" />
    </g>
    <g transform="translate(218, 76)">
      <rect x="0" y="0" width="42" height="18" rx="5" fill="rgba(217,48,37,0.08)" stroke="rgba(217,48,37,0.25)" strokeWidth="1" />
      <text x="7" y="12.5" fontFamily="'IBM Plex Mono', monospace" fontSize="7.5" fontWeight="600" fill="#D93025">BEAR</text>
      <circle cx="36" cy="9" r="3" fill="#D93025" opacity="0.7" />
    </g>
    <motion.g animate={{ y: [0, -4, 0] }} transition={{ repeat: Infinity, duration: 2.8, ease: "easeInOut" }}>
      <g transform="translate(38, 78)">
        <rect x="0" y="0" width="18" height="18" rx="5" fill="rgba(29,111,232,0.12)" stroke="rgba(29,111,232,0.3)" strokeWidth="1" />
        <text x="4" y="13" fontSize="10">✓</text>
      </g>
    </motion.g>
  </svg>
);

// ─── MINI PREVIEW CARD ────────────────────────────────────────────────────────

const MiniPreviewCard = ({ card, delay }: { card: typeof miniPreviewCards[0]; delay: number }) => {
  const Icon = card.icon;
  return (
    <motion.div className="mpv-card" style={{ background: card.bg, border: `1px solid ${card.border}` }}
      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
      transition={{ delay, duration: 0.4, ease: [0.22, 1, 0.36, 1] }}>
      <div className="mpv-header">
        <div className="mpv-icon-wrap" style={{ background: `rgba(${card.color === "#0EA66A" ? "14,166,106" : card.color === "#D93025" ? "217,48,37" : "29,111,232"},0.12)` }}>
          <Icon size={12} color={card.color} strokeWidth={2} />
        </div>
        <span className="mpv-label">{card.label}</span>
        <span className="mpv-tag" style={{ background: card.tagBg, color: card.tagColor }}>{card.tag}</span>
      </div>
      <p className="mpv-snippet">{card.snippet}</p>
      <div className="mpv-score-row">
        <div className="mpv-score-track">
          <motion.div className="mpv-score-fill" style={{ background: card.color }}
            initial={{ width: 0 }} animate={{ width: `${card.score}%` }}
            transition={{ delay: delay + 0.3, duration: 0.8, ease: [0.22, 1, 0.36, 1] }} />
        </div>
        <span className="mpv-score-val" style={{ color: card.color }}>{card.score}</span>
      </div>
    </motion.div>
  );
};

// ─── MAIN COMPONENT ───────────────────────────────────────────────────────────

const UploadDeck = () => {
  const navigate = useNavigate();
  const { status, currentStage, progressPct, runAnalysis, report, error, reset } = useApp();

  const [fileName, setFileName] = useState<string | null>(null);
  const [fileSize, setFileSize] = useState<string | null>(null);
  const [fileObj, setFileObj] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [companyInput, setCompanyInput] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [activeDot, setActiveDot] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  // Derive UI state from global context
  const isAnalyzing = status === "uploading" || status === "analyzing";
  const showPreview = status === "done" && report !== null;

  // Map global progressPct to a step index for the animated steps list
  const analysisStep = Math.min(
    Math.floor((progressPct / 100) * analysisSteps.length),
    analysisSteps.length - 1
  );

  useEffect(() => {
    const t = setInterval(() => setActiveDot(d => (d + 1) % 3), 1200);
    return () => clearInterval(t);
  }, []);

  const formatSize = (bytes: number) => {
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const storeFile = (f: File) => {
    if (!f.name.toLowerCase().endsWith(".pdf")) {
      setFileError("Please upload a PDF deck. PowerPoint import is not enabled for this launch build.");
      return;
    }
    if (f.size > 10 * 1024 * 1024) {
      setFileError("File is too large. Maximum size is 10 MB.");
      return;
    }
    setFileError(null);
    setFileName(f.name);
    setFileSize(formatSize(f.size));
    setFileObj(f);
    // Auto-fill company name from filename if empty
    if (!companyInput) {
      setCompanyInput(f.name.replace(/\.pdf$/i, "").replace(/[-_]/g, " "));
    }
    if (status === "done") reset();
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files?.length) storeFile(e.target.files[0]);
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files?.length) storeFile(e.dataTransfer.files[0]);
  };

  const handleDragOver = (e: React.DragEvent) => { e.preventDefault(); setIsDragging(true); };
  const handleDragLeave = () => setIsDragging(false);

  const handleAnalyze = async () => {
    if (!fileObj || isAnalyzing) return;
    await runAnalysis(fileObj, companyInput || fileName || "Unknown Company");
  };

  const currentStep = analysisSteps[analysisStep];
  const StepIcon = currentStep?.icon ?? Layers;

  // Use live stage label from context when analyzing, fallback to step label
  const stageLabelDisplay = isAnalyzing
    ? (currentStage || currentStep?.label || "Processing…")
    : "";

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=IBM+Plex+Mono:wght@300;400;500;600&family=Figtree:wght@300;400;500;600;700&display=swap');

        :root {
          --bg: #F0F2F5;
          --surface: #FFFFFF;
          --surface-2: #F7F8FA;
          --border: rgba(15,23,42,0.08);
          --border-strong: rgba(15,23,42,0.14);
          --text-primary: #0B1120;
          --text-secondary: #4A5568;
          --text-muted: #94A3B8;
          --blue: #1D6FE8;
          --green: #0EA66A;
          --amber: #C47A0A;
          --red: #D93025;
          --purple: #9B59B6;
          --shadow-sm: 0 1px 2px rgba(15,23,42,0.04), 0 4px 12px rgba(15,23,42,0.05);
          --shadow-md: 0 4px 20px rgba(15,23,42,0.09), 0 1px 4px rgba(15,23,42,0.05);
          --shadow-lg: 0 16px 48px rgba(15,23,42,0.13), 0 4px 16px rgba(15,23,42,0.07);
          --radius: 14px;
        }

        * { box-sizing: border-box; }

        .up-root {
          font-family: 'Figtree', sans-serif;
          color: var(--text-primary);
          min-height: 100vh;
          background: var(--bg);
        }

        .up-header {
          padding: 22px 32px 20px;
          background: var(--surface);
          border-bottom: 1px solid var(--border);
          position: relative;
          overflow: hidden;
          display: flex;
          align-items: center;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 12px;
        }

        .up-header::before {
          content: '';
          position: absolute;
          top: 0; left: 0; right: 0;
          height: 2px;
          background: linear-gradient(90deg, var(--blue), var(--green), var(--amber), var(--blue));
          background-size: 300% 100%;
          animation: hdr-flow 5s linear infinite;
        }

        @keyframes hdr-flow {
          0% { background-position: 300% 0; }
          100% { background-position: -300% 0; }
        }

        .up-eyebrow {
          font-family: 'IBM Plex Mono', monospace;
          font-size: 9.5px;
          color: var(--text-muted);
          letter-spacing: 0.14em;
          text-transform: uppercase;
          margin-bottom: 8px;
          display: flex;
          align-items: center;
          gap: 8px;
        }

        .up-eyebrow-dot {
          width: 5px; height: 5px;
          border-radius: 50%;
          background: var(--blue);
          animation: pulse-dot 2s ease-in-out infinite;
        }

        @keyframes pulse-dot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.5; transform: scale(0.8); }
        }

        .up-title {
          font-family: 'DM Serif Display', serif;
          font-size: 28px;
          font-weight: 400;
          letter-spacing: -0.01em;
          color: var(--text-primary);
          margin: 0 0 4px;
          line-height: 1;
        }

        .up-subtitle {
          font-family: 'IBM Plex Mono', monospace;
          font-size: 10.5px;
          color: var(--text-muted);
        }

        .up-header-badges {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-wrap: wrap;
        }

        .up-hbadge {
          font-family: 'IBM Plex Mono', monospace;
          font-size: 10px;
          font-weight: 500;
          padding: 5px 11px;
          border-radius: 20px;
          letter-spacing: 0.06em;
        }

        .up-content {
          display: grid;
          grid-template-columns: 1fr 300px;
          gap: 14px;
          padding: 16px;
        }

        .up-left-col { display: flex; flex-direction: column; gap: 14px; }
        .up-right-col { display: flex; flex-direction: column; gap: 12px; }

        .up-card {
          background: var(--surface);
          border-radius: var(--radius);
          border: 1px solid var(--border);
          box-shadow: var(--shadow-sm);
        }

        .up-card-pad { padding: 26px 28px; }

        .up-card-title {
          font-size: 15px;
          font-weight: 600;
          color: var(--text-primary);
          letter-spacing: -0.02em;
          margin-bottom: 2px;
        }

        .up-card-sub {
          font-family: 'IBM Plex Mono', monospace;
          font-size: 10.5px;
          color: var(--text-muted);
          margin-bottom: 20px;
        }

        .up-illus-strip {
          background: linear-gradient(135deg, rgba(29,111,232,0.03) 0%, rgba(14,166,106,0.03) 100%);
          border-radius: var(--radius);
          border: 1px solid var(--border);
          padding: 20px 24px 16px;
          box-shadow: var(--shadow-sm);
          display: grid;
          grid-template-columns: 320px 1fr;
          gap: 28px;
          align-items: center;
        }

        .up-illus-tag {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 9px;
          font-weight: 600;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: var(--blue);
          background: rgba(29,111,232,0.08);
          border: 1px solid rgba(29,111,232,0.2);
          padding: 4px 10px;
          border-radius: 20px;
          margin-bottom: 14px;
        }

        .up-illus-heading {
          font-family: 'DM Serif Display', serif;
          font-size: 22px;
          font-weight: 400;
          color: var(--text-primary);
          letter-spacing: -0.02em;
          line-height: 1.2;
          margin-bottom: 10px;
        }

        .up-illus-heading em { font-style: italic; color: var(--blue); }

        .up-illus-body {
          font-size: 13px;
          color: var(--text-secondary);
          line-height: 1.65;
          margin-bottom: 16px;
        }

        .up-agent-pills { display: flex; gap: 8px; flex-wrap: wrap; }

        .up-agent-pill {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 10px;
          font-weight: 500;
          padding: 5px 12px;
          border-radius: 20px;
        }

        .up-pill-bull { background: rgba(14,166,106,0.08); border: 1px solid rgba(14,166,106,0.22); color: #0EA66A; }
        .up-pill-bear { background: rgba(217,48,37,0.07); border: 1px solid rgba(217,48,37,0.2); color: #D93025; }
        .up-pill-fact { background: rgba(29,111,232,0.07); border: 1px solid rgba(29,111,232,0.2); color: #1D6FE8; }
        .up-pill-dot { width: 5px; height: 5px; border-radius: 50%; }

        .up-dropzone {
          border-radius: 12px;
          padding: 44px 32px 38px;
          cursor: pointer;
          text-align: center;
          transition: all 0.2s ease;
          position: relative;
          overflow: hidden;
        }

        .up-dz-idle { border: 1.5px dashed rgba(15,23,42,0.18); background: var(--surface-2); }
        .up-dz-idle:hover { border-color: var(--blue); background: rgba(29,111,232,0.025); }
        .up-dz-dragging { border: 1.5px dashed var(--blue); background: rgba(29,111,232,0.04); transform: scale(1.01); }
        .up-dz-filled { border: 1.5px solid rgba(14,166,106,0.4); background: rgba(14,166,106,0.025); }

        .up-icon-wrap {
          width: 52px; height: 52px;
          border-radius: 14px;
          display: flex;
          align-items: center;
          justify-content: center;
          margin: 0 auto 16px;
          transition: transform 0.2s ease;
        }

        .up-dropzone:hover .up-icon-wrap { transform: scale(1.08) translateY(-2px); }
        .up-dz-idle .up-icon-wrap, .up-dz-dragging .up-icon-wrap {
          background: var(--surface); border: 1px solid var(--border); box-shadow: var(--shadow-sm);
        }
        .up-dz-filled .up-icon-wrap { background: rgba(14,166,106,0.1); border: 1px solid rgba(14,166,106,0.22); }

        .up-dz-main-text { font-size: 15px; font-weight: 600; color: var(--text-primary); margin-bottom: 6px; letter-spacing: -0.02em; }

        .up-dz-hint { font-family: 'IBM Plex Mono', monospace; font-size: 10.5px; color: var(--text-muted); line-height: 1.6; }

        .up-file-info {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          margin: 12px auto 0;
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 8px 14px;
          font-family: 'IBM Plex Mono', monospace;
          font-size: 11px;
          color: var(--text-secondary);
          max-width: 280px;
          overflow: hidden;
        }

        .up-file-name { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 180px; }
        .up-file-size { color: var(--text-muted); flex-shrink: 0; font-size: 10px; }

        .up-remove-btn {
          display: inline-flex; align-items: center; gap: 5px;
          font-family: 'IBM Plex Mono', monospace; font-size: 10px;
          color: var(--text-muted); background: none; border: none;
          cursor: pointer; margin-top: 10px; transition: color 0.14s ease; padding: 0;
        }
        .up-remove-btn:hover { color: var(--red); }

        /* Company name input */
        .up-company-input {
          width: 100%;
          margin-bottom: 16px;
          padding: 10px 14px;
          border-radius: 9px;
          border: 1px solid var(--border);
          background: var(--surface-2);
          font-family: 'Figtree', sans-serif;
          font-size: 13.5px;
          color: var(--text-primary);
          outline: none;
          transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }
        .up-company-input:focus {
          border-color: var(--blue);
          box-shadow: 0 0 0 3px rgba(29,111,232,0.1);
        }
        .up-company-label {
          font-family: 'IBM Plex Mono', monospace;
          font-size: 9.5px;
          color: var(--text-muted);
          letter-spacing: 0.1em;
          text-transform: uppercase;
          display: block;
          margin-bottom: 6px;
        }

        /* Error box */
        .up-error-box {
          margin-top: 12px;
          padding: 12px 14px;
          border-radius: 9px;
          background: rgba(217,48,37,0.06);
          border: 1px solid rgba(217,48,37,0.2);
          font-family: 'IBM Plex Mono', monospace;
          font-size: 11px;
          color: var(--red);
          line-height: 1.5;
        }

        .up-analyze-btn {
          width: 100%; margin-top: 16px; padding: 14px;
          border-radius: 10px; font-family: 'Figtree', sans-serif;
          font-size: 14.5px; font-weight: 600; letter-spacing: -0.01em;
          cursor: pointer; transition: all 0.2s ease;
          display: flex; align-items: center; justify-content: center;
          gap: 8px; position: relative; overflow: hidden;
        }

        .up-btn-active {
          background: var(--blue); border: 1px solid transparent; color: #fff;
          box-shadow: 0 2px 8px rgba(29,111,232,0.3), 0 1px 3px rgba(29,111,232,0.2);
        }
        .up-btn-active:hover { background: #1660D0; transform: translateY(-1px); }
        .up-btn-active:active { transform: translateY(0); }
        .up-btn-disabled { background: var(--surface-2); border: 1px solid var(--border); color: var(--text-muted); cursor: not-allowed; }

        .up-processing-wrap {
          margin-top: 16px; background: rgba(15,23,42,0.02);
          border: 1px solid var(--border); border-radius: 12px;
          padding: 16px 18px; overflow: hidden;
        }

        .up-proc-header { display: flex; align-items: center; gap: 10px; margin-bottom: 14px; }

        .up-proc-icon-anim {
          width: 28px; height: 28px; border-radius: 8px;
          background: rgba(29,111,232,0.08); border: 1px solid rgba(29,111,232,0.18);
          display: flex; align-items: center; justify-content: center; flex-shrink: 0;
        }

        .up-proc-label { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--text-secondary); flex: 1; }
        .up-proc-pct { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--blue); font-weight: 600; }

        .up-proc-track { height: 4px; background: var(--border); border-radius: 4px; overflow: hidden; margin-bottom: 12px; }

        .up-proc-fill {
          height: 100%;
          background: linear-gradient(90deg, var(--blue), #60A5FA);
          border-radius: 4px;
          transition: width 0.55s cubic-bezier(0.22, 1, 0.36, 1);
        }

        .up-proc-steps { display: flex; flex-direction: column; gap: 6px; }

        .up-proc-step {
          display: flex; align-items: center; gap: 8px;
          font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; transition: all 0.3s ease;
        }

        .up-proc-step-done { color: var(--green); }
        .up-proc-step-active { color: var(--blue); font-weight: 500; }
        .up-proc-step-pending { color: var(--text-muted); }

        .up-proc-step-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }

        .up-eta {
          display: flex; align-items: center; gap: 5px;
          font-family: 'IBM Plex Mono', monospace; font-size: 10px;
          color: var(--text-muted); margin-top: 12px; justify-content: center;
        }

        .up-preview-section {}

        .up-preview-heading {
          display: flex; align-items: center; gap: 8px;
          font-size: 13px; font-weight: 600; color: var(--text-primary);
          margin-bottom: 12px; letter-spacing: -0.01em;
        }

        .up-preview-heading-badge {
          font-family: 'IBM Plex Mono', monospace; font-size: 8.5px;
          font-weight: 600; letter-spacing: 0.1em; text-transform: uppercase;
          background: rgba(14,166,106,0.1); color: var(--green);
          border: 1px solid rgba(14,166,106,0.22); padding: 2px 8px; border-radius: 10px;
        }

        .up-preview-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }

        .mpv-card { border-radius: 10px; padding: 12px 13px; }
        .mpv-header { display: flex; align-items: center; gap: 7px; margin-bottom: 8px; }
        .mpv-icon-wrap { width: 22px; height: 22px; border-radius: 6px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
        .mpv-label { font-size: 11px; font-weight: 600; color: var(--text-primary); flex: 1; letter-spacing: -0.01em; }
        .mpv-tag { font-family: 'IBM Plex Mono', monospace; font-size: 8px; font-weight: 600; letter-spacing: 0.08em; padding: 2px 6px; border-radius: 6px; }
        .mpv-snippet { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: var(--text-secondary); line-height: 1.55; margin: 0 0 10px; }
        .mpv-score-row { display: flex; align-items: center; gap: 8px; }
        .mpv-score-track { flex: 1; height: 3px; background: rgba(15,23,42,0.07); border-radius: 4px; overflow: hidden; }
        .mpv-score-fill { height: 100%; border-radius: 4px; }
        .mpv-score-val { font-family: 'IBM Plex Mono', monospace; font-size: 10px; font-weight: 600; min-width: 22px; text-align: right; }

        .up-how-section {
          background: var(--surface); border-radius: var(--radius);
          border: 1px solid var(--border); padding: 26px 28px; box-shadow: var(--shadow-sm);
        }

        .up-how-header { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 22px; }
        .up-how-title { font-family: 'DM Serif Display', serif; font-size: 20px; font-weight: 400; color: var(--text-primary); letter-spacing: -0.02em; margin: 0; }
        .up-how-sub { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--text-muted); margin-top: 3px; }
        .up-how-steps { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }

        .up-how-step {
          position: relative; padding: 16px; border-radius: 11px;
          transition: transform 0.2s ease, box-shadow 0.2s ease; cursor: default;
        }
        .up-how-step:hover { transform: translateY(-2px); box-shadow: var(--shadow-md); }
        .up-how-step:not(:last-child)::after {
          content: ''; position: absolute; right: -8px; top: 28px;
          width: 14px; height: 1px; background: var(--border-strong); z-index: 1;
        }

        .up-how-num { font-family: 'IBM Plex Mono', monospace; font-size: 9px; font-weight: 600; letter-spacing: 0.12em; color: var(--text-muted); margin-bottom: 10px; }
        .up-how-icon-box { width: 36px; height: 36px; border-radius: 10px; display: flex; align-items: center; justify-content: center; margin-bottom: 12px; }
        .up-how-step-title { font-size: 13px; font-weight: 600; color: var(--text-primary); letter-spacing: -0.01em; margin-bottom: 6px; }
        .up-how-step-desc { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: var(--text-muted); line-height: 1.6; }

        .up-section-label { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: var(--text-muted); letter-spacing: 0.14em; text-transform: uppercase; font-weight: 500; margin-bottom: 14px; }

        .up-feature-row { display: flex; align-items: flex-start; gap: 12px; padding: 10px; border-radius: 9px; transition: background 0.15s ease; cursor: default; margin-bottom: 2px; }
        .up-feature-row:hover { background: var(--surface-2); }
        .up-feature-icon { width: 30px; height: 30px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; transition: transform 0.2s ease; }
        .up-feature-row:hover .up-feature-icon { transform: scale(1.08); }
        .up-feature-name { font-size: 12.5px; font-weight: 600; color: var(--text-primary); letter-spacing: -0.01em; margin-bottom: 2px; }
        .up-feature-desc { font-family: 'IBM Plex Mono', monospace; font-size: 9.5px; color: var(--text-muted); line-height: 1.5; }

        .up-format-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; border-radius: 7px; transition: background 0.14s ease; }
        .up-format-row:hover { background: var(--surface-2); }
        .up-format-name { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--text-secondary); }
        .up-format-check { width: 20px; height: 20px; background: rgba(14,166,106,0.1); border: 1px solid rgba(14,166,106,0.22); border-radius: 6px; display: flex; align-items: center; justify-content: center; }
        .up-divider { height: 1px; background: var(--border); margin: 10px 0; }
        .up-maxsize-row { display: flex; justify-content: space-between; align-items: center; padding: 6px 10px; }
        .up-maxsize-label { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--text-muted); }
        .up-maxsize-val { font-family: 'IBM Plex Mono', monospace; font-size: 11px; color: var(--text-secondary); font-weight: 500; }

        .up-hint { font-family: 'IBM Plex Mono', monospace; font-size: 10px; color: var(--text-muted); text-align: center; margin-top: 10px; display: flex; align-items: center; justify-content: center; gap: 5px; }

        .up-scan-dots { display: flex; align-items: center; gap: 5px; justify-content: center; margin-top: 10px; }
        .up-scan-dot { width: 5px; height: 5px; border-radius: 50%; transition: background 0.3s ease, transform 0.3s ease; }
      `}</style>

      <div className="up-root">
        {/* ── HEADER ── */}
        <div className="up-header">
          <div>
            <div className="up-eyebrow">
              <div className="up-eyebrow-dot" />
              VentureFlow AI · New Submission
            </div>
            <h1 className="up-title">Upload Deck</h1>
            <p className="up-subtitle">AI-powered fact-checking & investment intelligence for VCs</p>
          </div>
          <div className="up-header-badges">
            <span className="up-hbadge" style={{ background: "rgba(14,166,106,0.08)", color: "#0EA66A", border: "1px solid rgba(14,166,106,0.22)" }}>
              ● Bull Agent Active
            </span>
            <span className="up-hbadge" style={{ background: "rgba(217,48,37,0.07)", color: "#D93025", border: "1px solid rgba(217,48,37,0.2)" }}>
              ● Bear Agent Active
            </span>
            <span className="up-hbadge" style={{ background: "rgba(29,111,232,0.07)", color: "#1D6FE8", border: "1px solid rgba(29,111,232,0.2)" }}>
              ● Fact-Check Live
            </span>
          </div>
        </div>

        <div className="up-content">
          {/* ── LEFT COLUMN ── */}
          <div className="up-left-col">

            {/* ILLUSTRATION STRIP */}
            <motion.div className="up-illus-strip"
              initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}>
              <div style={{ position: "relative" }}>
                <DeckIllustration />
                <div className="up-scan-dots">
                  {[0, 1, 2].map(i => (
                    <div key={i} className="up-scan-dot" style={{
                      background: activeDot === i ? "#1D6FE8" : "rgba(15,23,42,0.12)",
                      transform: activeDot === i ? "scale(1.4)" : "scale(1)",
                    }} />
                  ))}
                </div>
              </div>

              <div>
                <div className="up-illus-tag">
                  <Eye size={9} />
                  Dual-Agent Intelligence
                </div>
                <h2 className="up-illus-heading">
                  Instant VC-grade<br /><em>deal intelligence</em>
                </h2>
                <p className="up-illus-body">
                  VentureFlow runs your pitch deck through independent Bull &amp; Bear agents,
                  cross-references every claim with live databases, and surfaces founder signals,
                  market gaps, and risk vectors — in under 60 seconds.
                </p>
                <div className="up-agent-pills">
                  <span className="up-agent-pill up-pill-bull"><span className="up-pill-dot" style={{ background: "#0EA66A" }} />Bull Agent</span>
                  <span className="up-agent-pill up-pill-bear"><span className="up-pill-dot" style={{ background: "#D93025" }} />Bear Agent</span>
                  <span className="up-agent-pill up-pill-fact"><span className="up-pill-dot" style={{ background: "#1D6FE8" }} />Live Fact-Check</span>
                </div>
              </div>
            </motion.div>

            {/* UPLOAD CARD */}
            <motion.div className="up-card up-card-pad"
              initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1, duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>
              <div className="up-card-title">Pitch Deck</div>
              <div className="up-card-sub">Drop your file below or click to browse</div>

              {/* Company name input */}
              <label className="up-company-label">Company name</label>
              <input
                className="up-company-input"
                type="text"
                placeholder="e.g. NovaMed AI, CarbonCycle…"
                value={companyInput}
                onChange={e => setCompanyInput(e.target.value)}
                disabled={isAnalyzing}
              />

              <div
                className={`up-dropzone ${isDragging ? "up-dz-dragging" : fileName ? "up-dz-filled" : "up-dz-idle"}`}
                onDrop={handleDrop}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onClick={() => !isAnalyzing && inputRef.current?.click()}
              >
                <input ref={inputRef} type="file" style={{ display: "none" }}
                  accept=".pdf,application/pdf" onChange={handleFileChange} />

                <AnimatePresence mode="wait">
                  {!fileName ? (
                    <motion.div key="empty"
                      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
                      <div className="up-icon-wrap">
                        <Upload size={21} color={isDragging ? "#1D6FE8" : "#94A3B8"} strokeWidth={1.6} />
                      </div>
                      <div className="up-dz-main-text">{isDragging ? "Release to upload" : "Drop your deck here"}</div>
                      <div className="up-dz-hint">or click to browse<br />PDF · up to 10 MB</div>
                    </motion.div>
                  ) : (
                    <motion.div key="selected"
                      initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}
                      exit={{ opacity: 0, y: -6 }} transition={{ duration: 0.2 }}>
                      <div className="up-icon-wrap">
                        <FileText size={21} color="#0EA66A" strokeWidth={1.6} />
                      </div>
                      <div className="up-dz-main-text" style={{ color: "#0EA66A" }}>File ready</div>
                      <div style={{ display: "flex", justifyContent: "center" }}>
                        <div className="up-file-info">
                          <FileText size={12} color="#94A3B8" />
                          <span className="up-file-name">{fileName}</span>
                          {fileSize && <span className="up-file-size">{fileSize}</span>}
                        </div>
                      </div>
                      {!isAnalyzing && (
                        <div>
                          <button className="up-remove-btn"
                            onClick={e => { e.stopPropagation(); setFileName(null); setFileSize(null); setFileObj(null); reset(); }}>
                            <X size={10} /> remove file
                          </button>
                        </div>
                      )}
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* Error display */}
              <AnimatePresence>
                {(error || fileError) && (
                  <motion.div className="up-error-box"
                    initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}>
                    ⚠ {fileError || error}
                    <br />
                    <span style={{ fontSize: 9, opacity: 0.7 }}>Check that the backend is reachable and that Neon is configured.</span>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* ANALYZE BUTTON */}
              <motion.button
                className={`up-analyze-btn ${fileName && !isAnalyzing ? "up-btn-active" : "up-btn-disabled"}`}
                onClick={handleAnalyze}
                disabled={!fileName || isAnalyzing}
                whileTap={fileName && !isAnalyzing ? { scale: 0.99 } : {}}
              >
                {isAnalyzing ? (
                  <>
                    <motion.div animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }}>
                      <Zap size={15} />
                    </motion.div>
                    {stageLabelDisplay || "Running agents…"}
                  </>
                ) : (
                  <>
                    <Zap size={15} />
                    {fileName ? "Run AI Analysis" : "Upload a Deck First"}
                    {fileName && <ArrowRight size={14} style={{ marginLeft: "2px" }} />}
                  </>
                )}
              </motion.button>

              {/* ANIMATED PROCESSING */}
              <AnimatePresence>
                {isAnalyzing && (
                  <motion.div className="up-processing-wrap"
                    initial={{ opacity: 0, height: 0 }}
                    animate={{ opacity: 1, height: "auto" }}
                    exit={{ opacity: 0, height: 0 }}
                    transition={{ duration: 0.28 }}>

                    <div className="up-proc-header">
                      <motion.div className="up-proc-icon-anim"
                        animate={{ scale: [1, 1.1, 1] }} transition={{ repeat: Infinity, duration: 1.2 }}>
                        <StepIcon size={13} color="#1D6FE8" strokeWidth={1.75} />
                      </motion.div>
                      <span className="up-proc-label">{stageLabelDisplay}</span>
                      <span className="up-proc-pct">{progressPct}%</span>
                    </div>

                    <div className="up-proc-track">
                      <div className="up-proc-fill" style={{ width: `${progressPct}%` }} />
                    </div>

                    <div className="up-proc-steps">
                      {analysisSteps.map((s, i) => {
                        const S = s.icon;
                        const status = i < analysisStep ? "done" : i === analysisStep ? "active" : "pending";
                        return (
                          <div key={i} className={`up-proc-step up-proc-step-${status}`}>
                            <div className="up-proc-step-dot" style={{
                              background: status === "done" ? "#0EA66A" : status === "active" ? "#1D6FE8" : "rgba(15,23,42,0.12)"
                            }} />
                            {s.label}
                            {status === "done" && <CheckCircle size={9} color="#0EA66A" style={{ marginLeft: "auto" }} />}
                            {status === "active" && (
                              <motion.div style={{ marginLeft: "auto" }}
                                animate={{ opacity: [1, 0.3, 1] }} transition={{ repeat: Infinity, duration: 1 }}>
                                <Activity size={9} color="#1D6FE8" />
                              </motion.div>
                            )}
                          </div>
                        );
                      })}
                    </div>

                    <div className="up-eta">
                      <Clock size={10} />
                      Estimated 2–4 minutes · Do not close this tab
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {/* MINI PREVIEW CARDS (post-analysis) */}
              <AnimatePresence>
                {showPreview && (
                  <motion.div
                    initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0 }} transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
                    style={{ marginTop: 18 }}>
                    <div className="up-preview-heading">
                      <CheckCircle size={14} color="#0EA66A" />
                      Analysis Complete
                      <span className="up-preview-heading-badge">Preview</span>
                    </div>
                    <div className="up-preview-grid">
                      {miniPreviewCards.map((card, i) => (
                        <MiniPreviewCard key={i} card={card} delay={i * 0.1} />
                      ))}
                    </div>
                    <div style={{ marginTop: 12, textAlign: "center" }}>
                      <motion.button
                        style={{
                          background: "var(--blue)", color: "#fff", border: "none",
                          borderRadius: 9, padding: "10px 22px", fontSize: 13,
                          fontWeight: 600, cursor: "pointer", display: "inline-flex",
                          alignItems: "center", gap: 7, fontFamily: "Figtree, sans-serif",
                          letterSpacing: "-0.01em", boxShadow: "0 2px 8px rgba(29,111,232,0.28)"
                        }}
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                        onClick={() => navigate("/analysis")}>
                        View Full Report <ChevronRight size={14} />
                      </motion.button>
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>

              {fileName && !isAnalyzing && !showPreview && (
                <p className="up-hint">
                  <CheckCircle size={11} color="#0EA66A" />
                  Analysis typically completes in 2–4 minutes
                </p>
              )}
            </motion.div>

            {/* ── HOW IT WORKS ── */}
            <motion.div className="up-how-section"
              initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.22, duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>
              <div className="up-how-header">
                <div>
                  <h2 className="up-how-title">How it works</h2>
                  <p className="up-how-sub">From upload to VC-grade memo in 2–4 minutes</p>
                </div>
                <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: 9.5, color: "var(--text-muted)", letterSpacing: "0.1em" }}>4 STEPS</span>
              </div>

              <div className="up-how-steps">
                {howItWorksSteps.map((step, i) => {
                  const Icon = step.icon;
                  return (
                    <motion.div key={i} className="up-how-step"
                      style={{ background: step.bg, border: "1px solid rgba(15,23,42,0.06)" }}
                      initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}
                      transition={{ delay: 0.28 + i * 0.08, duration: 0.38 }}>
                      <div className="up-how-num">{step.number}</div>
                      <div className="up-how-icon-box" style={{
                        background: `rgba(${step.color === "#1D6FE8" ? "29,111,232" : step.color === "#0EA66A" ? "14,166,106" : step.color === "#C47A0A" ? "196,122,10" : "155,89,182"},0.12)`
                      }}>
                        <Icon size={17} color={step.color} strokeWidth={1.75} />
                      </div>
                      <div className="up-how-step-title">{step.title}</div>
                      <div className="up-how-step-desc">{step.desc}</div>
                    </motion.div>
                  );
                })}
              </div>
            </motion.div>
          </div>

          {/* ── RIGHT COLUMN ── */}
          <motion.div className="up-right-col"
            initial={{ opacity: 0, x: 10 }} animate={{ opacity: 1, x: 0 }}
            transition={{ delay: 0.14, duration: 0.45, ease: [0.22, 1, 0.36, 1] }}>

            <div className="up-card" style={{ padding: "20px" }}>
              <div className="up-section-label">What We Analyze</div>
              {analysisFeatures.map((f, i) => {
                const Icon = f.icon;
                return (
                  <motion.div key={i} className="up-feature-row"
                    initial={{ opacity: 0, x: 8 }} animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.2 + i * 0.07, duration: 0.35 }}>
                    <div className="up-feature-icon" style={{ background: f.bg, border: `1px solid ${f.border}` }}>
                      <Icon size={13} color={f.color} strokeWidth={1.75} />
                    </div>
                    <div>
                      <div className="up-feature-name">{f.label}</div>
                      <div className="up-feature-desc">{f.desc}</div>
                    </div>
                  </motion.div>
                );
              })}
            </div>

            <div className="up-card" style={{ padding: "18px 20px" }}>
              <div className="up-section-label">Supported Formats</div>
              {[{ fmt: "PDF", desc: "Recommended" }].map(f => (
                <div key={f.fmt} className="up-format-row">
                  <div>
                    <span className="up-format-name">.{f.fmt.toLowerCase()}</span>
                    <span style={{ fontFamily: "'IBM Plex Mono', monospace", fontSize: "9.5px", color: "#C0CADA", marginLeft: "8px" }}>{f.desc}</span>
                  </div>
                  <div className="up-format-check">
                    <CheckCircle size={11} color="#0EA66A" strokeWidth={2.5} />
                  </div>
                </div>
              ))}
              <div className="up-divider" />
              <div className="up-maxsize-row">
                <span className="up-maxsize-label">Max file size</span>
                <span className="up-maxsize-val">10 MB</span>
              </div>
            </div>

            <motion.div className="up-card" style={{ padding: "18px 20px" }}
              initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.35 }}>
              <div className="up-section-label">Data Sources</div>
              {[
                { name: "Neon report database", icon: Database, color: "#1D6FE8" },
                { name: "DuckDuckGo web search", icon: Globe, color: "#0EA66A" },
                { name: "SEC EDGAR filings", icon: Shield, color: "#D93025" },
                { name: "Groq Llama 3.3 70B", icon: Activity, color: "#C47A0A" },
              ].map((src, i) => {
                const Icon = src.icon;
                return (
                  <div key={i} className="up-feature-row" style={{ padding: "8px 10px" }}>
                    <div className="up-feature-icon" style={{
                      width: 26, height: 26, borderRadius: 7,
                      background: `rgba(${src.color === "#1D6FE8" ? "29,111,232" : src.color === "#0EA66A" ? "14,166,106" : src.color === "#D93025" ? "217,48,37" : "196,122,10"},0.08)`,
                      border: `1px solid rgba(${src.color === "#1D6FE8" ? "29,111,232" : src.color === "#0EA66A" ? "14,166,106" : src.color === "#D93025" ? "217,48,37" : "196,122,10"},0.18)`
                    }}>
                      <Icon size={12} color={src.color} strokeWidth={1.75} />
                    </div>
                    <span className="up-feature-name" style={{ fontSize: 12 }}>{src.name}</span>
                  </div>
                );
              })}
            </motion.div>
          </motion.div>
        </div>
      </div>
    </>
  );
};

export default UploadDeck;
