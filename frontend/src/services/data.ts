import { apiRequest } from './api';
import {
  DataHealthResponse,
  DatasetProfile,
  QualityReport,
  TableSummary,
} from '../types/api';

/**
 * Fetch data layer readiness status and table list.
 */
export async function getDataHealth(): Promise<DataHealthResponse> {
  return apiRequest<DataHealthResponse>('/api/v1/data/health');
}

/**
 * List all registered business domain tables.
 */
export async function listTables(): Promise<TableSummary[]> {
  return apiRequest<TableSummary[]>('/api/v1/data/tables');
}

/**
 * Profile a specific dataset / table for nulls, cardinality, distributions.
 */
export async function profileDataset(dataset: string): Promise<DatasetProfile> {
  return apiRequest<DatasetProfile>(`/api/v1/data/profile/${encodeURIComponent(dataset)}`);
}

/**
 * Audit dataset quality against business rules.
 */
export async function auditQuality(dataset: string): Promise<QualityReport> {
  return apiRequest<QualityReport>(`/api/v1/data/quality/${encodeURIComponent(dataset)}`);
}
