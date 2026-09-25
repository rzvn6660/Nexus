import React from 'react';
import { CheckCircle2, Circle, Loader2 } from 'lucide-react';

export type StageId = 'understand' | 'investigate' | 'validate' | 'predict' | 'decide';

interface StageConfig {
  id: StageId;
  label: string;
  defaultAction: string;
}

const STAGES: StageConfig[] = [
  { id: 'understand', label: 'Understand', defaultAction: 'Resolving business semantics & temporal boundaries' },
  { id: 'investigate', label: 'Investigate', defaultAction: 'Decomposing variance & testing driver hypotheses' },
  { id: 'validate', label: 'Validate', defaultAction: 'Verifying mathematical & empirical evidence' },
  { id: 'predict', label: 'Predict', defaultAction: 'Evaluating prospective forecast horizons' },
  { id: 'decide', label: 'Decide', defaultAction: 'Synthesizing recommendations for human review' },
];

interface IntelligenceStageProps {
  currentStage?: StageId;
  statusMessage?: string;
  isExecuting?: boolean;
  completedStages?: StageId[];
  className?: string;
}

export const IntelligenceStage: React.FC<IntelligenceStageProps> = ({
  currentStage = 'understand',
  statusMessage,
  isExecuting = false,
  completedStages = [],
  className = '',
}) => {
  const currentIndex = STAGES.findIndex((s) => s.id === currentStage);

  return (
    <div className={`p-4 rounded-2xl bg-void-sub border border-surface-elevated space-y-3 ${className}`}>
      {/* Visual Workflow Pipeline Track */}
      <div className="flex items-center justify-between gap-1 overflow-x-auto pb-1 text-xs">
        {STAGES.map((stage, idx) => {
          const isCompleted = completedStages.includes(stage.id) || (!isExecuting && idx < currentIndex);
          const isCurrent = stage.id === currentStage;

          return (
            <React.Fragment key={stage.id}>
              <div
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg shrink-0 transition-all font-mono text-[11px] ${
                  isCurrent
                    ? 'bg-cyan-950/90 text-brand-cyan border border-brand-cyan/40 font-semibold shadow-sm'
                    : isCompleted
                    ? 'bg-surface/80 text-emerald-400 border border-emerald-900/60'
                    : 'text-slate-500 bg-void/50 border border-surface-elevated/40'
                }`}
              >
                {isCurrent && isExecuting ? (
                  <Loader2 className="w-3.5 h-3.5 text-brand-cyan animate-spin shrink-0" />
                ) : isCompleted ? (
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400 shrink-0" />
                ) : (
                  <Circle className="w-3.5 h-3.5 text-slate-600 shrink-0" />
                )}
                <span>{stage.label}</span>
              </div>

              {idx < STAGES.length - 1 && (
                <div
                  className={`h-0.5 flex-1 min-w-[12px] transition-colors ${
                    idx < currentIndex || isCompleted
                      ? 'bg-cyan-800/80'
                      : 'bg-surface-elevated'
                  }`}
                />
              )}
            </React.Fragment>
          );
        })}
      </div>

      {/* Human-Readable Operation Status Line */}
      {statusMessage && (
        <div className="flex items-center gap-2 pt-1 border-t border-surface-elevated/60 text-xs font-mono text-slate-300">
          <span className="w-1.5 h-1.5 rounded-full bg-brand-cyan animate-pulse" />
          <span className="uppercase text-brand-cyan font-semibold text-[10px] tracking-wider">
            {currentStage}:
          </span>
          <span className="truncate">{statusMessage}</span>
        </div>
      )}
    </div>
  );
};
