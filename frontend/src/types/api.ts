/**
 * Core TypeScript definitions for NEXUS API interfaces.
 * Maps 1:1 with FastAPI backend schemas across Phases 1 through 7.
 */

// ==========================================
// 1. System Health & Infrastructure
// ==========================================

export interface DatabaseHealth {
  status: 'connected' | 'disconnected' | 'unknown';
  latency_ms?: number | null;
  error?: string | null;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  environment: string;
  timestamp: string;
  database?: DatabaseHealth | null;
}

// ==========================================
// 2. Evidence & Provenance
// ==========================================

export interface EvidenceRecord {
  evidence_id: string;
  calculation_type: string;
  source_tables: string[];
  source_columns: string[];
  filter_predicates: Record<string, any>;
  period_start?: string | null;
  period_end?: string | null;
  row_count: number;
  parameters_used: Record<string, any>;
  mathematical_formula: string;
  execution_time_ms: number;
  generated_at: string;
  checksum: string;
}

export interface RAGEvidence {
  evidence_id: string;
  query: string;
  document_title: string;
  document_source: string;
  business_domain: string;
  chunk_index: number;
  content: string;
  relevance_score: number;
  retrieval_method: string;
  retrieved_at: string;
}

// ==========================================
// 3. Deterministic Analytics Engine
// ==========================================

export interface SummaryMetricItem {
  value: number;
  previous_value?: number | null;
  absolute_change?: number | null;
  percentage_change?: number | null;
}

export interface SummaryData {
  gross_revenue: SummaryMetricItem;
  discounts: SummaryMetricItem;
  returns: SummaryMetricItem;
  net_revenue: SummaryMetricItem;
  cogs: SummaryMetricItem;
  gross_profit: SummaryMetricItem;
  operating_expenses: SummaryMetricItem;
  operating_profit: SummaryMetricItem;
  orders_count: SummaryMetricItem;
  average_order_value: SummaryMetricItem;
  units_sold: SummaryMetricItem;
  customers_count: SummaryMetricItem;
  gross_margin_pct?: number | null;
  operating_margin_pct?: number | null;
}

export interface SummaryResponse {
  success: boolean;
  data: SummaryData;
  evidence: EvidenceRecord;
}

export interface TimeSeriesPoint {
  period_start: string;
  period_end: string;
  period_label: string;
  value: number;
  comparison_value?: number | null;
  growth_rate?: number | null;
  moving_average?: number | null;
}

export interface TimeSeriesData {
  metric: string;
  granularity: string;
  points: TimeSeriesPoint[];
  summary: {
    total_value: number;
    average_value: number;
    min_value: number;
    max_value: number;
    overall_growth_rate?: number | null;
  };
}

export interface TimeSeriesResponse {
  success: boolean;
  data: TimeSeriesData;
  evidence: EvidenceRecord;
}

export interface ProductRankingItem {
  rank: number;
  product_id: number;
  product_name: string;
  sku: string;
  category: string;
  metric_value: number;
  metric_name: string;
  units_sold: number;
  revenue: number;
  gross_profit: number;
  margin_pct: number;
}

export interface ProductRankingResponse {
  success: boolean;
  data: {
    ranking_metric: string;
    total_products_evaluated: number;
    items: ProductRankingItem[];
  };
  evidence: EvidenceRecord;
}

export interface BreakdownItem {
  dimension_value: string;
  metric_value: number;
  percentage_of_total: number;
  order_count?: number;
  unit_count?: number;
}

export interface BreakdownResponse {
  success: boolean;
  data: {
    dimension: string;
    metric: string;
    total_value: number;
    items: BreakdownItem[];
  };
  evidence: EvidenceRecord;
}

export interface InventoryOverviewData {
  total_skus: number;
  total_inventory_value: number;
  low_stock_items_count: number;
  out_of_stock_items_count: number;
  reorder_needed_items_count: number;
  warehouses: string[];
}

export interface InventoryOverviewResponse {
  success: boolean;
  data: InventoryOverviewData;
  evidence: EvidenceRecord;
}

