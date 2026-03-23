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

  componentDidCatch(error: Error, info: any) {
    console.error('[ErrorBoundary]', error, info);
  }

  render() {
    if (this.state.error) {
      const _ = i18n.value;
      return (
        <div style={{ padding: '2rem', maxWidth: '40rem' }}>
          <h2 style={{ fontFamily: 'var(--mono)', fontSize: '1rem', marginBottom: '0.5rem', color: 'var(--red)' }}>
            {_['error-boundary-title']}
          </h2>
          <pre style={{
            fontFamily: 'var(--mono)', fontSize: '0.8125rem', color: 'var(--fg-2)',
            whiteSpace: 'pre-wrap', wordBreak: 'break-word',
          }}>
            {this.state.error.message}
          </pre>
          <button
            style={{
              marginTop: '1rem', padding: '0.5rem 1rem',
              fontFamily: 'var(--mono)', fontSize: '0.8125rem',
              border: '1px solid var(--border)', background: 'var(--bg-1)',
              color: 'var(--fg-0)', cursor: 'pointer',
            }}
            onClick={() => this.setState({ error: null })}
          >
            {_['error-boundary-retry']}
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
