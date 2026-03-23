import { Component } from 'preact';
import type { ComponentChildren } from 'preact';
import { i18n } from '../store/ui';

interface Props { children: ComponentChildren; }
interface State { error: Error | null; }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(_error: Error, _info: { componentStack?: string }) {
    // Error already captured in state via getDerivedStateFromError
  }

  render() {
    if (this.state.error) {
      const _ = i18n.value;
      return (
        <div class="error-boundary">
          <h2 class="error-boundary-title">{_['error-boundary-title']}</h2>
          <pre class="error-boundary-detail">{this.state.error.message}</pre>
          <button class="btn btn-ghost btn-sm" onClick={() => this.setState({ error: null })}>
            {_['error-boundary-retry']}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
