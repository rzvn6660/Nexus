import { Component, ErrorInfo, ReactNode } from 'react';
import { AlertOctagon, RefreshCw } from 'lucide-react';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallbackTitle?: string;
  fallbackMessage?: string;
  onReset?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    console.error('[NEXUS ErrorBoundary caught an unhandled rendering error]:', error, errorInfo);
    this.setState({ errorInfo });
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <div className="p-8 sm:p-12 rounded-3xl bg-surface/80 border border-rose-500/30 text-center max-w-2xl mx-auto my-8 shadow-2xl backdrop-blur-xl space-y-5 animate-in fade-in duration-200">
          <div className="w-14 h-14 rounded-2xl bg-rose-950/80 border border-rose-500/40 flex items-center justify-center mx-auto text-rose-400 shadow-[0_0_20px_rgba(244,63,94,0.2)]">
            <AlertOctagon className="w-7 h-7" />
          </div>

          <div className="space-y-2">
            <h3 className="text-xl font-bold text-white font-sans">
              {this.props.fallbackTitle || 'Component Rendering Exception'}
            </h3>
            <p className="text-xs sm:text-sm text-slate-300 max-w-md mx-auto leading-relaxed">
              {this.props.fallbackMessage ||
                'An unexpected rendering issue occurred in this section. NEXUS captured the fault to keep the workspace operational.'}
            </p>
          </div>

          {this.state.error && (
            <div className="p-3.5 rounded-xl bg-void/80 border border-surface-elevated text-left font-mono text-[11px] text-rose-300 max-h-32 overflow-y-auto">
              <span className="text-slate-500 block text-[9px] uppercase tracking-wider mb-1">
                ERROR DIAGNOSTIC
              </span>
              {this.state.error.toString()}
            </div>
          )}

          <div className="pt-2">
            <button
              type="button"
              onClick={this.handleReset}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-xl bg-brand-cyan hover:bg-cyan-400 text-void font-bold text-xs shadow-lg transition-all cursor-pointer"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Recover Component</span>
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}
