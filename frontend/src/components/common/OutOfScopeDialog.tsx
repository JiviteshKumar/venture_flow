import { useEffect, useRef } from "react";
import type { ScopeCheck } from "../../services/apiClient";

/**
 * Shown when the backend refuses a deck because the company is not a
 * technology startup.
 *
 * WHY A DIALOG AND NOT THE RED ERROR LINE
 *
 * Every other error on this screen is something to retry: a network failure, a
 * file that would not parse, a rate limit. This one is not. There is no retry
 * that helps, and the user needs to understand a product decision rather than
 * fix a fault -- so it gets an explanation with the evidence behind it, not a
 * one-line "⚠ 422".
 *
 * WHAT IT SHOWS, AND WHY THE EVIDENCE IS IN IT
 *
 * The classifier can be wrong, and the honest thing is to let the user see what
 * it decided on. The reason is quoted from the deck's own words, the matched
 * industry terms are listed, and the confidence is shown. A founder whose
 * genuine tech company is refused can see immediately that it keyed on the word
 * "clinic", which is far more useful than being told the answer with no
 * working.
 *
 * ACCESSIBILITY
 *
 * Focus moves to the dialog on open and returns to the trigger on close; Escape
 * dismisses; the backdrop is inert to clicks so a mis-click cannot dismiss an
 * explanation the user has not read yet.
 */
export function OutOfScopeDialog({
  scopeCheck,
  companyName,
  onDismiss,
}: {
  scopeCheck: ScopeCheck;
  companyName?: string;
  onDismiss: () => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const previouslyFocused = useRef<Element | null>(null);

  useEffect(() => {
    previouslyFocused.current = document.activeElement;
    closeRef.current?.focus();

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onDismiss();
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      (previouslyFocused.current as HTMLElement | null)?.focus?.();
    };
  }, [onDismiss]);

  const signals = scopeCheck.non_tech_signals || [];

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
        background: "rgba(11,17,32,0.55)",
      }}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="scope-title"
        aria-describedby="scope-body"
        style={{
          background: "var(--surface)",
          border: "1px solid var(--border-strong)",
          borderRadius: 12,
          boxShadow: "var(--shadow-panel)",
          maxWidth: 560,
          width: "100%",
          maxHeight: "85vh",
          overflowY: "auto",
          padding: "26px 28px 22px",
        }}
      >
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--caution)",
            fontWeight: 600,
            marginBottom: 10,
          }}
        >
          Outside VentureFlow's scope
        </div>

        <h2
          id="scope-title"
          style={{
            fontFamily: "var(--font-display)",
            fontSize: 24,
            lineHeight: 1.25,
            color: "var(--text-primary)",
            margin: "0 0 12px",
          }}
        >
          {companyName ? `${companyName} does not look like a technology startup.` : "This does not look like a technology startup."}
        </h2>

        <div id="scope-body" style={{ fontSize: 14, lineHeight: 1.65, color: "var(--text-secondary)" }}>
          <p style={{ margin: "0 0 14px" }}>{scopeCheck.scope_statement}</p>

          <div
            style={{
              background: "var(--surface-2)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: "12px 14px",
              margin: "0 0 14px",
            }}
          >
            <div
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 9.5,
                letterSpacing: "0.08em",
                textTransform: "uppercase",
                color: "var(--text-muted)",
                fontWeight: 600,
                marginBottom: 6,
              }}
            >
              What this was decided on
            </div>
            <p style={{ margin: 0, color: "var(--text-primary)" }}>{scopeCheck.reason}</p>

            {signals.length > 0 && (
              <div style={{ marginTop: 10, display: "flex", flexWrap: "wrap", gap: 6 }}>
                {signals.map((signal) => (
                  <span
                    key={signal}
                    style={{
                      fontFamily: "var(--font-mono)",
                      fontSize: 11,
                      padding: "2px 8px",
                      borderRadius: 999,
                      background: "rgba(196,122,10,0.10)",
                      border: "1px solid rgba(196,122,10,0.25)",
                      color: "var(--caution)",
                    }}
                  >
                    {signal}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Shown because the classifier is not infallible and the user is
              entitled to know how sure it was and what decided it. */}
          <p style={{ margin: "0 0 16px", fontSize: 12.5, color: "var(--text-muted)" }}>
            Confidence {Math.round((scopeCheck.confidence || 0) * 100)}%
            {scopeCheck.sector ? ` · classified as ${scopeCheck.sector}` : ""}
            {scopeCheck.method ? ` · decided by ${scopeCheck.method.replace(/_/g, " ")}` : ""}.
            {" "}If this is wrong, the deck may not describe the product clearly enough
            for the classifier — adding what the software actually does usually
            resolves it.
          </p>
        </div>

        <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
          <button
            ref={closeRef}
            type="button"
            onClick={onDismiss}
            style={{
              fontFamily: "var(--font-sans)",
              fontSize: 13,
              fontWeight: 600,
              padding: "9px 18px",
              borderRadius: 8,
              border: "1px solid var(--border-strong)",
              background: "var(--accent)",
              color: "#FFFFFF",
              cursor: "pointer",
            }}
          >
            Try a different deck
          </button>
        </div>
      </div>
    </div>
  );
}

export default OutOfScopeDialog;
