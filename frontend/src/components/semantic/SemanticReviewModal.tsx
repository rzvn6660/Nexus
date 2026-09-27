import React, { useState, useEffect } from 'react';
import {
  X,
  AlertTriangle,
  CheckCircle2,
  ShieldAlert,
  ArrowRight,
  Layers,
  Edit3,
  RefreshCw,
  Ban,
  Check,
} from 'lucide-react';
import {
  getSemanticRevisionDiff,
  approveSemanticRevision,
  rejectSemanticRevision,
  modifySemanticRevision,
} from '../../services/semantic';
import { SemanticDiffResponse, MetricDiffItem } from '../../types/api';

interface SemanticReviewModalProps {
  isOpen: boolean;
  onClose: () => void;
  revisionId: string;
  revisionVersion: number;
  businessId?: string;
  onActionComplete: () => void;
}

export const SemanticReviewModal: React.FC<SemanticReviewModalProps> = ({
  isOpen,
  onClose,
  revisionId,
  revisionVersion,
  businessId,
  onActionComplete,
}) => {
  const [diff, setDiff] = useState<SemanticDiffResponse | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [actionInProgress, setActionInProgress] = useState<boolean>(false);
  const [comment, setComment] = useState<string>('');
  const [error, setError] = useState<string | null>(null);
  const [showModifyForm, setShowModifyForm] = useState<boolean>(false);
  const [formulaOverrides, setFormulaOverrides] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!isOpen) return;

    let isMounted = true;
    setLoading(true);
    setError(null);
    setShowModifyForm(false);
    setFormulaOverrides({});
    setComment('');

    getSemanticRevisionDiff(revisionId, undefined, businessId)
      .then((res) => {
        if (isMounted) {
          setDiff(res);
          // Initialize overrides with proposed formulas
          const initialOverrides: Record<string, string> = {};
          res.metric_diffs.forEach((m) => {
            if (m.has_conflict || m.change_type === 'CHANGED') {
              initialOverrides[m.metric_name] = m.proposed_formula || '';
            }
          });
          setFormulaOverrides(initialOverrides);
        }
      })
      .catch((err: any) => {
        if (isMounted) {
          setError(err?.message || 'Failed to compute revision differences.');
        }
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => {
      isMounted = false;
    };
  }, [isOpen, revisionId, businessId]);

  if (!isOpen) return null;

  const handleApprove = async () => {
    setActionInProgress(true);
    setError(null);
    try {
      await approveSemanticRevision(revisionId, { comment: comment.trim() || undefined }, businessId);
      onActionComplete();
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to approve revision. Check permissions.');
    } finally {
      setActionInProgress(false);
    }
  };

  const handleReject = async () => {
    setActionInProgress(true);
    setError(null);
    try {
      await rejectSemanticRevision(revisionId, { comment: comment.trim() || undefined }, businessId);
      onActionComplete();
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to reject revision. Check permissions.');
    } finally {
      setActionInProgress(false);
    }
  };

  const handleModifySubmit = async () => {
    setActionInProgress(true);
    setError(null);
    try {
      const metricsOverride: Record<string, Record<string, any>> = {};
      Object.entries(formulaOverrides).forEach(([metricName, formula]) => {
        if (formula.trim()) {
          metricsOverride[metricName] = { calculation_formula: formula.trim() };
        }
      });

      await modifySemanticRevision(
        revisionId,
        {
          metrics_override: metricsOverride,
          comment: comment.trim() || undefined,
        },
        businessId
      );
      onActionComplete();
      onClose();
    } catch (err: any) {
      setError(err?.message || 'Failed to save modifications.');
    } finally {
      setActionInProgress(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-void/80 backdrop-blur-md animate-fade-in">
      <div className="glass-panel w-full max-w-4xl max-h-[90vh] rounded-3xl border border-surface-elevated bg-surface/95 shadow-2xl flex flex-col overflow-hidden text-slate-200">
        {/* Header */}
        <div className="p-6 border-b border-surface-elevated flex items-center justify-between bg-surface-elevated/40 shrink-0">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-2xl bg-amber-500/10 border border-amber-500/20 text-amber-400">
              <ShieldAlert className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white tracking-tight flex items-center gap-2">
                Semantic Revision Review
                <span className="text-xs font-mono font-normal px-2.5 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20">
                  Revision v{revisionVersion}
                </span>
              </h2>
              <p className="text-xs text-slate-400">
                Inspect changes against active model before approving or rejecting activation.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            disabled={actionInProgress}
            className="p-2 rounded-xl text-slate-400 hover:text-white hover:bg-surface-elevated transition-all"
            aria-label="Close"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">
          {error && (
            <div className="p-4 rounded-2xl bg-rose-950/40 border border-rose-800/60 text-xs text-rose-300 flex items-center gap-3">
              <AlertTriangle className="w-4 h-4 text-rose-400 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {loading ? (
            <div className="py-20 flex flex-col items-center justify-center gap-3 text-slate-400">
              <RefreshCw className="w-6 h-6 animate-spin text-cyan-400" />
              <p className="text-xs">Computing deterministic semantic diff...</p>
            </div>
          ) : diff ? (
            <>
              {/* Conflict Notification */}
              {diff.has_conflicts && (
                <div className="p-4 rounded-2xl bg-amber-950/30 border border-amber-800/40 text-xs space-y-1.5">
                  <div className="flex items-center gap-2 text-amber-300 font-semibold">
                    <AlertTriangle className="w-4 h-4 text-amber-400" />
                    <span>{diff.conflicts_count} Semantic Definition Conflict(s) Detected</span>
                  </div>
                  <p className="text-slate-300 text-[11px]">
                    The proposed revision contains metric calculation formulas that differ from your currently verified active model. To prevent silent metric changes, human approval is required.
                  </p>
                </div>
              )}

              {/* Version Comparison Bar */}
              <div className="p-4 rounded-2xl bg-void/50 border border-surface-elevated flex items-center justify-between text-xs">
                <div className="flex items-center gap-3">
                  <div>
                    <span className="text-[10px] uppercase font-mono tracking-wider text-slate-500 block">
                      Active Model
                    </span>
                    <span className="font-semibold text-slate-300">
                      {diff.base_version ? `Version v${diff.base_version}` : 'None (Initial Activation)'}
                    </span>
                  </div>
                  <ArrowRight className="w-4 h-4 text-slate-600" />
                  <div>
                    <span className="text-[10px] uppercase font-mono tracking-wider text-amber-400 block">
                      Proposed Revision
                    </span>
                    <span className="font-semibold text-amber-300 font-mono">
                      Version v{diff.target_version}
                    </span>
                  </div>
                </div>

                <div className="flex items-center gap-4 text-[11px] font-mono">
                  <span className="text-slate-400">
                    Metrics changed: <strong className="text-white">{diff.metric_diffs.filter((m) => m.change_type !== 'UNCHANGED').length}</strong>
                  </span>
                  <span className="text-slate-400">
                    Entities: <strong className="text-white">{diff.entity_diffs.length}</strong>
                  </span>
                </div>
              </div>

              {/* Metric Changes Detail */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-semibold text-slate-300 uppercase tracking-wider flex items-center gap-2">
                    <Layers className="w-4 h-4 text-cyan-400" /> Metric Definition Comparison
                  </h3>
                  <button
                    onClick={() => setShowModifyForm(!showModifyForm)}
                    className="text-xs text-cyan-400 hover:text-cyan-300 flex items-center gap-1.5 transition-colors"
                  >
                    <Edit3 className="w-3.5 h-3.5" />
                    <span>{showModifyForm ? 'Hide Formula Editor' : 'Customize Formulas'}</span>
                  </button>
                </div>

                <div className="space-y-2">
                  {diff.metric_diffs.map((m: MetricDiffItem) => {
                    const isChanged = m.change_type === 'CHANGED';
                    const isAdded = m.change_type === 'ADDED';
                    const isRemoved = m.change_type === 'REMOVED';

                    return (
                      <div
                        key={m.metric_name}
                        className={`p-3.5 rounded-2xl border text-xs space-y-2 ${
                          m.has_conflict
                            ? 'bg-amber-950/20 border-amber-700/50'
                            : isChanged
                            ? 'bg-surface/60 border-surface-elevated'
                            : isAdded
                            ? 'bg-emerald-950/10 border-emerald-800/30'
                            : isRemoved
                            ? 'bg-rose-950/10 border-rose-800/30'
                            : 'bg-surface/30 border-surface-elevated/40 opacity-70'
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-white">{m.metric_name}</span>
                            <span
                              className={`text-[10px] font-mono px-2 py-0.5 rounded-full border ${
                                m.has_conflict
                                  ? 'bg-amber-500/10 text-amber-300 border-amber-500/30 font-bold'
                                  : isChanged
                                  ? 'bg-blue-500/10 text-blue-300 border-blue-500/30'
                                  : isAdded
                                  ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                                  : isRemoved
                                  ? 'bg-rose-500/10 text-rose-300 border-rose-500/30'
                                  : 'bg-slate-800 text-slate-400 border-slate-700'
                              }`}
                            >
                              {m.has_conflict ? 'CONFLICT' : m.change_type}
                            </span>
                          </div>

                          <span className="font-mono text-[10px] text-slate-400">
                            Source: {m.source_data || 'database'}
                          </span>
                        </div>

                        {/* Formula Comparison */}
                        {(isChanged || m.has_conflict) && (
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
                            <div className="p-2.5 rounded-xl bg-void/60 border border-surface-elevated space-y-1">
                              <span className="text-[10px] text-slate-400 uppercase font-mono block">
                                Verified Active Formula
                              </span>
                              <code className="text-slate-300 font-mono text-[11px] block break-all">
                                {m.previous_formula || 'None'}
                              </code>
                            </div>
                            <div className="p-2.5 rounded-xl bg-amber-950/30 border border-amber-800/40 space-y-1">
                              <span className="text-[10px] text-amber-400 uppercase font-mono block">
                                Proposed Formula
                              </span>
                              <code className="text-amber-200 font-mono text-[11px] block break-all">
                                {m.proposed_formula || 'None'}
                              </code>
                            </div>
                          </div>
                        )}

                        {m.conflict_reason && (
                          <p className="text-[11px] text-amber-300/90 font-mono">
                            ⚠ {m.conflict_reason}
                          </p>
                        )}

                        {/* Formula Editor Row if shown */}
                        {showModifyForm && (m.has_conflict || isChanged) && (
                          <div className="pt-2 border-t border-surface-elevated/40 space-y-1">
                            <label className="text-[10px] text-slate-400 font-medium">
                              Override Calculation Formula:
                            </label>
                            <input
                              type="text"
                              value={formulaOverrides[m.metric_name] || ''}
                              onChange={(e) =>
                                setFormulaOverrides({
                                  ...formulaOverrides,
                                  [m.metric_name]: e.target.value,
                                })
                              }
                              className="w-full px-3 py-1.5 rounded-xl bg-void border border-surface-highlight text-xs font-mono text-cyan-300 focus:outline-none focus:border-cyan-500"
                              placeholder="e.g. SUM(sales.total_amount - sales.discount)"
                            />
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Synonyms & Ambiguity Changes (if any) */}
              {(diff.synonym_diffs.some((s) => s.change_type !== 'UNCHANGED') ||
                diff.ambiguous_term_diffs.some((a) => a.change_type !== 'UNCHANGED')) && (
                <div className="p-4 rounded-2xl bg-void/40 border border-surface-elevated space-y-2 text-xs">
                  <h4 className="font-semibold text-slate-300">Synonym & Term Alignments:</h4>
                  {diff.synonym_diffs
                    .filter((s) => s.change_type !== 'UNCHANGED')
                    .map((s) => (
                      <p key={s.term} className="text-slate-400 font-mono text-[11px]">
                        • Synonym '{s.term}': {s.previous_target || 'None'} → {s.proposed_target} ({s.change_type})
                      </p>
                    ))}
                </div>
              )}

              {/* Reviewer Note / Comment */}
              <div className="space-y-1.5 pt-2">
                <label className="text-xs font-medium text-slate-300 block">
                  Reviewer Audit Note (Optional):
                </label>
                <textarea
                  rows={2}
                  value={comment}
                  onChange={(e) => setComment(e.target.value)}
                  placeholder="Record rationale for approval, rejection, or formula adjustments..."
                  className="w-full px-3.5 py-2.5 rounded-2xl bg-void/80 border border-surface-elevated text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:border-slate-500 resize-none"
                />
              </div>
            </>
          ) : null}
        </div>

        {/* Action Footer */}
        <div className="p-5 border-t border-surface-elevated bg-surface-elevated/40 flex flex-col sm:flex-row items-center justify-between gap-3 shrink-0">
          <span className="text-[11px] text-slate-500">
            Authorization: Organization Owner or Admin role required.
          </span>

          <div className="flex items-center gap-2.5 w-full sm:w-auto justify-end">
            <button
              onClick={onClose}
              disabled={actionInProgress}
              className="px-4 py-2 rounded-xl text-xs font-medium text-slate-400 hover:text-white hover:bg-surface-elevated transition-all"
            >
              Cancel
            </button>

            {showModifyForm ? (
              <button
                onClick={handleModifySubmit}
                disabled={actionInProgress || loading}
                className="flex items-center gap-2 px-4 py-2 rounded-xl bg-cyan-600 hover:bg-cyan-500 text-white text-xs font-semibold shadow-lg shadow-cyan-950 transition-all disabled:opacity-50"
              >
                <Check className="w-4 h-4" />
                <span>Save Modifications & Submit</span>
              </button>
            ) : (
              <>
                <button
                  onClick={handleReject}
                  disabled={actionInProgress || loading}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-rose-950/60 hover:bg-rose-900 border border-rose-800 text-rose-200 text-xs font-semibold transition-all disabled:opacity-50"
                >
                  <Ban className="w-3.5 h-3.5" />
                  <span>Reject Revision</span>
                </button>

                <button
                  onClick={handleApprove}
                  disabled={actionInProgress || loading}
                  className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-lg shadow-emerald-950 transition-all disabled:opacity-50"
                >
                  <CheckCircle2 className="w-4 h-4" />
                  <span>Approve & Activate v{revisionVersion}</span>
                </button>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
