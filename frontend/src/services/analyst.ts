/**
 * Frontend Service for NEXUS Adaptive Analyst Engine & PostgreSQL Onboarding.
 */

import { apiRequest, buildQueryString } from './api';

export interface SkillMetadata {
  skill_id: string;
  name: string;
  description: string;
  domain: string;
  version: string;
  activation_conditions: string[];
  required_input_data: string[];
  required_data_quality: number;
  methodology: string;
  confidence_methodology: string;
  known_limitations: string[];
  evidence_requirements: string[];
  enabled: boolean;
  test_coverage: string;
}

export interface AnalystOverviewResponse {
  total_registered_skills: number;
  active_skill_versions: number;
  total_analysis_runs: number;
  success_rate_pct: number;
  data_readiness_status: string;
  current_workload: string;
  skills_by_domain: Record<string, number>;
  recent_runs: Array<{
    id: number;
    request_id: string;
    query: string;
    intent: string;
    status: string;
    answer_preview: string;
    tools_used: string[];
    execution_time_ms: number;
    created_at: string;
  }>;
}

export interface LeadAnalystReportPayload {
  executive_answer: string;
  key_findings: string[];
  supporting_evidence: Record<string, any>;
  relevant_calculations: Array<{ formula?: string; metric?: string; result?: any; value?: any }>;
  contributing_factors: string[];
  confidence_score: number;
  uncertainty_level: string;
  confidence_rationale: string;
  limitations: string[];
  recommended_next_action: string;
  validation_status: string;
  formatted_markdown: string;
}

export interface ExecutionPlanPayload {
  query: string;
  detected_intent: string;
  target_entities: string[];
  selected_skill_ids: string[];
  execution_order: string[];
  routing_rationale: string;
}

export interface AnalystRunResult {
  run_id: number;
  request_id: string;
  query: string;
  intent: string;
  execution_plan: ExecutionPlanPayload;
  lead_analyst_report: LeadAnalystReportPayload;
  skills_used: string[];
  execution_time_ms: number;
  data_readiness: string;
}

export interface PostgresConfig {
  host: string;
  port: number;
  database: string;
  user: string;
  password?: string;
  sslmode?: string;
}

export interface PostgresTableSummary {
  schema: string;
  table: string;
  full_name: string;
  columns: Array<{ name: string; data_type: string; is_nullable: boolean }>;
  column_count: number;
}

export interface PostgresPreviewResponse {
  schema: string;
  table: string;
  total_rows: number;
  columns: string[];
  sample_rows: Array<Record<string, any>>;
}

export interface PostgresIngestPayload extends PostgresConfig {
  table_name: string;
  schema_name?: string;
  target_entity: string;
  column_mapping: Record<string, string>;
  max_rows?: number;
}

export interface PostgresIngestResponse {
  success: boolean;
  target_entity: string;
  total_rows_read: number;
  inserted_count: number;
  skipped_duplicates: number;
  rejected_count: number;
  rejected_records: Array<{ row_index: number; reason: string; data: any }>;
  readiness_status: string;
}

export const getAnalystOverview = async (): Promise<AnalystOverviewResponse> => {
  return apiRequest<AnalystOverviewResponse>('/api/v1/analyst/overview');
};

export const listAnalystSkills = async (domain?: string): Promise<SkillMetadata[]> => {
  const query = buildQueryString(domain ? { domain } : undefined);
  return apiRequest<SkillMetadata[]>(`/api/v1/analyst/skills${query}`);
};

export const toggleAnalystSkill = async (skillId: string, enabled: boolean): Promise<any> => {
  return apiRequest(`/api/v1/analyst/skills/${skillId}/toggle`, {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  });
};

export const analyzeAnalystQuestion = async (query: string): Promise<AnalystRunResult> => {
  return apiRequest<AnalystRunResult>('/api/v1/analyst/analyze', {
    method: 'POST',
    body: JSON.stringify({ query }),
  });
};

export const listAnalysisRuns = async (limit: number = 50): Promise<any[]> => {
  const query = buildQueryString({ limit });
  return apiRequest<any[]>(`/api/v1/analyst/runs${query}`);
};

export const getAnalysisRunDetail = async (runId: number): Promise<any> => {
  return apiRequest<any>(`/api/v1/analyst/runs/${runId}`);
};

// PostgreSQL Onboarding APIs
export const testPostgresConnection = async (config: PostgresConfig): Promise<any> => {
  return apiRequest('/api/v1/analyst/onboard/postgres/test', {
    method: 'POST',
    body: JSON.stringify(config),
  });
};

export const inspectPostgresTables = async (config: PostgresConfig): Promise<PostgresTableSummary[]> => {
  return apiRequest<PostgresTableSummary[]>('/api/v1/analyst/onboard/postgres/inspect', {
    method: 'POST',
    body: JSON.stringify(config),
  });
};

export const previewPostgresTable = async (
  config: PostgresConfig,
  tableName: string,
  schemaName: string = 'public',
  limit: number = 15
): Promise<PostgresPreviewResponse> => {
  return apiRequest<PostgresPreviewResponse>('/api/v1/analyst/onboard/postgres/preview', {
    method: 'POST',
    body: JSON.stringify({
      ...config,
      table_name: tableName,
      schema_name: schemaName,
      limit,
    }),
  });
};

export const ingestPostgresTable = async (payload: PostgresIngestPayload): Promise<PostgresIngestResponse> => {
  return apiRequest<PostgresIngestResponse>('/api/v1/analyst/onboard/postgres/ingest', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
};
