import { Navigate, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useAuth } from "../../context/AuthContext";

/**
 * Sends signed-out visitors to the sign-in screen.
 *
 * WHY THE LOADING BRANCH MATTERS
 *
 * `status` starts as "loading" while the stored token is checked against
 * `/auth/me`. Treating that as signed-out would redirect an already-signed-in
 * user to the login page on every single page load, and then bounce them back
 * a few hundred milliseconds later. The blank hold below is short and is the
 * difference between an app that feels stable and one that flickers.
 *
 * WHEN ACCOUNTS DO NOT EXIST
 *
 * If the backend has no database it cannot have accounts, and this must not
 * lock the product behind a sign-in form nobody can complete. In that case the
 * children render: the deployment is exactly as open as it was before accounts
 * were added, which is a deliberate, stated position rather than an oversight
 * (reports created without an owner are visible to everyone -- see migration
 * 010 and `db.list_reports`).
 */
export default function RequireAuth({ children }: { children: ReactNode }) {
  const { status, accountsEnabled, retry } = useAuth();
  const location = useLocation();

  if (status === "loading") return <SessionCheckHold />;

  // The session check did not come back. Sending the reader to a sign-in form
  // here would be a lie -- their session is very likely fine and the server
  // is not answering -- and it would lose the page they were on.
  if (status === "unreachable") return <UnreachableHold onRetry={retry} />;

  if (!accountsEnabled) return <>{children}</>;

  if (status === "signed-out") {
    // `state.from` so the sign-in screen can return the user to where they were
    // going rather than dumping them on the dashboard.
    return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}


/**
 * The hold shown while `/auth/me` is in flight.
 *
 * Silent for the first couple of seconds, deliberately: the check normally
 * takes a few hundred milliseconds, and a message that appears and vanishes
 * that fast is worse than nothing.
 *
 * After that it explains itself, because the blank was actively misleading on
 * the deployed service. A free-tier host sleeps after a period of inactivity
 * and the first request then pays the wake-up cost -- measured at 52.5 seconds
 * on venture-flow-api.onrender.com. For that entire time the app rendered an
 * empty page with a "not signed in" sidebar, which reads as a broken deploy
 * rather than a cold start. Saying so is the same contract the rest of this
 * product follows: a wait the user cannot see is indistinguishable from a
 * failure.
 */
function SessionCheckHold() {
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setSlow(true), 2500);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div
      style={{ minHeight: "60vh", display: "grid", placeItems: "center", padding: 24 }}
      aria-busy="true"
      aria-label="Checking your session"
    >
      {slow && (
        <div
          role="status"
          style={{
            maxWidth: 430,
            textAlign: "center",
            color: "var(--text-secondary, #475569)",
            fontSize: 14,
            lineHeight: 1.65,
          }}
        >
          <div
            style={{
              fontFamily: "var(--font-display, inherit)",
              fontSize: 17,
              color: "var(--text-primary, #0F172A)",
              marginBottom: 6,
            }}
          >
            Waking the server
          </div>
          This deployment sleeps after a spell of inactivity, so the first request of
          the day can take up to a minute. Nothing is wrong &mdash; later requests are
          immediate.
        </div>
      )}
    </div>
  );
}


/**
 * Shown when `/auth/me` could not be reached at all.
 *
 * It says which of the two possible things happened, because they call for
 * different reactions: a sleeping free-tier host fixes itself in under a
 * minute, and a backend that is down does not. Retrying is one button rather
 * than a page reload, so the reader keeps their place.
 */
function UnreachableHold({ onRetry }: { onRetry: () => void }) {
  return (
    <div
      style={{ minHeight: "60vh", display: "grid", placeItems: "center", padding: 24 }}
      role="status"
    >
      <div style={{ maxWidth: 440, textAlign: "center" }}>
        <div
          className="vf-md"
          style={{ marginBottom: 10, color: "var(--text-primary)" }}
        >
          Cannot reach the server
        </div>
        <p style={{ fontSize: 13.5, lineHeight: 1.65, color: "var(--text-muted)", margin: "0 0 18px" }}>
          Your session is still stored on this device &mdash; this is the server not
          answering, not a sign-out. It retries automatically every few seconds.
        </p>
        <button
          type="button"
          onClick={onRetry}
          style={{
            font: "inherit", fontSize: 13.5, fontWeight: 600, cursor: "pointer",
            padding: "9px 18px", borderRadius: "var(--radius-sm)",
            border: "1px solid var(--border-strong)", background: "var(--surface)",
            color: "var(--text-primary)",
          }}
        >
          Try now
        </button>
      </div>
    </div>
  );
}
