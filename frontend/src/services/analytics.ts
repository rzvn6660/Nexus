import { apiRequest, buildQueryString } from './api';
import {
  SummaryResponse,
  TimeSeriesResponse,
  ProductRankingResponse,
  BreakdownResponse,
  InventoryOverviewResponse,
  CadenceResponse,
  RetentionOverviewResponse,
  RetentionCustomerListApiResponse,
  RetentionCustomerDetailResponse,
  RetentionOutcomeEvaluationResponse,
} from '../types/api';

export interface AnalyticsFilterParams {
  date_from?: string;
  date_to?: string;
  comparison_date_from?: string;
  comparison_date_to?: string;
  categories?: string[];
  customer_segments?: string[];
  granularity?: 'daily' | 'weekly' | 'monthly' | 'quarterly' | 'yearly';
}

/**
 * Fetch 12-metric financial summary with baseline comparisons.
 */
export async function getFinancialSummary(
  params?: AnalyticsFilterParams
): Promise<SummaryResponse> {
  const query = buildQueryString(params);
  return apiRequest<SummaryResponse>(`/api/v1/analytics/summary${query}`);
}

/**
 * Fetch revenue time series.
 */
export async function getRevenueTimeSeries(
  params?: AnalyticsFilterParams
): Promise<TimeSeriesResponse> {
  const query = buildQueryString(params);
  return apiRequest<TimeSeriesResponse>(`/api/v1/analytics/revenue${query}`);
}

/**
 * Fetch profit time series.
 */
export async function getProfitTimeSeries(
  params?: AnalyticsFilterParams
): Promise<TimeSeriesResponse> {
  const query = buildQueryString(params);
  return apiRequest<TimeSeriesResponse>(`/api/v1/analytics/profit${query}`);
}

/**
 * Fetch sales volume & orders time series.
 */
export async function getSalesTimeSeries(
  params?: AnalyticsFilterParams
): Promise<TimeSeriesResponse> {
  const query = buildQueryString(params);
  return apiRequest<TimeSeriesResponse>(`/api/v1/analytics/sales${query}`);
}

/**
 * Fetch product performance rankings.
 */
export async function getProductRankings(
  params?: AnalyticsFilterParams & { ranking_metric?: string; limit?: number }
): Promise<ProductRankingResponse> {
  const query = buildQueryString(params);
  return apiRequest<ProductRankingResponse>(`/api/v1/analytics/products${query}`);
}

/**
 * Fetch product category breakdown.
 */
export async function getCategoryBreakdown(
  params?: AnalyticsFilterParams & { metric?: string }
): Promise<BreakdownResponse> {
  const query = buildQueryString(params);
  return apiRequest<BreakdownResponse>(`/api/v1/analytics/categories${query}`);
}

/**
 * Fetch customer segments breakdown.
 */
export async function getCustomerSegments(
  params?: AnalyticsFilterParams
): Promise<BreakdownResponse> {
  const query = buildQueryString(params);
  return apiRequest<BreakdownResponse>(`/api/v1/analytics/customers${query}`);
}

/**
 * Fetch inventory health overview and alert metrics.
 */
export async function getInventoryOverview(
  params?: { warehouse?: string; category?: string }
): Promise<InventoryOverviewResponse> {
  const query = buildQueryString(params);
  return apiRequest<InventoryOverviewResponse>(`/api/v1/analytics/inventory${query}`);
}

/**
 * Fetch customer purchase cadence metrics with pilot safety gates and seasonal disclosures.
 */
export async function getCustomerCadence(
  params?: { date_to?: string; required_sources?: string[]; seasonal_context?: string }
): Promise<CadenceResponse> {
  const query = buildQueryString(params);
  return apiRequest<CadenceResponse>(`/api/v1/analytics/cadence${query}`);
}

/**
 * Fetch customer retention overview and workload distribution.
 */
export async function getRetentionOverview(
  params?: { date_to?: string; required_sources?: string[]; seasonal_context?: string }
): Promise<RetentionOverviewResponse> {
  const query = buildQueryString(params);
  return apiRequest<RetentionOverviewResponse>(`/api/v1/analytics/retention/overview${query}`);
}

/**
 * List and prioritize customers at risk of churn with retention proposals.
 */
export async function listRetentionCustomers(
  params?: {
    risk_tier?: string;
    urgency?: string;
    segment?: string;
    search?: string;
    requires_attention_only?: boolean;
    is_repeat_only?: boolean;
    page?: number;
    page_size?: number;
    date_to?: string;
  }
): Promise<RetentionCustomerListApiResponse> {
  const query = buildQueryString(params);
  return apiRequest<RetentionCustomerListApiResponse>(`/api/v1/analytics/retention/customers${query}`);
}

/**
 * Fetch deep-dive risk profile and contextual retention proposal for a customer.
 */
export async function getRetentionCustomerDetail(
  customerId: number,
  params?: { date_to?: string }
): Promise<RetentionCustomerDetailResponse> {
  const query = buildQueryString(params);
  return apiRequest<RetentionCustomerDetailResponse>(`/api/v1/analytics/retention/customers/${customerId}${query}`);
}

/**
 * Register a retention recommendation in the HITL ledger.
 */
export async function createRetentionRecommendation(payload: {
  customer_id: number;
  action_type?: string;
  custom_notes?: string;
}): Promise<any> {
  return apiRequest<any>('/api/v1/analytics/retention/actions/recommend', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Record merchant review disposition for a retention decision (HITL).
 */
export async function reviewRetentionDecision(payload: {
  decision_id: number;
  status: 'APPROVED' | 'REJECTED' | 'MODIFIED' | 'DEFERRED';
  reviewer_id: string;
  reviewer_notes?: string;
  modified_action_type?: string;
}): Promise<any> {
  return apiRequest<any>('/api/v1/analytics/retention/actions/review', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Record execution of an approved retention action.
 */
export async function executeRetentionAction(payload: {
  decision_id: number;
  execution_channel: string;
  executed_by: string;
  execution_notes?: string;
  offer_code?: string;
  execution_date?: string;
}): Promise<any> {
  return apiRequest<any>('/api/v1/analytics/retention/actions/execute', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Log customer response to an executed retention intervention.
 */
export async function logCustomerResponse(payload: {
  decision_id: number;
  response_status: 'opened' | 'replied' | 'redeemed_code' | 'no_response' | 'declined' | 'purchased';
  logged_by: string;
  response_notes?: string;
  response_date?: string;
}): Promise<any> {
  return apiRequest<any>('/api/v1/analytics/retention/actions/response', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Evaluate customer retention outcomes comparing intervened customers against non-intervened at-risk peers.
 */
export async function getRetentionEvaluation(
  params?: { evaluation_window_days?: number; date_to?: string }
): Promise<RetentionOutcomeEvaluationResponse> {
  const query = buildQueryString(params);
  return apiRequest<RetentionOutcomeEvaluationResponse>(`/api/v1/analytics/retention/evaluation${query}`);
}
