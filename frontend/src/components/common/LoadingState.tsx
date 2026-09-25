import React from 'react';
import { Loader2 } from 'lucide-react';

interface LoadingStateProps {
  message?: string;
  stepIndex?: number;
  steps?: string[];
  className?: string;
}

export const LoadingState: React.FC<LoadingStateProps> = ({
  message = 'Loading analytics...',
  stepIndex,
  steps,
  className = '',
}) => {
  return (
    <div
      role="status"
      aria-live="polite"
      className={`flex flex-col items-center justify-center p-8 text-center space-y-4 ${className}`}
    >
      <div className="relative">
        <div className="w-12 h-12 rounded-2xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center animate-pulse">
          <Loader2 className="w-6 h-6 text-cyan-400 animate-spin" />
        </div>
      </div>

      <div className="space-y-1">
        <p className="text-sm font-medium text-slate-200">{message}</p>
        <p className="text-xs text-slate-400">Performing deterministic verification</p>
      </div>

      {steps && steps.length > 0 && (
        <div className="w-full max-w-xs pt-2 space-y-2">
          {steps.map((step, idx) => {
            const isCompleted = stepIndex !== undefined && idx < stepIndex;
            const isCurrent = stepIndex !== undefined && idx === stepIndex;
            return (
              <div
                key={step}
                className="flex items-center gap-2 text-xs font-mono transition-opacity duration-200"
              >
                <div
                  className={`w-2 h-2 rounded-full ${
                    isCompleted
                      ? 'bg-emerald-400'
                      : isCurrent
                      ? 'bg-cyan-400 animate-ping'
                      : 'bg-slate-700'
                  }`}
                />
                <span
                  className={
                    isCurrent
                      ? 'text-cyan-300 font-semibold'
                      : isCompleted
                      ? 'text-slate-400 line-through'
                      : 'text-slate-400'
                  }
                >
                  {step}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export const CardSkeleton: React.FC<{ rows?: number }> = ({ rows = 3 }) => {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 space-y-4 animate-pulse">
      <div className="flex items-center justify-between">
        <div className="h-4 w-28 bg-slate-800 rounded" />
        <div className="h-6 w-16 bg-slate-800 rounded-full" />
      </div>
      <div className="h-8 w-40 bg-slate-700 rounded" />
      <div className="space-y-2 pt-2">
        {Array.from({ length: rows }).map((_, i) => (
          <div
            key={i}
            className="h-3 bg-slate-800/80 rounded"
            style={{ width: `${85 - i * 15}%` }}
          />
        ))}
      </div>
    </div>
  );
};
