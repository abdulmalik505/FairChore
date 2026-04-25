import React from 'react';

export default class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { err: null };
  }

  static getDerivedStateFromError(err) {
    return { err };
  }

  componentDidCatch(err, info) {
    console.error('FairChore crashed:', err, info);
  }

  handleReload = () => {
    this.setState({ err: null });
    window.location.reload();
  };

  render() {
    if (!this.state.err) return this.props.children;
    return (
      <div style={{
        display: 'flex', flexDirection: 'column', alignItems: 'center',
        justifyContent: 'center', height: '100vh', padding: 24,
        fontFamily: 'system-ui, sans-serif', textAlign: 'center',
        background: '#122042', color: '#fff',
      }}>
        <h1 style={{ fontSize: 28, margin: 0 }}>Something went wrong</h1>
        <p style={{ opacity: 0.8, maxWidth: 420, margin: '12px 0 24px' }}>
          FairChore hit an unexpected error. Your data is safe — reload the
          page to continue.
        </p>
        <button onClick={this.handleReload} style={{
          background: '#fff', color: '#122042', border: 'none',
          padding: '10px 24px', borderRadius: 8, fontWeight: 600,
          cursor: 'pointer',
        }}>
          Reload
        </button>
        {process.env.NODE_ENV !== 'production' && (
          <pre style={{
            marginTop: 24, maxWidth: 560, whiteSpace: 'pre-wrap',
            fontSize: 12, opacity: 0.6, textAlign: 'left',
          }}>
            {String(this.state.err?.stack || this.state.err)}
          </pre>
        )}
      </div>
    );
  }
}
