import React, { useState } from 'react';
import {
  CheckCircle,
  XCircle,
  Edit3,
  Clock,
  UserCheck,
  Check,
  PauseCircle,
  ArrowRight,
  ShieldCheck,
} from 'lucide-react';
import { DecisionRecordItem, DecisionReviewRequest } from '../../types/api';
import { formatDate } from '../../utils/formatters';

interface DecisionCardProps {
  decision: DecisionRecordItem;
  onReview?: (decisionId: number, review: DecisionReviewRequest) => Promise<void>;
  onInspectAnalysis?: (analysisId: number) => void;
  className?: string;
}

export const DecisionCard: React.FC<DecisionCardProps> = ({
  decision,
  onReview,
  onInspectAnalysis,
  className = '',
}) => {
  const [isReviewing, setIsReviewing] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState<'APPROVED' | 'REJECTED' | 'MODIFIED' | 'DEFERRED'>('APPROVED');
  const [reviewerNotes, setReviewerNotes] = useState(decision.reviewer_notes || '');
  const [submitting, setSubmitting] = useState(false);

  const getStatusBadge = (status: string) => {
    switch (status.toUpperCase()) {
      case 'APPROVED':
        return 'bg-emerald-950/80 text-emerald-300 border-emerald-700/60';
      case 'REJECTED':
        return 'bg-rose-950/80 text-rose-300 border-rose-700/60';
      case 'MODIFIED':
        return 'bg-sky-950/80 text-sky-300 border-sky-700/60';
      case 'DEFERRED':
        return 'bg-slate-900/80 text-slate-300 border-slate-700/60';
      default:
        return 'bg-amber-950/80 text-amber-300 border-amber-600/60 animate-pulse';
    }
  };

  const handleCommitReview = async () => {
    if (!onReview) return;
    setSubmitting(true);
    try {
      await onReview(decision.id, {
        status: selectedStatus,
        reviewer_notes: reviewerNotes.trim() || undefined,
        reviewed_by: 'Executive Reviewer',
      });
      setIsReviewing(false);
    } catch (err) {
      console.error('Failed to submit review:', err);
    } finally {
      setSubmitting(false);
    }
  };

  const isPending = decision.status.toUpperCase() === 'PENDING';

  return (
    <div
      className={`p-5 rounded-2xl bg-void/60 border ${
        isPending ? 'border-amber-500/40 shadow-[0_0_15px_-4px_rgba(245,158,11,0.15)]' : 'border-white/[0.08]'
      } space-y-4 hover:border-white/[0.15] transition-all ${className}`}
    >
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div className="space-y-1.5 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`text-[10px] font-mono uppercase px-2.5 py-0.5 rounded-full border font-semibold ${getStatusBadge(decision.status)}`}>
              {decision.status}
            </span>

            {decision.recommendation_type && (
              <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-surface border border-white/[0.08] text-slate-300 uppercase">
                {decision.recommendation_type}
              </span>
            )}

            <span className="text-[11px] font-mono text-slate-400 flex items-center gap-1">
              <Clock className="w-3 h-3 text-slate-500" />
              {formatDate(decision.created_at)}
            </span>

            {decision.analysis_id && (
              <button
                type="button"
                onClick={() => onInspectAnalysis?.(decision.analysis_id!)}
                className="text-[11px] font-mono text-cyan-400 hover:text-cyan-300 underline underline-offset-2 flex items-center gap-1 transition-colors"
                title={`Inspect Source Analysis #${decision.analysis_id}`}
              >
                <span>Run #{decision.analysis_id}</span>
                <ArrowRight className="w-2.5 h-2.5" />
              </button>
            )}
          </div>

          <h4 className="text-sm font-semibold text-white font-sans pt-1 leading-relaxed">
            {decision.recommendation_text}
          </h4>

          {(decision.action_target_type || decision.outcome_window_days) && (
            <div className="flex items-center gap-2 pt-0.5 text-[10px] font-mono text-slate-400">
              {decision.action_target_type && (
                <span>
                  Target: <span className="text-slate-300">{decision.action_target_type}{decision.action_target_id ? ` (${decision.action_target_id})` : ''}</span>
                </span>
              )}
              {decision.outcome_window_days && (
                <span>• Outcome Horizon: {decision.outcome_window_days}d</span>
              )}
            </div>
          )}
        </div>

        {isPending && onReview && !isReviewing && (
          <button
            onClick={() => setIsReviewing(true)}
            className="btn-primary text-xs h-8 px-3 self-start shrink-0 inline-flex items-center gap-1.5"
          >
            <UserCheck className="w-3.5 h-3.5" />
            <span>Review Gate</span>
          </button>
        )}
      </div>

      {/* Reviewer Note Display (If audited) */}
      {decision.reviewer_notes && !isReviewing && (
        <div className="p-3 rounded-xl bg-surface/80 border border-white/[0.06] text-xs font-mono text-slate-300 space-y-1">
          <div className="flex items-center justify-between text-slate-400 text-[10px] uppercase font-semibold">
            <span className="flex items-center gap-1">
              <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
              <span>Reviewer Audit Note:</span>
            </span>
            {decision.reviewed_at && (
              <span>Audited {formatDate(decision.reviewed_at)}</span>
            )}
          </div>
          <p className="font-sans text-slate-200 text-xs leading-relaxed">{decision.reviewer_notes}</p>
          {decision.reviewed_by && (
            <span className="text-slate-500 text-[10px] block">
              Auditor: {decision.reviewed_by}
            </span>
          )}
        </div>
      )}

      {/* Interactive Review Form */}
      {isReviewing && (
        <div className="pt-3 border-t border-white/[0.08] space-y-3 animate-in fade-in duration-150">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <span className="text-xs font-mono text-slate-300 font-semibold">Review Outcome Posture:</span>
            <div className="inline-flex rounded-lg bg-surface border border-white/[0.08] p-0.5 text-xs font-mono">
              <button
                type="button"
                onClick={() => setSelectedStatus('APPROVED')}
                className={`px-3 py-1 rounded-md transition-all flex items-center gap-1 ${
                  selectedStatus === 'APPROVED'
                    ? 'bg-emerald-600 text-white font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <CheckCircle className="w-3 h-3" />
                <span>Approve</span>
              </button>
              <button
                type="button"
                onClick={() => setSelectedStatus('MODIFIED')}
                className={`px-3 py-1 rounded-md transition-all flex items-center gap-1 ${
                  selectedStatus === 'MODIFIED'
                    ? 'bg-sky-600 text-white font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <Edit3 className="w-3 h-3" />
                <span>Modify</span>
              </button>
              <button
                type="button"
                onClick={() => setSelectedStatus('REJECTED')}
                className={`px-3 py-1 rounded-md transition-all flex items-center gap-1 ${
                  selectedStatus === 'REJECTED'
                    ? 'bg-rose-600 text-white font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <XCircle className="w-3 h-3" />
                <span>Reject</span>
              </button>
              <button
                type="button"
                onClick={() => setSelectedStatus('DEFERRED')}
                className={`px-3 py-1 rounded-md transition-all flex items-center gap-1 ${
                  selectedStatus === 'DEFERRED'
                    ? 'bg-slate-700 text-white font-semibold'
                    : 'text-slate-400 hover:text-slate-200'
                }`}
              >
                <PauseCircle className="w-3 h-3" />
                <span>Defer</span>
              </button>
            </div>
          </div>

          <textarea
            rows={2}
            value={reviewerNotes}
            onChange={(e) => setReviewerNotes(e.target.value)}
            placeholder="Provide audit context, modification caveats, or executive approval notes..."
            className="input-obsidian text-xs font-sans resize-none"
          />

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setIsReviewing(false)}
              className="btn-secondary text-xs h-8 px-3"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={submitting}
              onClick={handleCommitReview}
              className="btn-primary text-xs h-8 px-3 inline-flex items-center gap-1.5"
            >
              <Check className="w-3.5 h-3.5" />
              <span>{submitting ? 'Committing...' : 'Commit Decision'}</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

