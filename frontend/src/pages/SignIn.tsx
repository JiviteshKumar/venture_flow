import { useEffect, useMemo, useRef, useState } from "react";
import { motion, useReducedMotion } from "framer-motion";
import { useLocation, useNavigate } from "react-router-dom";
import { ArrowRight, Check, Eye, EyeOff, Loader2, Mail, ShieldCheck } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { DURATION, EASE_OUT, FadeIn } from "../components/ui/Motion";

/**
 * One screen for both signing in and signing up.
 *
 * WHY ONE SCREEN AND NOT TWO ROUTES
 *
 * The two forms differ by one field and one button label. As separate pages
 * they duplicate the layout, the validation and the error handling, and the
 * user loses whatever they typed when they realise they are on the wrong one.
 * Here the mode is state, the email survives the switch, and the transition is
 * a 200ms crossfade rather than a page load.
 *
 * WHAT IT IS HONEST ABOUT
 *
 * This deployment has no email provider, so there is no verification email and
 * no password reset. That is stated on the form, next to the field it affects,
 * rather than discovered later by someone locked out of their own account.
 */

type Mode = "signin" | "signup";

export default function SignIn() {
  const navigate = useNavigate();
  const location = useLocation();
  const reduced = useReducedMotion();
  const { signIn, signUp, status, accountsEnabled, emailNote, passwordMinLength } = useAuth();

  const [mode, setMode] = useState<Mode>(
    new URLSearchParams(location.search).get("mode") === "signup" ? "signup" : "signin",
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  // A submit that takes 50 seconds is a cold start, not a hang -- say so
  // rather than spinning silently. Same threshold reasoning as RequireAuth:
  // silent while the request is merely normal-slow.
  const [slowSubmit, setSlowSubmit] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!busy) {
      setSlowSubmit(false);
      return;
    }
    const timer = window.setTimeout(() => setSlowSubmit(true), 3000);
    return () => window.clearTimeout(timer);
  }, [busy]);
  const emailRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (status === "signed-in") navigate("/", { replace: true });
  }, [status, navigate]);

  useEffect(() => {
    emailRef.current?.focus();
  }, []);

  // Live, non-blocking. The rule is shown as progress rather than as a
  // rejection after submitting, which is the difference between a form that
  // helps and a form that scolds.
  const passwordLongEnough = password.length >= passwordMinLength;
  const emailLooksValid = useMemo(
    () => /^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$/.test(email.trim()),
    [email],
  );
  const canSubmit =
    emailLooksValid && (mode === "signin" ? password.length > 0 : passwordLongEnough) && !busy;

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    setBusy(true);
    setError(null);
    try {
      if (mode === "signin") await signIn(email.trim(), password);
      else await signUp(email.trim(), password, displayName.trim());
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  };

  const switchMode = (next: Mode) => {
    setMode(next);
    setError(null);
    setPassword("");
  };

  return (
    <div className="si-root">
      <style>{`
        .si-root {
          min-height: 100vh;
          display: grid;
          grid-template-columns: 1.05fr 1fr;
          background: var(--bg);
          color: var(--text-primary);
          font-family: var(--font-sans);
        }
        .si-aside {
          position: relative;
          overflow: hidden;
          padding: 56px 52px;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          background:
            radial-gradient(120% 120% at 0% 0%, #14315F 0%, #0B1120 55%, #070B14 100%);
          color: #E8EEF9;
        }
        /* A slow, very low-contrast drift. It is the only looping animation in
           the app and it lives here because a sign-in screen is the one place
           nobody is reading carefully. It is disabled under reduced motion. */
        .si-aura {
          position: absolute; inset: -30%;
          background:
            radial-gradient(40% 40% at 30% 30%, rgba(29,111,232,0.35), transparent 70%),
            radial-gradient(35% 35% at 70% 65%, rgba(14,166,106,0.22), transparent 70%);
          filter: blur(50px);
          animation: si-drift 24s ease-in-out infinite alternate;
        }
        @keyframes si-drift {
          from { transform: translate3d(-3%, -2%, 0) scale(1); }
          to   { transform: translate3d(4%, 3%, 0) scale(1.08); }
        }
        @media (prefers-reduced-motion: reduce) {
          .si-aura { animation: none; }
        }

        .si-aside-inner { position: relative; z-index: 1; }
        .si-wordmark {
          font-family: var(--font-mono); font-size: 11px; letter-spacing: 0.22em;
          text-transform: uppercase; color: rgba(232,238,249,0.65);
        }
        .si-headline {
          font-family: var(--font-display);
          font-size: clamp(34px, 3.4vw, 52px);
          line-height: 1.08; letter-spacing: -0.02em;
          margin: 22px 0 16px; color: #FFFFFF;
        }
        .si-sub { font-size: 15px; line-height: 1.7; color: rgba(232,238,249,0.78); max-width: 42ch; }
        .si-points { position: relative; z-index: 1; display: grid; gap: 14px; margin-top: 36px; }
        .si-point { display: flex; gap: 11px; align-items: flex-start; font-size: 13.5px;
                    line-height: 1.6; color: rgba(232,238,249,0.85); }
        .si-point svg { flex-shrink: 0; margin-top: 2px; color: #6FE3AC; }

        .si-form-wrap {
          display: flex; align-items: center; justify-content: center;
          padding: 44px 32px;
        }
        .si-card { width: 100%; max-width: 396px; }

        .si-title {
          font-family: var(--font-display); font-size: 32px; line-height: 1.15;
          letter-spacing: -0.015em; margin: 0 0 8px; color: var(--text-primary);
        }
        .si-lede { font-size: 14px; color: var(--text-muted); margin: 0 0 26px; line-height: 1.6; }

        .si-label {
          display: block; font-family: var(--font-mono); font-size: 10px;
          letter-spacing: 0.11em; text-transform: uppercase; font-weight: 600;
          color: var(--text-muted); margin-bottom: 7px;
        }
        .si-field { position: relative; margin-bottom: 16px; }
        .si-input {
          width: 100%; box-sizing: border-box;
          padding: 12px 14px; font-size: 14.5px; font-family: var(--font-sans);
          color: var(--text-primary); background: var(--surface);
          border: 1px solid var(--border-strong); border-radius: 9px;
          transition: border-color var(--dur-fast) var(--ease-out),
                      box-shadow var(--dur-fast) var(--ease-out);
        }
        .si-input::placeholder { color: var(--text-faint); }
        .si-input:focus {
          outline: none;
          border-color: var(--accent);
          box-shadow: 0 0 0 3px rgba(29,111,232,0.14);
        }
        .si-input-pw { padding-right: 44px; }
        .si-eye {
          position: absolute; right: 6px; bottom: 5px;
          width: 34px; height: 34px; display: flex; align-items: center;
          justify-content: center; border: 0; background: transparent;
          color: var(--text-muted); cursor: pointer; border-radius: 7px;
        }
        .si-eye:hover { background: var(--surface-2); color: var(--text-primary); }

        .si-hint {
          display: flex; align-items: center; gap: 6px;
          font-size: 11.5px; margin-top: 7px; color: var(--text-muted);
        }
        .si-hint-ok { color: var(--positive); }

        .si-submit {
          width: 100%; margin-top: 8px; padding: 13px 18px;
          font-family: var(--font-sans); font-size: 14.5px; font-weight: 600;
          color: #fff; background: var(--accent);
          border: 0; border-radius: 9px; cursor: pointer;
          display: flex; align-items: center; justify-content: center; gap: 9px;
          transition: background var(--dur-fast) var(--ease-out),
                      transform var(--dur-fast) var(--ease-out),
                      box-shadow var(--dur-base) var(--ease-out);
        }
        .si-submit:hover:not(:disabled) {
          background: #1660CE; box-shadow: var(--shadow-glow); transform: translateY(-1px);
        }
        .si-submit:active:not(:disabled) { transform: translateY(0); }
        .si-submit:disabled { opacity: 0.5; cursor: not-allowed; }

        .si-switch {
          margin-top: 22px; font-size: 13.5px; color: var(--text-muted); text-align: center;
        }
        .si-switch button {
          border: 0; background: transparent; color: var(--accent);
          font-weight: 600; font-size: 13.5px; cursor: pointer; padding: 2px 4px;
          font-family: var(--font-sans); border-radius: 5px;
        }
        .si-switch button:hover { text-decoration: underline; }

        .si-error {
          display: flex; gap: 9px; align-items: flex-start;
          background: rgba(217,48,37,0.07); border: 1px solid rgba(217,48,37,0.28);
          color: #A81E15; border-radius: 9px; padding: 11px 13px;
          font-size: 13px; line-height: 1.55; margin-bottom: 16px;
        }
        .si-note {
          margin-top: 20px; padding: 11px 13px; border-radius: 9px;
          background: var(--surface-2); border: 1px solid var(--border);
          font-size: 11.5px; line-height: 1.6; color: var(--text-muted);
        }
        .si-spin { animation: si-rotate 0.9s linear infinite; }
        @keyframes si-rotate { to { transform: rotate(360deg); } }

        /* LAST in the block, deliberately.
           These rules were originally written next to .si-root, above the
           .si-aside block. At equal specificity the later rule wins, so the
           display:flex on .si-aside overrode the display:none here, and the
           editorial panel kept rendering at every width -- pushing the actual
           form below the fold on a narrow screen, which is precisely what the
           query exists to prevent. Media queries carry no extra specificity;
           only their position saves them. */
        @media (max-width: 900px) {
          .si-root { grid-template-columns: 1fr; }
          .si-aside { display: none; }
          .si-form-wrap { padding: 32px 22px; }
        }
      `}</style>

      <aside className="si-aside">
        <div className="si-aura" aria-hidden="true" />
        <div className="si-aside-inner">
          <div className="si-wordmark">VentureFlow</div>
          <h1 className="si-headline">
            Diligence that shows
            <br />
            its working.
          </h1>
          <p className="si-sub">
            Upload a deck. Every claim is checked against live sources, every
            figure is traced to the slide it came from, and anything the tool
            could not establish is said out loud rather than filled in.
          </p>
        </div>

        {/* Deliberately not marketing numbers. Each line is a property of the
            product that is actually true and testable. */}
        <div className="si-points">
          {[
            "Claims verified against real sources, with the evidence shown",
            "Scores stated with their confidence interval and base rate",
            "Extraction coverage reported, so silence is never mistaken for absence",
          ].map((point) => (
            <div className="si-point" key={point}>
              <Check size={15} />
              <span>{point}</span>
            </div>
          ))}
        </div>
      </aside>

      <div className="si-form-wrap">
        <FadeIn className="si-card" y={14}>
          {/* Keyed on `mode` with no AnimatePresence, deliberately.
              The first version wrapped this in <AnimatePresence mode="wait">
              so the old heading could animate out before the new one animated
              in. It left a stale child: switching to sign-up updated the button
              and revealed the name field while the heading still read "Welcome
              back" -- the exiting node was never replaced. Changing the key
              remounts the element, which plays initial -> animate on its own
              and cannot get stuck holding a child that has already left. Two
              lines of text do not need a coordinated exit. */}
          <motion.div
            key={mode}
            initial={reduced ? { opacity: 0 } : { opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: DURATION.base, ease: EASE_OUT }}
          >
            <h2 className="si-title">
              {mode === "signin" ? "Welcome back" : "Create your account"}
            </h2>
            <p className="si-lede">
              {mode === "signin"
                ? "Sign in to reach your saved analyses."
                : "Your analyses stay yours — reports are scoped to your account."}
            </p>
          </motion.div>

          {!accountsEnabled && (
            <div className="si-error" role="alert">
              <span>
                This deployment has no database configured, so accounts are
                unavailable. The rest of the product still works without one.
              </span>
            </div>
          )}

          {/* Same reasoning as the name field above: an alert that lingers
              at opacity 0 is still announced by a screen reader. */}
          {error && (
            <motion.div
              key="auth-error"
              className="si-error"
              role="alert"
              initial={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              transition={{ duration: DURATION.fast, ease: EASE_OUT }}
              style={{ overflow: "hidden" }}
            >
              <span>{error}</span>
            </motion.div>
          )}

          <form onSubmit={submit} noValidate>
            {/* Conditionally rendered, with an entry animation only.
                This was an <AnimatePresence> wrapper so the field could
                collapse on the way out. It did not unmount: the exit ran to
                height 0 and left a real, focusable text input inside a
                zero-height clipped container -- invisible to a sighted user,
                and Tab landed straight in it. Adding the key AnimatePresence
                needs did not fix it either.
                A ghost form control is a worse defect than a missing exit
                animation, so the field now simply unmounts. It still animates
                in, which is the half a user actually notices. */}
            {mode === "signup" && (
              <motion.div
                key="display-name-field"
                initial={reduced ? { opacity: 0 } : { opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                transition={{ duration: DURATION.base, ease: EASE_OUT }}
                style={{ overflow: "hidden" }}
              >
                <div className="si-field">
                  <label className="si-label" htmlFor="si-name">Your name (optional)</label>
                  <input
                    id="si-name"
                    className="si-input"
                    value={displayName}
                    onChange={(e) => setDisplayName(e.target.value)}
                    placeholder="Ada Lovelace"
                    autoComplete="name"
                    maxLength={80}
                  />
                </div>
              </motion.div>
            )}

            <div className="si-field">
              <label className="si-label" htmlFor="si-email">Email</label>
              <input
                ref={emailRef}
                id="si-email"
                className="si-input"
                type="email"
                inputMode="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@fund.com"
                autoComplete="email"
                maxLength={254}
                aria-invalid={email.length > 0 && !emailLooksValid}
              />
            </div>

            <div className="si-field">
              <label className="si-label" htmlFor="si-password">Password</label>
              <input
                id="si-password"
                className="si-input si-input-pw"
                type={showPassword ? "text" : "password"}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={mode === "signup" ? `At least ${passwordMinLength} characters` : "Your password"}
                autoComplete={mode === "signup" ? "new-password" : "current-password"}
                maxLength={1024}
              />
              <button
                type="button"
                className="si-eye"
                onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>

              {/* Shown only while signing up. During sign-in the rule is
                  irrelevant -- the password either matches or it does not, and
                  telling someone their existing password is too short would be
                  both wrong and alarming. */}
              {mode === "signup" && password.length > 0 && (
                <div className={`si-hint ${passwordLongEnough ? "si-hint-ok" : ""}`}>
                  {passwordLongEnough ? <Check size={13} /> : <ShieldCheck size={13} />}
                  <span>
                    {passwordLongEnough
                      ? "Long enough."
                      : `${passwordMinLength - password.length} more character${
                          passwordMinLength - password.length === 1 ? "" : "s"
                        }. Length beats punctuation.`}
                  </span>
                </div>
              )}
            </div>

            <button className="si-submit" type="submit" disabled={!canSubmit}>
              {busy ? (
                <>
                  <Loader2 size={16} className="si-spin" />
                  {mode === "signin" ? "Signing in…" : "Creating your account…"}
                </>
              ) : (
                <>
                  {mode === "signin" ? "Sign in" : "Create account"}
                  <ArrowRight size={16} />
                </>
              )}
            </button>

            {slowSubmit && (
              <div className="si-hint" role="status">
                <span>
                  Waking the server &mdash; the first request after a quiet spell can
                  take up to a minute.
                </span>
              </div>
            )}
          </form>

          <div className="si-switch">
            {mode === "signin" ? (
              <>
                No account yet?{" "}
                <button type="button" onClick={() => switchMode("signup")}>Create one</button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button type="button" onClick={() => switchMode("signin")}>Sign in</button>
              </>
            )}
          </div>

          {/* Said here, on the form, rather than discovered later by someone
              locked out of their own account. */}
          {emailNote && (
            <p className="si-note">
              <Mail size={12} style={{ verticalAlign: "-2px", marginRight: 6 }} />
              {emailNote}
            </p>
          )}
        </FadeIn>
      </div>
    </div>
  );
}