// ==========================================
// 4. LangGraph Agent Analytics
// ==========================================

export interface AgentAnalyzeRequest {
  query: string;
  explanation_level?: string;
  reference_date?: string | null;
  is_investigation?: boolean;
  is_forecast?: boolean;
}

export interface AgentExecutionMetadata {
  request_id: string;
  elapsed_ms: float;
  iterations: number;
  tool_call_count: number;
  tools_executed: string[];
  evidence_status: string;
  timestamp: string;
}

export interface AgentResponse {
  answer: string;
  intent: string;
  explanation_level: string;
  evidence: EvidenceRecord[];
  rag_evidence: RAGEvidence[];
  semantic_context?: Record<string, any> | null;
  diagnostic_summary?: Record<string, any> | null;
  forecast_summary?: Record<string, any> | null;
  calculations: Array<Record<string, any>>;
  assumptions: string[];
  limitations: string[];
  tools_used: string[];
  follow_up_questions: string[];
  needs_clarification: boolean;
  clarification_prompt?: string | null;
  status: string;
  execution_metadata: AgentExecutionMetadata;
}

// ==========================================
// 5. Diagnostic Investigation Engine
// ==========================================

export interface InvestigationObservation {
  observation_id: string;
  metric: string;
  dimension?: string | null;
  period: string;
  observed_value: number;
  baseline_value: number;
  variance_amount: number;
  variance_pct: number;
  is_material: boolean;
  finding: string;
}

export interface InvestigationHypothesis {
  hypothesis_id: string;
  statement: string;
  status: 'confirmed' | 'rejected' | 'inconclusive';
  confidence: number;
  support_score: number;
  evidence_summary: string;
  evidence_ids: string[];
}

export interface InvestigationConclusion {
  conclusion_id: string;
  statement: string;
  primary_driver: string;
  contributing_factors: string[];
  confidence_rating: 'high' | 'medium' | 'low';
  causality_caveat: string;
}

export interface InvestigationStep {
  step_number: number;
  action_type: string;
  description: string;
  tool_invoked: string;
  findings: string;
}

export interface EvidenceGap {
  gap_id: string;
  area: string;
  description: string;
  impact_assessment: string;
}

export interface InvestigationRequest {
  query: string;
  explanation_level?: string;
  reference_date?: string | null;
}

export interface InvestigationResponse {
  status: string;
  question: string;
  summary: string;
  investigation_type: string;
  observations: InvestigationObservation[];
  hypotheses: InvestigationHypothesis[];
  conclusions: InvestigationConclusion[];
  evidence: EvidenceRecord[];
  rag_evidence: RAGEvidence[];
  evidence_gaps: EvidenceGap[];
  assumptions: string[];
  limitations: string[];
  tools_used: string[];
  investigation_steps: InvestigationStep[];
  stopped_reason: string;
  follow_up_questions: string[];
  explanation: string;
}

// ==========================================
// 6. Predictive Intelligence & Forecasting
// ==========================================

export interface ForecastDataQuality {
  status: 'READY' | 'READY_WITH_WARNINGS' | 'INSUFFICIENT_DATA' | 'INVALID';
  observation_count: number;
  frequency: string;
  date_from?: string | null;
  date_to?: string | null;
  missing_periods: number;
  missing_values: number;
  warnings: string[];
  blocking_reasons: string[];
}

export interface EvaluationMetrics {
  mae: number;
  rmse: number;
  smape: number;
  mape?: number | null;
  wape?: number | null;
}

export interface ForecastPredictionPoint {
  period: string;
  period_start: string;
  period_end: string;
  point_forecast: number;
  lower_bound: number;
  upper_bound: number;
  confidence_level: number;
}

export interface ForecastModelInfo {
  name: string;
  version: string;
  model_type: string;
  parameters: Record<string, any>;
  is_baseline: boolean;
}

