import React, { useState } from 'react';
import {
  CheckCircle,
  XCircle,
  Edit3,
  Clock,
  UserCheck,
  Check,
} from 'lucide-react';
import { DecisionRecordItem, DecisionReviewRequest } from '../../types/api';
import { formatDate } from '../../utils/formatters';

interface DecisionCardProps {
  decision: DecisionRecordItem;
  onReview?: (decisionId: number, review: DecisionReviewRequest) => Promise<void>;
  className?: string;
}

export const DecisionCard: React.FC<DecisionCardProps> = ({
  decision,
  onReview,
  className = '',
}) => {
  const [isReviewing, setIsReviewing] = useState(false);
  const [selectedStatus, setSelectedStatus] = useState<'APPROVED' | 'REJECTED' | 'MODIFIED'>('APPROVED');
  const [reviewerNotes, setReviewerNotes] = useState(decision.reviewer_notes || '');
  const [submitting, setSubmitting] = useState(false);

  const getStatusBadge = (status: string) => {
    switch (status.toUpperCase()) {
      case 'APPROVED':
        return 'bg-emerald-950/80 text-emerald-300 border-emerald-800';
      case 'REJECTED':
        return 'bg-rose-950/80 text-rose-300 border-rose-800';
      case 'MODIFIED':
        return 'bg-sky-950/80 text-sky-300 border-sky-800';
      default:
        return 'bg-amber-950/80 text-amber-300 border-amber-800 animate-pulse';
    }
  };

  const handleCommitReview = async () => {
    if (!onReview) return;
    setSubmitting(true);
    try {
      await onReview(decision.id, {
        status: selectedStatus,
        reviewer_notes: reviewerNotes,
        reviewed_by: 'Lead Analyst / Executive',
      });
      setIsReviewing(false);
    } catch (err) {
      console.error('Failed to submit review:', err);
    } finally {
      setSubmitting(false);
    }
  };

  const isPending = decision.status === 'PENDING';

  return (
    <div
      className={`p-5 rounded-2xl bg-surface/70 border ${
        isPending ? 'border-amber-800/60' : 'border-surface-elevated'
      } space-y-4 ${className}`}
    >
      <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
        <div className="space-y-1 flex-1">
          <div className="flex items-center gap-2">
            <span className={`text-[10px] font-mono uppercase px-2.5 py-0.5 rounded-full border ${getStatusBadge(decision.status)}`}>
              {decision.status}
            </span>
            <span className="text-[11px] font-mono text-slate-400 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {formatDate(decision.created_at)}
            </span>
          </div>

          <h4 className="text-sm font-semibold text-white font-sans pt-1">
            {decision.recommendation_text}
          </h4>
        </div>

        {isPending && onReview && !isReviewing && (
          <button
            onClick={() => setIsReviewing(true)}
            className="inline-flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold shadow-md shadow-cyan-600/25 transition-all self-start"
          >
            <UserCheck className="w-3.5 h-3.5" />
            <span>Human Review Gate</span>
          </button>
        )}
      </div>

      {/* Reviewer Note Display (If already audited) */}
      {decision.reviewer_notes && !isReviewing && (
        <div className="p-3 rounded-xl bg-void/60 border border-surface-elevated text-xs font-mono text-slate-300">
          <span className="text-slate-400 block text-[10px] uppercase">Reviewer Audit Note:</span>
          <p className="mt-0.5">{decision.reviewer_notes}</p>
          {decision.reviewed_by && (
            <span className="text-slate-400 text-[10px] block mt-1">
              By {decision.reviewed_by} on {formatDate(decision.reviewed_at || '')}
            </span>
          )}
        </div>
      )}

      {/* Interactive Review Form */}
      {isReviewing && (
        <div className="pt-3 border-t border-surface-elevated space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-xs font-mono text-slate-300 font-semibold">Review Outcome:</span>
            <div className="inline-flex rounded-lg bg-void border border-surface-elevated p-0.5 text-xs font-mono">
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
            </div>
          </div>

          <textarea
            rows={2}
            value={reviewerNotes}
            onChange={(e) => setReviewerNotes(e.target.value)}
            placeholder="Provide context, modification caveats, or executive approval notes..."
            className="w-full rounded-xl bg-void border border-surface-elevated p-3 text-xs text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-brand-cyan font-sans"
          />

          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => setIsReviewing(false)}
              className="px-3 py-1.5 rounded-lg text-slate-400 hover:text-slate-200 text-xs"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={submitting}
              onClick={handleCommitReview}
              className="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg bg-brand-cyan hover:bg-cyan-400 text-void font-bold text-xs transition-all shadow-sm"
            >
              <Check className="w-3.5 h-3.5" />
              <span>Commit Decision</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
