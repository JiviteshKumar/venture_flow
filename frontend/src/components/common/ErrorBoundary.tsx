import { Component, type ErrorInfo, type ReactNode } from "react";

type Props = { children: ReactNode };
type State = { hasError: boolean };

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Keep diagnostics local; do not expose application details to end users.
    console.error("Unhandled UI error", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <main role="alert" style={{ maxWidth: 640, margin: "10vh auto", padding: 24, fontFamily: "system-ui" }}>
          <h1>Something went wrong</h1>
          <p>VentureFlow could not render this page. Reload to try again.</p>
          <button onClick={() => window.location.reload()}>Reload VentureFlow</button>
        </main>
      );
    }
    return this.props.children;
  }
}
