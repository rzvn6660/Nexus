import { apiRequest } from './api';

export interface GatewayColumnProfile {
  column_name: string;
  inferred_type: string;
  null_count: number;
  null_percentage: number;
  unique_count: number;
  is_unique: boolean;
  sample_values: any[];
  min_value?: any;
  max_value?: any;
  mean_value?: number;
  column_role: string;
}

export interface GatewayQualityCheck {
  rule_id: string;
  rule_name: string;
  passed: boolean;
  score_deduction: number;
  message: string;
  affected_columns: string[];
}

export interface GatewayMappingProposal {
  source_column: string;
  mapped_field: string;
  confidence: number;
  status: 'AUTOMAPPED' | 'REQUIRES_REVIEW';
  reason: string;
}

export interface GatewayDatasetDetail {
  dataset_id: string;
  original_filename: string;
  file_format: string;
  file_size_bytes: number;
  status: string;
  row_count: number;
  column_count: number;
  column_profiles: GatewayColumnProfile[];
  column_roles: Record<string, string>;
  quality_score: number;
  quality_checks: GatewayQualityCheck[];
  target_entity: string;
  schema_mappings: GatewayMappingProposal[];
  readiness_score: number;
  readiness_status: string;
  readiness_reasons: string[];
  created_at: string;
}

export interface GatewayPreviewResponse {
  dataset_id: string;
  filename: string;
  total_rows: number;
  total_columns: number;
  columns: string[];
  inferred_types: Record<string, string>;
  column_roles: Record<string, string>;
  sample_rows: Record<string, any>[];
  readiness_score: number;
  target_entity: string;
  schema_mappings: GatewayMappingProposal[];
}

export interface GatewayIngestResponse {
  dataset_id: string;
  status: string;
  target_entity: string;
  records_persisted: number;
  business_id: string;
  message: string;
}

export async function uploadGatewayDataset(file: File): Promise<GatewayDatasetDetail> {
  const formData = new FormData();
  formData.append('file', file);
  return apiRequest<GatewayDatasetDetail>('/api/v1/gateway/upload', {
    method: 'POST',
    body: formData,
  });
}

export async function listGatewayDatasets(): Promise<GatewayDatasetDetail[]> {
  return apiRequest<GatewayDatasetDetail[]>('/api/v1/gateway/datasets');
}

export async function getGatewayDataset(datasetId: string): Promise<GatewayDatasetDetail> {
  return apiRequest<GatewayDatasetDetail>(`/api/v1/gateway/datasets/${datasetId}`);
}

export async function previewGatewayDataset(datasetId: string): Promise<GatewayPreviewResponse> {
  return apiRequest<GatewayPreviewResponse>(`/api/v1/gateway/datasets/${datasetId}/preview`);
}

export async function ingestGatewayDataset(
  datasetId: string,
  targetEntity?: string,
  columnOverrides?: Record<string, string>
): Promise<GatewayIngestResponse> {
  return apiRequest<GatewayIngestResponse>(`/api/v1/gateway/datasets/${datasetId}/ingest`, {
    method: 'POST',
    body: JSON.stringify({
      target_entity: targetEntity,
      column_overrides: columnOverrides,
    }),
  });
}
