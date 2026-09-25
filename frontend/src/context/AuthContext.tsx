import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode,
} from "react";
import { api, parseApiError, sessionToken, type AuthUser } from "../services/apiClient";

/**
 * Who is signed in.
 *
 * Kept separate from AppContext on purpose. AppContext holds the current
 * analysis -- an upload, a report, a progress percentage -- all of which is
 * scratch state for one piece of work. Identity outlives every one of those and
 * has a different lifecycle: it survives a `reset()`, it is restored from
 * storage on boot, and it must be resolved before the first protected render.
 * Folding the two together would mean clearing a session whenever a user
 * started a new analysis.
 *
 * `status` distinguishes three states the UI has to render differently:
 *
 *   "loading"  the token in storage has not been checked yet. Rendering a
 *              sign-in form here would flash it at an already-signed-in user
 *              on every page load.
 *   "signed-in"/"signed-out"  resolved.
 *
 * `accountsEnabled` is false when the backend has no database, which is a
 * different sentence on screen from "you are signed out": one asks the user to
 * sign in, the other tells them the deployment cannot have accounts at all.
 */

/**
 * "unreachable" is the state this used to be missing, and its absence was a
 * bug with teeth: every failure of `/auth/me` -- a 429 from the rate limiter,
 * a 500, a dropped database connection, a timeout on a sleeping host -- was
 * recorded as "signed-out", and RequireAuth duly redirected to the sign-in
 * screen. A user with a perfectly valid session was thrown out of the report
 * they were reading because one request lost a race. The token was kept, so
 * reloading fixed it, which is exactly what makes the bug hard to report.
 *
 * Now: no token means signed-out, a rejected token means signed-out, and a
 * request that never got an answer means unreachable -- which keeps the user
 * where they are and retries.
 */
export type AuthStatus = "loading" | "signed-in" | "signed-out" | "unreachable";

interface AuthContextValue {
  status: AuthStatus;
  /** Re-run the session check, for the retry on the unreachable hold. */
  retry: () => void;
  user: AuthUser | null;
  accountsEnabled: boolean;
  emailNote: string;
  passwordMinLength: number;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string, displayName?: string) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  // A visitor with no stored session is signed out, and we know that without
  // asking the server. The "loading" hold exists only to stop a sign-in form
  // flashing at someone who IS signed in, which cannot happen when there is no
  // token to restore.
  //
  // Holding regardless cost a full minute on the deployed service: a sleeping
  // free-tier instance takes ~50s to answer /auth/me (measured at 52.5s), so
  // opening the link showed an empty app shell with a "not signed in" sidebar
  // for that whole time instead of the sign-in screen. The check still runs
  // underneath -- it is what tells us whether accounts exist at all.
  const [status, setStatus] = useState<AuthStatus>(
    () => (sessionToken.get() ? "loading" : "signed-out"),
  );
  const [user, setUser] = useState<AuthUser | null>(null);
  const [accountsEnabled, setAccountsEnabled] = useState(true);
  const [emailNote, setEmailNote] = useState("");
  const [passwordMinLength, setPasswordMinLength] = useState(10);

  const refresh = useCallback(async () => {
    try {
      const who = await api.whoAmI();
      setUser(who.user);
      setAccountsEnabled(who.accounts_enabled);
      setEmailNote(who.email_verification_note || "");
      setPasswordMinLength(who.password_min_length || 10);
      setStatus(who.user ? "signed-in" : "signed-out");
    } catch {
      // The request did not come back. That is not the same as being signed
      // out, and it must not be rendered as one: the token stays, the user
      // stays where they are, and this retries.
      setUser(null);
      setStatus(sessionToken.get() ? "unreachable" : "signed-out");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Two automatic retries, then the hold asks the reader to try. A backend
  // that has gone to sleep answers within a minute; one that is genuinely down
  // should stop being polled rather than be hammered by every open tab.
  useEffect(() => {
    if (status !== "unreachable") return;
    const timer = window.setTimeout(() => { void refresh(); }, 4000);
    return () => window.clearTimeout(timer);
  }, [status, refresh]);

  // The server rejected this session -- expired, revoked, or the production
  // sign-in gate. Clear local state so RequireAuth sends the user to sign in,
  // rather than leaving them on a page whose every request now fails.
  useEffect(() => {
    const onSignedOut = () => {
      setUser(null);
      setStatus("signed-out");
    };
    window.addEventListener("vf:signin-required", onSignedOut);
    return () => window.removeEventListener("vf:signin-required", onSignedOut);
  }, []);

  const retry = useCallback(() => { void refresh(); }, [refresh]);

  const signIn = useCallback(async (email: string, password: string) => {
    try {
      const session = await api.login(email, password);
      setUser(session.user);
      setStatus("signed-in");
    } catch (err) {
      // parseApiError narrows FastAPI's `detail`, which is a string here and an
      // object for the out-of-scope refusal. Passing the raw value to JSX is
      // what turns a wrong password into a blank screen.
      throw new Error(parseApiError(err, "Could not sign in. Is the API running?").message);
    }
  }, []);

  const signUp = useCallback(async (email: string, password: string, displayName = "") => {
    try {
      const session = await api.register(email, password, displayName);
      setUser(session.user);
      setStatus("signed-in");
    } catch (err) {
      throw new Error(parseApiError(err, "Could not create the account.").message);
    }
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } finally {
      // Local state clears even if the network call failed, so the UI never
      // shows someone as signed in after they asked not to be.
      sessionToken.clear();
      setUser(null);
      setStatus("signed-out");
    }
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    status, user, accountsEnabled, emailNote, passwordMinLength,
    retry, signIn, signUp, signOut,
  }), [status, user, accountsEnabled, emailNote, passwordMinLength,
       retry, signIn, signUp, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
