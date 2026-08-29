import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

/**
 * Per-tool error boundary: one malformed or hostile tool payload must never
 * break the whole message. On failure the card collapses to a small notice.
 */
export class ToolErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return <div className="tool-error">This tool could not be displayed.</div>;
    }
    return this.props.children;
  }
}