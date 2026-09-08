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

export type AuthStatus = "loading" | "signed-in" | "signed-out";

interface AuthContextValue {
  status: AuthStatus;
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
  const [status, setStatus] = useState<AuthStatus>("loading");
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
      // An unreachable backend is not a signed-in state. It is also not a
      // reason to wipe a stored token: the session may be perfectly valid and
      // the API merely down, so the token stays and this retries on reload.
      setUser(null);
      setStatus("signed-out");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

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
    signIn, signUp, signOut,
  }), [status, user, accountsEnabled, emailNote, passwordMinLength,
       signIn, signUp, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
