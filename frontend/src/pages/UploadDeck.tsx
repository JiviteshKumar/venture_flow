import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useNavigate } from "react-router-dom";
import {
  ArrowLeft, ArrowRight, Check, Clock, FileText, Loader2, X,
} from "lucide-react";
import { useApp } from "../context/AppContext";
import { formatBytes } from "../utils/format";
import { formatElapsed, useElapsedSeconds } from "../hooks/useElapsed";
import OutOfScopeDialog from "../components/common/OutOfScopeDialog";
import { GrowBar } from "../components/ui/Motion";
import { Magnetic, Reveal, SplitWords } from "../components/ui/scroll";
import { Badge, BadgeStyles } from "../components/ui/Surface";
import IntakePortal, { type IntakeState } from "../components/upload/IntakePortal";
import DeckSculpture, { type DeckPage } from "../components/analysis/DeckSculpture";
import AnalysisTheatre from "../components/analysis/AnalysisTheatre";

/**
 * Submission, as the first scene rather than a form.
 *
 * THE SHAPE OF IT
 *
 * One statement, one target, and then a readout of what was actually found in
 * the file. The aperture is empty until a deck exists; the moment one is
 * parsed it is replaced by that deck's own pages in space, and the numbers
 * beside it are counts taken from the extractor's output -- pages, claims,
 * founders, financial signals, characters of text, and which reader produced
 * them.
 *
 * WHAT IS NOT HERE
 *
 * No invented ingestion metrics. A reference version of this screen counts
 * "142 entities" and "11 market signals"; this extractor produces neither, so
 * neither is shown. Every figure below is one the pipeline genuinely returns,
 * and a field the deck did not state renders as an em dash rather than a zero
 * -- a deck that did not mention revenue and a company with no revenue are
 * different findings.
 */

// Kept in step with document_extractor.SUPPORTED_FORMATS on the backend. The
// upload used to be PDF-only, which forced founders to export their deck
// before they could use the product at all.
const ACCEPTED = [".pdf", ".pptx", ".docx", ".txt", ".md"];
const MAX_BYTES = 10 * 1024 * 1024;

/**
 * The pipeline's own steps, in the order it reports them.
 *
 * These strings are matched against the stage the backend writes to the job
 * row (see ventureflow_agent._stage), which is why they are phrased as the
 * backend phrases them rather than as marketing copy.
 */
const STAGES = [
  "Reading the document",
  "Verifying claims against live web search",
  "Detecting risk signals in the deck",
  "Checking founder backgrounds",
  "Running market, team, bull and bear agents",
  "Retrieving evidence from prior reports",
  "Writing the investment memo",
];

