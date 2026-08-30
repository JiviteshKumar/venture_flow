import { useEffect, useRef, useState } from "react";
import { api, demoToken } from "../../services/apiClient";

/**
 * Passphrase prompt for the gated demo deployment.
 *
 * Deliberately not a login screen, and worded so nobody mistakes it for one.
 * There is no user model behind this and no per-account data isolation: every
 * report still lives in one shared pool, and anyone holding the passphrase sees
 * all of it. What it stops is an anonymous passer-by reading that pool, which
 * the deployed API previously allowed over sequential integer report ids.
 *
 * It renders only when the backend has actually answered 401. A local run with
 * no DEMO_ACCESS_TOKEN set never sees this at all, so development is unchanged.
 */
export default function DemoGate({ children }: { children: React.ReactNode }) {
  const [locked, setLocked] = useState(false);
  const [value, setValue] = useState("");
  const [checking, setChecking] = useState(false);
  const [failed, setFailed] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => { inputRef.current?.focus(); }, []);

  useEffect(() => {
    const onGate = () => { setLocked(true); setFailed(false); };
    window.addEventListener("vf:gate-required", onGate);
    return () => window.removeEventListener("vf:gate-required", onGate);
  }, []);

  // Probe once on mount so a gated deployment asks immediately, rather than
  // letting the user pick a file and only then discovering they cannot proceed.
  useEffect(() => {
    let cancelled = false;
    api.listReports()
      .then(() => { if (!cancelled) setLocked(false); })
      .catch((e) => { if (!cancelled && e?.response?.status === 401) setLocked(true); });
    return () => { cancelled = true; };
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!value.trim() || checking) return;
    setChecking(true);
    setFailed(false);
    demoToken.set(value.trim());
    try {
      await api.listReports();
      setLocked(false);
      setValue("");
    } catch (err: unknown) {
      // The interceptor clears a rejected passphrase; surface it plainly.
      if ((err as { response?: { status?: number } })?.response?.status === 401) setFailed(true);
      else setFailed(true);
    } finally {
      setChecking(false);
    }
  };

  if (!locked) return <>{children}</>;

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999, display: "flex",
      alignItems: "center", justifyContent: "center", background: "#F7F8FA",
      fontFamily: "system-ui, -apple-system, sans-serif",
    }}>
      <form onSubmit={submit} style={{
        width: "min(420px, 92vw)", background: "#fff", padding: "28px 30px",
        borderRadius: 14, border: "1px solid rgba(15,23,42,0.09)",
        boxShadow: "0 10px 40px rgba(15,23,42,0.08)",
      }}>
        <div style={{
          fontFamily: "'IBM Plex Mono', monospace", fontSize: 9.5, letterSpacing: "0.14em",
          textTransform: "uppercase", color: "#5D6B7F", marginBottom: 10,
        }}>Private demo</div>

        <h1 style={{ fontSize: 20, margin: "0 0 8px", color: "#0B1120", letterSpacing: "-0.01em" }}>
          Enter the access passphrase
        </h1>
        <p style={{ fontSize: 13, lineHeight: 1.65, color: "#4A5568", margin: "0 0 18px" }}>
          This deployment is shared, not per-account: everyone with the
          passphrase sees the same set of analysed decks. Don&rsquo;t upload
          anything genuinely confidential.
        </p>

        <input
          /* Focused on mount via the ref below rather than with `autoFocus`.
             This screen is a modal gate whose only control is this field, so
             moving focus here is correct -- but `autoFocus` also fires when
             the component is re-mounted mid-session, which yanks focus away
             from wherever the user actually was. */
          ref={inputRef}
          type="password"
          value={value}
          onChange={(e) => { setValue(e.target.value); setFailed(false); }}
          placeholder="Passphrase"
          disabled={checking}
          style={{
            width: "100%", padding: "11px 13px", fontSize: 14, borderRadius: 9,
            border: `1px solid ${failed ? "#D93025" : "rgba(15,23,42,0.14)"}`,
            outline: "none", boxSizing: "border-box", marginBottom: 10,
          }}
        />

        {failed && (
          <div style={{ color: "#D93025", fontSize: 12.5, marginBottom: 10 }}>
            That passphrase was not accepted.
          </div>
        )}

        <button
          type="submit"
          disabled={!value.trim() || checking}
          style={{
            width: "100%", padding: "11px 0", fontSize: 14, fontWeight: 600,
            borderRadius: 9, border: "none", cursor: value.trim() && !checking ? "pointer" : "default",
            background: value.trim() && !checking ? "#1D6FE8" : "#CBD5E1", color: "#fff",
          }}
        >
          {checking ? "Checking…" : "Continue"}
        </button>
      </form>
    </div>
  );
}
