import { Component, type ReactNode } from "react";
import { StaticGradient } from "./StaticGradient";

export class BackgroundBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    return this.state.failed ? <StaticGradient /> : this.props.children;
  }
}
