import { Navigate, useLocation } from "react-router-dom";
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
  const { status, accountsEnabled } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div
        style={{ minHeight: "60vh" }}
        aria-busy="true"
        aria-label="Checking your session"
      />
    );
  }

  if (!accountsEnabled) return <>{children}</>;

  if (status === "signed-out") {
    // `state.from` so the sign-in screen can return the user to where they were
    // going rather than dumping them on the dashboard.
    return <Navigate to="/signin" replace state={{ from: location.pathname }} />;
  }

  return <>{children}</>;
}
