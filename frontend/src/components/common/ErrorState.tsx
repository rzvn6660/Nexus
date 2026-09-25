import React, { useState } from 'react';
import { AlertTriangle, ChevronDown, ChevronUp, RefreshCw } from 'lucide-react';

interface ErrorStateProps {
  title?: string;
  message: string;
  technicalDetails?: any;
  onRetry?: () => void;
  className?: string;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Analysis Notice',
  message,
  technicalDetails,
  onRetry,
  className = '',
}) => {
  const [showDetails, setShowDetails] = useState(false);

  return (
    <div
      role="alert"
      className={`rounded-2xl border border-rose-500/30 bg-rose-950/20 p-6 space-y-4 ${className}`}
    >
      <div className="flex items-start gap-3">
        <div className="p-2 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400 mt-0.5 shrink-0">
          <AlertTriangle className="w-5 h-5" />
        </div>

        <div className="flex-1 space-y-1">
          <h3 className="text-sm font-semibold text-rose-200">{title}</h3>
          <p className="text-xs text-rose-300/90 leading-relaxed">{message}</p>
        </div>

        {onRetry && (
          <button
            onClick={onRetry}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-900/40 hover:bg-rose-900/60 border border-rose-700/50 text-rose-200 text-xs font-medium transition-all"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Retry</span>
          </button>
        )}
      </div>

      {technicalDetails && (
        <div className="border-t border-rose-900/40 pt-3">
          <button
            onClick={() => setShowDetails(!showDetails)}
            className="inline-flex items-center gap-1 text-[11px] font-mono text-rose-400/80 hover:text-rose-300 transition-colors"
          >
            {showDetails ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            <span>{showDetails ? 'Hide technical diagnostics' : 'Show technical diagnostics'}</span>
          </button>

          {showDetails && (
            <pre className="mt-2 p-3 rounded-lg bg-slate-950/80 border border-rose-900/30 text-[11px] font-mono text-slate-300 overflow-x-auto max-h-48 whitespace-pre-wrap">
              {typeof technicalDetails === 'string'
                ? technicalDetails
                : JSON.stringify(technicalDetails, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
};
