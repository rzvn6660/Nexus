import { apiRequest, buildQueryString } from './api';

export interface ConnectorCredentialSummary {
  id: string;
  business_id: string;
  provider: string;
  provider_account_id: string;
  scopes: string[];
  kms_key_id: string;
  status: string;
  created_at: string | null;
  last_rotated_at: string | null;
  credentials_masked: string;
}

export interface RegisterConnectorCredentialRequest {
  business_id: string;
  provider: string;
  provider_account_id: string;
  credentials: Record<string, any>;
  scopes?: string[];
  kms_key_id?: string;
}

export interface CheckpointSummary {
  id: string;
  provider: string;
  sync_mode: string;
  period_start: string;
  period_end: string;
  current_cursor: string | null;
  status: string;
  records_extracted: number;
  worker_id: string | null;
  last_attempt_at: string | null;
  completed_at: string | null;
}

export interface WebhookInboxStatusSummary {
  provider: string;
  total_events: number;
  completed_events: number;
  quarantined_events: number;
  pending_or_processing_events: number;
  failed_events: number;
}

export interface PeriodCloseSubmissionSummary {
  manifest_id: string;
  period_start: string | null;
  period_end: string | null;
  verification_status: string;
  signature_valid: boolean;
  dataset_identity_digest: string;
  db_reconciled: boolean;
  db_reconciled_at: string | null;
  persisted_row_count: number | null;
  persisted_gross_total: string | null;
  version_number: number;
  supersedes_package_id: string | null;
  superseded_by_package_id: string | null;
  is_superseded: boolean;
  created_at: string | null;
}

export interface VerifyHistoricalPackageResult {
  package_id: string;
  version_number: number;
  historical_signature_valid: boolean;
  signing_key_id: string;
  key_valid_at_signing: boolean;
  key_status_at_signing: string;
  current_key_status: string;
  canonical_digest_matches: boolean;
  current_dataset_diverged: boolean;
  divergence_details: string | null;
}

/**
 * List tenant connector credentials with masked secrets.
 */
export async function listConnectorCredentials(
  businessId: string
): Promise<ConnectorCredentialSummary[]> {
  const query = buildQueryString({ business_id: businessId });
  return apiRequest<ConnectorCredentialSummary[]>(`/api/v1/connectors/credentials${query}`);
}

/**
 * Register or rotate a provider credential under envelope encryption.
 */
export async function registerConnectorCredentials(
  payload: RegisterConnectorCredentialRequest
): Promise<ConnectorCredentialSummary> {
  return apiRequest<ConnectorCredentialSummary>('/api/v1/connectors/credentials', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

/**
 * List sync checkpoints for monitoring pagination and worker execution.
 */
export async function listSyncCheckpoints(
  businessId: string,
  provider?: string
): Promise<CheckpointSummary[]> {
  const query = buildQueryString({ business_id: businessId, provider });
  return apiRequest<CheckpointSummary[]>(`/api/v1/connectors/checkpoints${query}`);
}

/**
 * Get durable webhook inbox processing and quarantine summaries.
 */
export async function getWebhookInboxSummary(
  businessId: string
): Promise<WebhookInboxStatusSummary[]> {
  const query = buildQueryString({ business_id: businessId });
  return apiRequest<WebhookInboxStatusSummary[]>(`/api/v1/connectors/webhooks/summary${query}`);
}

/**
 * Get historical signed period-close package submissions.
 */
export async function getPeriodCloseHistory(
  businessId: string
): Promise<PeriodCloseSubmissionSummary[]> {
  const query = buildQueryString({ business_id: businessId });
  return apiRequest<PeriodCloseSubmissionSummary[]>(`/api/v1/connectors/period-close/history${query}`);
}

/**
 * Verify historical package signature and current dataset divergence.
 */
export async function verifyHistoricalPackage(
  manifestId: string,
  businessId: string
): Promise<VerifyHistoricalPackageResult> {
  const query = buildQueryString({ business_id: businessId });
  return apiRequest<VerifyHistoricalPackageResult>(
    `/api/v1/connectors/period-close/${encodeURIComponent(manifestId)}/verify-historical${query}`,
    {
      method: 'POST',
    }
  );
}
