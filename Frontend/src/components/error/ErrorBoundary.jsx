import { Component } from 'react';
import ServerErrorPage from './ServerErrorPage';

/**
 * Catches unexpected RENDERING errors anywhere below it and shows the 500 page instead of React's
 * blank white screen. A class component because that is still the only way to implement
 * componentDidCatch - there is no hook equivalent.
 *
 * Scope note: this covers render/lifecycle errors only. It deliberately does NOT catch API
 * errors - those are handled where they happen (toasts for validation/permission failures, the
 * 500 page only for genuine server faults), because turning every 4xx into a full-page error
 * would be wrong and would throw away the specific message the user needs.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError() {
    return { hasError: true };
  }

  componentDidCatch(error, info) {
    // Logged for developers via the browser console only - never rendered to the user, so no
    // stack trace or internal detail can leak into the UI.
    if (import.meta.env.DEV) {
      console.error('Unhandled render error:', error, info);
    }
  }

  handleRetry = () => {
    // Clear the error and let React re-render the subtree. If whatever caused the crash is still
    // broken it throws again and we land straight back here - no loop, because this only ever
    // runs from a click.
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      return <ServerErrorPage standalone onRetry={this.handleRetry} />;
    }
    return this.props.children;
  }
}
