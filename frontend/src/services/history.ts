/**
 * History, Decisions & Audit Governance Service for NEXUS.
 * Interfaces with Phase 11 persisted analysis runs and human approval review gates.
 */

import { apiRequest, buildQueryString } from './api';
import {
  AnalysisRunItem,
  AnalysisRunDetail,
  DecisionRecordItem,
  DecisionReviewRequest,
  ReportExportResponse,
} from '../types/api';

/**
 * Fetch persisted history of analytical runs.
 */
export async function listHistoricalAnalyses(
  params?: { limit?: number; offset?: number }
): Promise<AnalysisRunItem[]> {
  const qs = buildQueryString(params);
  return apiRequest<AnalysisRunItem[]>(`/api/v1/history/analyses${qs}`);
}

/**
 * Fetch complete detail of a specific historical analysis run.
 */
export async function getAnalysisDetail(
  runId: number | string
): Promise<AnalysisRunDetail> {
  return apiRequest<AnalysisRunDetail>(`/api/v1/history/analyses/${runId}`);
}

/**
 * Generate and download exportable intelligence dossier.
 */
export async function exportAnalysisReport(
  runId: number | string,
  format: string = 'markdown'
): Promise<ReportExportResponse> {
  const qs = buildQueryString({ format });
  return apiRequest<ReportExportResponse>(`/api/v1/history/analyses/${runId}/report${qs}`);
}

/**
 * List human decision records with optional status filter.
 */
export async function listDecisionRecords(
  params?: { status?: string; limit?: number; offset?: number }
): Promise<DecisionRecordItem[]> {
  const qs = buildQueryString(params);
  return apiRequest<DecisionRecordItem[]>(`/api/v1/history/decisions${qs}`);
}

/**
 * Review, approve, reject or modify a proposed business recommendation.
 */
export async function reviewDecisionRecord(
  decisionId: number | string,
  review: DecisionReviewRequest
): Promise<DecisionRecordItem> {
  return apiRequest<DecisionRecordItem>(`/api/v1/history/decisions/${decisionId}/review`, {
    method: 'POST',
    body: JSON.stringify(review),
  });
}