export interface ForecastEvidence {
  forecast_id: string;
  request_id: string;
  target_metric: string;
  frequency: string;
  forecast_horizon: number;
  source_tables: string[];
  source_columns: string[];
  filter_predicates: Record<string, any>;
  training_range_start: string;
  training_range_end: string;
  forecast_range_start: string;
  forecast_range_end: string;
  selected_model: string;
  model_version: string;
  model_parameters: Record<string, any>;
  validation_method: string;
  validation_metrics: EvaluationMetrics;
  candidate_evaluations: Record<string, EvaluationMetrics>;
  selection_reason: string;
  assumptions: string[];
  limitations: string[];
  data_quality_status: string;
  generated_at: string;
}

export interface ForecastRequest {
  target_metric?: string;
  entity_type?: string | null;
  entity_id?: string | null;
  forecast_horizon?: number;
  frequency?: string;
  model_policy?: 'validated_best' | 'baseline_only' | 'specific_model';
  specific_model?: string | null;
  confidence_level?: number;
}

export interface ForecastAnalyzeRequest {
  query: string;
  explanation_level?: string;
  reference_date?: string | null;
}

export interface ForecastResponse {
  status: 'completed' | 'insufficient_data' | 'unavailable' | 'error';
  target_metric: string;
  entity_type?: string | null;
  entity_id?: string | null;
  frequency: string;
  training_period: {
    from: string;
    to: string;
  };
  forecast_period: {
    from: string;
    to: string;
  };
  model: ForecastModelInfo;
  predictions: ForecastPredictionPoint[];
  evaluation: EvaluationMetrics;
  data_quality: ForecastDataQuality;
  evidence: ForecastEvidence;
  assumptions: string[];
  limitations: string[];
  explanation: string;
}

// ==========================================
// 7. Data Layer & Profiling
// ==========================================

export interface DataHealthResponse {
  status: string;
  layer: string;
  registered_models: number;
  tables: string[];
  total_records: number;
}

export interface TableSummary {
  table_name: string;
  row_count: number;
  column_count: number;
  columns: Array<{
    name: string;
    type: string;
    nullable: boolean;
  }>;
}

export interface ColumnProfile {
  column_name: string;
  data_type: string;
  null_count: number;
  null_percentage: number;
  distinct_count: number;
  min_value?: any;
  max_value?: any;
}

export interface DatasetProfile {
  table_name: string;
  row_count: number;
  column_count: number;
  columns: Record<string, ColumnProfile>;
  generated_at: string;
}

export interface QualityRuleResult {
  rule_id: string;
  rule_name: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  status: 'passed' | 'warning' | 'failed';
  message: string;
  violation_count: number;
}

export interface QualityReport {
  dataset: string;
  overall_status: 'passed' | 'warning' | 'failed';
  total_rules: number;
  passed_rules: number;
  failed_rules: number;
  rule_results: QualityRuleResult[];
  audited_at: string;
}

// ==========================================
// 8. Semantic Layer & KPI Catalog
// ==========================================

export interface KPIResponse {
  canonical_name: string;
  display_name: string;
  description: string;
  synonyms: string[];
  analytics_tool: string;
  metric_field: string;
  calculation_reference: string;
  unit: string;
  business_domain: string;
  status: string;
}

export interface SemanticResolveResponse {
  query: string;
  resolved_kpi?: KPIResponse | null;
  canonical_name?: string | null;
  analytics_tool?: string | null;
  metric_field?: string | null;
  is_ambiguous: boolean;
  candidate_kpis: KPIResponse[];
  is_supported: boolean;
  unsupported_message?: string | null;
  clarification_prompt?: string | null;
  matched_synonym?: string | null;
}

// ==========================================
// 9. Knowledge & Business Context RAG
// ==========================================

export interface DocumentSummaryResponse {
  id: string;
  title: string;
  business_domain: string;
  version: string;
  source: string;
  chunk_count: number;
  created_at: string;
  tags: string[];
}

export interface KnowledgeSearchResponse {
  query: string;
  top_k: number;
  domain_filter?: string | null;
  results: Array<{
    document_title: string;
    business_domain: string;
    content: string;
    score: number;
  }>;
}

// Alias for numeric compatibility
type float = number;
