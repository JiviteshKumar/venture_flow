import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { hasError: boolean; error: Error | null; componentStack: string };

/**
 * Catches render crashes and — importantly — says what broke.
 *
 * The previous version rendered "Something went wrong. Reload to try again."
 * and nothing else, on the reasoning that application details should not be
 * exposed to end users. That is a sound instinct for a public multi-tenant
 * product and the wrong trade here: this is a single-operator internal tool,
 * the "user" is the person who can actually fix it, and a bare reload prompt
 * gave them nothing to act on and nothing to report. It is the same failure
 * shape as the backend swallowing job errors into a fixed string.
 *
 * The error and component stack are now shown in a collapsed block, with a
 * copy button, so a crash can be reported precisely instead of described as
 * "it broke when I clicked around".
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null, componentStack: "" };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info);
    this.setState({ error, componentStack: info.componentStack ?? "" });
  }

  private details(): string {
    const { error, componentStack } = this.state;
    return [
      `${error?.name ?? "Error"}: ${error?.message ?? "unknown"}`,
      "",
      error?.stack ?? "(no stack)",
      "",
      "Component stack:",
      componentStack || "(none)",
      "",
      `URL: ${window.location.href}`,
    ].join("\n");
  }

  render() {
    if (!this.state.hasError) return this.props.children;

    return (
      <main
        role="alert"
        style={{ maxWidth: 760, margin: "8vh auto", padding: 24, fontFamily: "system-ui", color: "#0B1120" }}
      >
        <h1 style={{ fontSize: 22, margin: "0 0 6px" }}>Something went wrong</h1>
        <p style={{ margin: "0 0 4px", color: "#667085" }}>
          VentureFlow could not render this page. The error is below — reloading usually recovers,
          but the details are what make it fixable.
        </p>
        <p style={{ margin: "0 0 16px", fontFamily: "ui-monospace, monospace", fontSize: 13, color: "#B42318" }}>
          {this.state.error?.name}: {this.state.error?.message}
        </p>

        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          <button
            onClick={() => window.location.reload()}
            style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid #D0D5DD", background: "#1D6FE8", color: "#fff", cursor: "pointer" }}
          >
            Reload VentureFlow
          </button>
          <button
            onClick={() => void navigator.clipboard?.writeText(this.details())}
            style={{ padding: "8px 14px", borderRadius: 8, border: "1px solid #D0D5DD", background: "#fff", cursor: "pointer" }}
          >
            Copy error details
          </button>
        </div>

        <details>
          <summary style={{ cursor: "pointer", fontSize: 13, color: "#667085" }}>
            Technical details
          </summary>
          <pre
            style={{
              marginTop: 10, padding: 12, background: "#F2F4F7", border: "1px solid #E4E7EC",
              borderRadius: 8, fontSize: 11.5, lineHeight: 1.5, overflowX: "auto", whiteSpace: "pre-wrap",
            }}
          >
            {this.details()}
          </pre>
        </details>
      </main>
    );
  }
}
