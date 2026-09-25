import { apiRequest, buildQueryString } from './api';
import {
  SummaryResponse,
  TimeSeriesResponse,
  ProductRankingResponse,
  BreakdownResponse,
  InventoryOverviewResponse,
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