const UploadDeck = () => {
  const navigate = useNavigate();
  const {
    status, currentStage, progressPct, prepareUpload, runAnalysis,
    uploadResult, report, error, outOfScope, dismissOutOfScope, reset, startedAt,
  } = useApp();

  const isAnalyzing = status === "uploading" || status === "analyzing";
  const isParsed = status === "ready" && uploadResult !== null;
  const isDone = status === "done" && report !== null;
  const elapsed = useElapsedSeconds(isAnalyzing ? startedAt : null);

  const [fileName, setFileName] = useState<string | null>(null);
  const [fileSize, setFileSize] = useState<string | null>(null);
  const [fileObj, setFileObj] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [companyInput, setCompanyInput] = useState("");
  // Founder names, comma-separated. Pre-filled from what the extractor found
  // and editable before submitting, because these names go to a live web
  // search and a public-background assessment -- a name the extractor got
  // wrong becomes a background check on a stranger.
  const [foundersInput, setFoundersInput] = useState("");
  const [foundersTouched, setFoundersTouched] = useState(false);
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const detectedFounders = uploadResult?.detected_founders ?? [];
  const parsing = status === "uploading" && !isAnalyzing;

  useEffect(() => {
    if (foundersTouched) return;
    const names = (uploadResult?.detected_founders ?? []).map((f) => f.name).filter(Boolean);
    setFoundersInput(names.join(", "));
  }, [uploadResult, foundersTouched]);

  // ── What the extractor actually found ─────────────────────────────────────

  /** The deck's own pages. Every one is "read" here: at this point the
   *  extractor has produced text for them, and which ones reached a structured
   *  FIELD is a question the report answers, not the upload. */
  const pages: DeckPage[] = (uploadResult?.deck_slides ?? []).map((_, i) => ({
    slide: i + 1,
    read: true,
  }));

  const financialSignals = uploadResult
    ? [uploadResult.revenue, uploadResult.burn_rate, uploadResult.runway_months]
      .filter((v) => v !== null && v !== undefined).length
    : 0;

  const readout = uploadResult
    ? [
      { label: "Pages", value: String(uploadResult.page_count || pages.length || 0), hint: "" },
      { label: "Claims found", value: String(uploadResult.detected_claims?.length ?? 0), hint: "candidates for verification" },
      { label: "Founders named", value: String(detectedFounders.length), hint: detectedFounders.length ? "from the team slide" : "no team slide found" },
      { label: "Financial signals", value: `${financialSignals} of 3`, hint: "revenue, burn, runway" },
      {
        label: "Text recovered",
        value: uploadResult.extracted_text
          ? `${(Math.round(uploadResult.extracted_text.length / 100) / 10).toFixed(1)}k`
          : "0",
        hint: "characters",
      },
      {
        label: "Read by",
        value: uploadResult.text_source === "ocr" ? "OCR"
          : uploadResult.text_source === "hybrid" ? "Text + OCR" : "Text layer",
        hint: uploadResult.document_format ?? "",
      },
    ]
    : [];

  const intake: IntakeState = parsing ? "reading" : dragging ? "armed" : "idle";

  // ── File handling ─────────────────────────────────────────────────────────

  const storeFile = (f: File) => {
    const extension = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED.includes(extension)) {
      setFileError(`That file type is not supported. Use ${ACCEPTED.join(", ")}.`);
      return;
    }
    if (f.size > MAX_BYTES) {
      setFileError(`That file is ${formatBytes(f.size)}. The limit is 10 MB.`);
      return;
    }
    setFileError(null);
    setFileName(f.name);
    setFileSize(formatBytes(f.size));
    setFileObj(f);
    setFoundersTouched(false);
    const derived = f.name.replace(/\.[^.]+$/, "").replace(/[-_]/g, " ");
    if (!companyInput) setCompanyInput(derived);
    if (status === "done" || status === "ready") reset();
    // Parse immediately, so the readout can show what is in the deck before
    // the analysis is committed to.
    void prepareUpload(f, companyInput || derived || "Unknown Company");
  };

  const clearFile = () => {
    setFileName(null); setFileSize(null); setFileObj(null); setFileError(null);
    reset();
  };

  const run = async () => {
    if (!fileObj || isAnalyzing) return;
    const founders = foundersInput.split(",").map((n) => n.trim()).filter(Boolean).slice(0, 5);
    await runAnalysis(fileObj, companyInput || fileName || "Unknown Company", founders);
  };

  /** Which real stage the backend last reported. -1 until one arrives. */
  const stageIndex = STAGES.findIndex((s) =>
    currentStage.toLowerCase().includes(s.slice(0, 16).toLowerCase()));

  return (
    <div className="up-root">
      <BadgeStyles />
      <style>{`
        .up-root { min-height: 100%; background: var(--bg); color: var(--text); }

        .up-bar {
          position: sticky; top: 0; z-index: 20;
          display: flex; align-items: center; gap: 14px;
          padding: 16px clamp(20px, 5vw, 72px);
          background: linear-gradient(180deg, var(--bg) 62%, transparent);
        }
        .up-back {
          display: inline-flex; align-items: center; gap: 8px;
          padding: 8px 15px; border-radius: var(--r-pill); cursor: pointer;
          font: inherit; font-size: var(--t-micro); font-weight: 600;
          color: var(--text-2); background: var(--neutral-quiet);
          border: 1px solid var(--line);
          transition: color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
        }
        .up-back:hover { color: var(--text); border-color: var(--line-strong); }

        .up-stage { max-width: 1180px; margin: 0 auto; padding: clamp(16px, 4vh, 40px) clamp(20px, 5vw, 72px) 120px; }

        .up-headline {
          font-family: var(--font-display); font-size: clamp(40px, 6.4vw, 96px);
          line-height: 0.96; letter-spacing: -0.035em; margin: 0; color: var(--text);
        }
        .up-sub { font-size: clamp(15px, 1.3vw, 19px); line-height: 1.6; color: var(--text-2); margin: 22px 0 0; max-width: 52ch; }

        /* The target. One large object, not a dashed rectangle inside a card. */
        .up-target {
          position: relative; margin-top: clamp(28px, 5vh, 56px);
          border-radius: var(--r-xl);
          border: 1px solid var(--line);
          background: linear-gradient(180deg, rgba(143,182,255,0.045), transparent 70%);
          display: grid; place-items: end center; text-align: center;
          min-height: 420px; padding: 40px 24px 42px; cursor: pointer; overflow: hidden;
          transition: border-color var(--dur-base) var(--ease-out),
                      background var(--dur-base) var(--ease-out),
                      transform var(--dur-base) var(--ease-out);
        }
        .up-target:hover { border-color: var(--accent-line); }
        .up-target[data-drag="true"] {
          border-color: var(--accent);
          background: linear-gradient(180deg, var(--accent-quiet), transparent 70%);
          transform: scale(1.004);
        }
        .up-target[data-filled="true"] { cursor: default; }
        .up-target-inner { position: relative; z-index: 2; }
        .up-target-title { font-size: clamp(19px, 2vw, 26px); font-weight: 600; letter-spacing: -0.02em; }
        .up-target-hint { font-size: var(--t-small); color: var(--text-3); margin-top: 9px; }

        /* The readout: the deck's own numbers, beside the deck itself. */
        .up-readout {
          display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 1px; background: var(--line);
          border: 1px solid var(--line); border-radius: var(--r-lg); overflow: hidden;
        }
        .up-cell { background: var(--surface); padding: 18px 20px; }
        .up-cell-v { font-family: var(--font-display); font-size: 30px; line-height: 1; letter-spacing: -0.02em; }
        .up-cell-h { font-size: var(--t-micro); color: var(--text-3); margin-top: 6px; min-height: 1em; }

        .up-field { display: block; margin-bottom: 18px; }
        .up-input {
          width: 100%; padding: 12px 14px; font: inherit; font-size: var(--t-body);
          background: var(--surface); color: var(--text);
          border: 1px solid var(--line-strong); border-radius: var(--r-sm);
          transition: border-color var(--dur-fast) var(--ease-out), box-shadow var(--dur-fast) var(--ease-out);
        }
        .up-input::placeholder { color: var(--text-faint); }
        .up-input:focus { outline: none; border-color: var(--accent); box-shadow: 0 0 0 3px var(--accent-quiet); }
        .up-help { font-size: var(--t-micro); color: var(--text-3); margin-top: 8px; line-height: 1.55; }

        .up-run {
          width: 100%; display: inline-flex; align-items: center; justify-content: center; gap: 10px;
          padding: 17px 26px; border-radius: var(--r-pill); cursor: pointer;
          font: inherit; font-size: 15px; font-weight: 600;
          background: var(--accent); color: #fff; border: none;
          box-shadow: 0 10px 30px rgba(47,107,255,0.28);
          transition: background var(--dur-fast) var(--ease-out),
                      transform var(--dur-fast) var(--ease-out),
                      box-shadow var(--dur-base) var(--ease-out);
        }
        .up-run:hover:not(:disabled) { background: var(--accent-hover); transform: translateY(-1px); }
        .up-run:disabled { background: var(--neutral-quiet); color: var(--text-3); box-shadow: none; cursor: not-allowed; }

        .up-step { display: flex; align-items: center; gap: 11px; padding: 9px 0; font-size: var(--t-small); color: var(--text-faint); }
        .up-step[data-state="done"] { color: var(--text-2); }
        .up-step[data-state="active"] { color: var(--text); font-weight: 600; }
        .up-step-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--surface-3); flex-shrink: 0; }
        .up-step[data-state="done"] .up-step-dot { background: var(--verified); }
        .up-step[data-state="active"] .up-step-dot { background: var(--accent); box-shadow: 0 0 0 4px var(--accent-quiet); }

        .up-split { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 0.92fr); gap: clamp(24px, 4vw, 56px); align-items: start; }
        @media (max-width: 900px) {
          .up-split { grid-template-columns: 1fr; }
          .up-readout { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
      `}</style>

      <div className="up-bar">
        <button className="up-back" onClick={() => navigate("/")} data-cursor="Back">
          <ArrowLeft size={14} /> All analyses
        </button>
      </div>

      <div className="up-stage">
        <Reveal>
          <h1 className="up-headline">
            <SplitWords text="Give us a company." />
            <br />
            <span style={{ color: "var(--text-3)" }}>
              <SplitWords text="We'll investigate it." delay={0.16} />
            </span>
          </h1>
        </Reveal>
        <Reveal delay={0.24}>
          <p className="up-sub">
            Upload a pitch deck. VentureFlow extracts its claims, checks them against
            live sources, and challenges the assumptions underneath &mdash; then says
            plainly what it could not establish.
          </p>
        </Reveal>

        <Reveal delay={0.3}>
          <div
            className="up-target"
            data-drag={dragging}
            data-filled={Boolean(fileName)}
            data-cursor={fileName ? undefined : "Drop"}
            onDrop={(e) => {
              e.preventDefault(); setDragging(false);
              if (e.dataTransfer.files?.length) storeFile(e.dataTransfer.files[0]);
            }}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onClick={() => !isAnalyzing && !fileName && inputRef.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === "Enter" || e.key === " ") && !isAnalyzing && !fileName) {
                e.preventDefault(); inputRef.current?.click();
              }
            }}
            role="button"
            tabIndex={isAnalyzing || fileName ? -1 : 0}
            aria-label="Choose a pitch deck, or drop one here"
          >
            <input
              ref={inputRef} type="file" style={{ display: "none" }}
              accept={ACCEPTED.join(",")}
              onChange={(e) => e.target.files?.length && storeFile(e.target.files[0])}
            />

            {/* An empty aperture until there is a deck; then the deck itself. */}
            {pages.length > 0
              ? <DeckSculpture pages={pages} progress={0} align="center" />
              : <IntakePortal state={intake} height={420} />}

            <div className="up-target-inner">
              <AnimatePresence mode="wait" initial={false}>
                {!fileName ? (
                  <motion.div key="empty" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -8 }} transition={{ duration: 0.2 }}>
                    <div className="up-target-title">
                      {dragging ? "Release to begin" : "Drop a pitch deck here"}
                    </div>
                    <div className="up-target-hint">
                      PDF, PPTX, DOCX, TXT or MD &middot; up to 10 MB &middot; or click to browse
                    </div>
                  </motion.div>
                ) : (
                  <motion.div key="filled" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }} transition={{ duration: 0.2 }}>
                    <div style={{ display: "inline-flex", alignItems: "center", gap: 12, padding: "10px 16px", borderRadius: "var(--r-pill)", background: "var(--neutral-quiet)", border: "1px solid var(--line)" }}>
                      <FileText size={15} color={isParsed ? "var(--verified)" : "var(--accent)"} />
                      <span style={{ fontSize: 13.5, fontWeight: 600 }}>{fileName}</span>
                      <span className="vf-num" style={{ fontSize: 12, color: "var(--text-3)" }}>{fileSize}</span>
                      {parsing && (
                        <motion.span animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 1, ease: "linear" }} style={{ display: "flex", color: "var(--accent)" }}>
                          <Loader2 size={13} />
                        </motion.span>
                      )}
                      {!isAnalyzing && (
                        <button
                          onClick={(e) => { e.stopPropagation(); clearFile(); }}
                          aria-label="Remove file"
                          style={{ display: "flex", background: "none", border: "none", color: "var(--text-3)", cursor: "pointer", padding: 0 }}
                        >
                          <X size={14} />
                        </button>
                      )}
                    </div>
                    <div className="up-target-hint">
                      {parsing ? "Reading the document…" : isParsed ? "Read. Check the details before we start." : ""}
                    </div>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </div>
        </Reveal>

        {(fileError || (error && !outOfScope)) && (
          <div
            role="alert"
            style={{
              marginTop: 16, padding: "13px 16px", borderRadius: "var(--r-md)",
              background: "var(--critical-quiet)", border: "1px solid var(--critical-line)",
              color: "var(--text)", fontSize: 13.5,
            }}
          >
            {fileError || error}
          </div>
        )}

        <AnimatePresence>
          {isParsed && (
            <motion.div
              initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              transition={{ duration: 0.35 }}
              style={{ marginTop: 44 }}
            >
              <div className="up-split">
                <div>
                  <div className="vf-label" style={{ marginBottom: 14 }}>Deck ingestion</div>
                  <div className="up-readout">
                    {readout.map((r) => (
                      <div className="up-cell" key={r.label}>
                        <div className="vf-label" style={{ marginBottom: 10 }}>{r.label}</div>
                        <div className="up-cell-v">{r.value}</div>
                        <div className="up-cell-h">{r.hint}</div>
                      </div>
                    ))}
                  </div>

                  {uploadResult?.text_source && uploadResult.text_source !== "text_layer" && (
                    <p style={{ marginTop: 16, fontSize: 13, lineHeight: 1.65, color: "var(--text-2)" }}>
                      <Badge tone="accent" size="sm">Read by OCR</Badge>{" "}
                      {uploadResult.text_source === "ocr"
                        ? "This deck has no text layer, so every page was recognised from its image."
                        : "This deck's text layer was thin, so the pages were also read as images."}
                      {" "}Treat any figure as read from a picture: OCR misreads digits more
                      often than it misreads words.
                    </p>
                  )}
                </div>

                <div>
                  <div className="vf-label" style={{ marginBottom: 14 }}>Before we start</div>

                  <label className="up-field">
                    <span className="vf-label" style={{ display: "block", marginBottom: 8 }}>Company name</span>
                    <input
                      className="up-input"
                      value={companyInput}
                      onChange={(e) => setCompanyInput(e.target.value)}
                      placeholder="e.g. NovaMed AI"
                      disabled={isAnalyzing}
                    />
                  </label>

                  <label className="up-field">
                    <span className="vf-label" style={{ display: "block", marginBottom: 8 }}>
                      Founders
                      {detectedFounders.length > 0 && (
                        <span style={{ color: "var(--verified)", marginLeft: 8, textTransform: "none", letterSpacing: 0 }}>
                          {detectedFounders.length} found in the deck
                        </span>
                      )}
                    </span>
                    <input
                      className="up-input"
                      value={foundersInput}
                      onChange={(e) => { setFoundersTouched(true); setFoundersInput(e.target.value); }}
                      placeholder="Comma-separated, e.g. Ada Lovelace, Grace Hopper"
                      disabled={isAnalyzing}
                    />
                    <span className="up-help">
                      {detectedFounders.length > 0
                        ? "Read from the deck's team slide. Each name is searched against public evidence, so correct them before running."
                        : "No team slide was found. Add names to enable the background check, or leave this empty to skip it."}
                    </span>
                  </label>

                  <Magnetic>
                    <button className="up-run" onClick={run} disabled={isAnalyzing || parsing} data-cursor="Run">
                      Begin investigation <ArrowRight size={17} />
                    </button>
                  </Magnetic>
                  <p className="up-help" style={{ textAlign: "center" }}>
                    Five to ten minutes. You can leave this tab and come back.
                  </p>
                </div>
              </div>
            </motion.div>
          )}
        </AnimatePresence>

        <AnimatePresence>
          {isAnalyzing && (
            <motion.div
              initial={{ opacity: 0, y: 16 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}
              style={{ marginTop: 44 }}
            >
              <div className="vf-label" style={{ marginBottom: 6 }}>Investigating</div>
              <div style={{ display: "flex", alignItems: "baseline", gap: 16, flexWrap: "wrap", marginBottom: 6 }}>
                <div className="vf-md">{companyInput || fileName}</div>
                <span style={{ fontSize: 13.5, color: "var(--text-3)" }}>{currentStage}</span>
                <span style={{ marginLeft: "auto", display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13, color: "var(--text-3)" }}>
                  <Clock size={13} />
                  <span className="vf-num">{formatElapsed(elapsed)}</span> elapsed
                </span>
              </div>
              <GrowBar pct={progressPct} color="var(--accent)" height={3} />

              {/* The specialists, driven by the backend's own stage string. */}
              <AnalysisTheatre
                company={companyInput || fileName || "This deck"}
                stage={currentStage}
                height={520}
              />

              {/* The same sequence in reading order, for anyone who wants the
                  list rather than the picture. */}
              <details style={{ marginTop: 4 }}>
                <summary style={{ cursor: "pointer", fontSize: 13, color: "var(--text-3)" }}>
                  Steps, in order
                </summary>
                <div style={{ marginTop: 10, maxWidth: 560 }}>
                  {STAGES.map((s, i) => (
                    <div
                      key={s}
                      className="up-step"
                      data-state={stageIndex < 0 ? "" : i < stageIndex ? "done" : i === stageIndex ? "active" : ""}
                    >
                      <span className="up-step-dot" />
                      {s}
                      {stageIndex > i && <Check size={13} color="var(--verified)" style={{ marginLeft: "auto" }} />}
                    </div>
                  ))}
                </div>
              </details>
            </motion.div>
          )}
        </AnimatePresence>

        {isDone && (
          <div
            style={{
              marginTop: 44, display: "flex", alignItems: "center", gap: 18, flexWrap: "wrap",
              padding: "22px 24px", borderRadius: "var(--r-lg)",
              border: "1px solid var(--verified-line)", background: "var(--verified-quiet)",
            }}
          >
            <Check size={20} color="var(--verified)" />
            <div>
              <div style={{ fontSize: 15, fontWeight: 600 }}>{report?.company} is analysed</div>
              <div style={{ fontSize: 13, color: "var(--text-3)" }}>
                Scored {Math.round(report!.final_score)}/100 &middot; {report!.recommendation}
              </div>
            </div>
            <Magnetic>
              <button
                className="up-run"
                style={{ width: "auto", marginLeft: "auto" }}
                onClick={() => navigate("/analysis")}
                data-cursor="Open"
              >
                Open the report <ArrowRight size={16} />
              </button>
            </Magnetic>
          </div>
        )}
      </div>

      {outOfScope && (
        <OutOfScopeDialog
          scopeCheck={outOfScope}
          companyName={companyInput}
          onDismiss={() => { dismissOutOfScope(); clearFile(); }}
        />
      )}
    </div>
  );
};

export default UploadDeck;
