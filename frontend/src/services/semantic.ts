import { apiRequest, buildQueryString } from './api';
import {
  BusinessUnderstandingResponse,
  KPIResponse,
  SemanticActivationRequest,
  SemanticActivationResponse,
  SemanticDiffResponse,
  SemanticModifyRequest,
  SemanticReviewActionRequest,
  SemanticReviewActionResponse,
  SemanticRevisionSummary,
  SemanticResolveResponse,
} from '../types/api';

/**
 * List all approved KPIs from the Semantic Layer ontology.
 */
export async function listKPIs(domain?: string): Promise<KPIResponse[]> {
  const query = buildQueryString(domain ? { domain } : undefined);
  return apiRequest<KPIResponse[]>(`/api/v1/semantic/kpis${query}`);
}

/**
 * Get details for a specific canonical KPI.
 */
export async function getKPIByName(canonicalName: string): Promise<KPIResponse> {
  return apiRequest<KPIResponse>(`/api/v1/semantic/kpis/${encodeURIComponent(canonicalName)}`);
}

/**
 * Resolve natural language terminology against the ontology (tenant-aware).
 */
export async function resolveTerminology(
  query: string,
  businessId?: string
): Promise<SemanticResolveResponse> {
  const qStr = buildQueryString(businessId ? { business_id: businessId } : undefined);
  return apiRequest<SemanticResolveResponse>(`/api/v1/semantic/resolve${qStr}`, {
    method: 'POST',
    body: JSON.stringify({ query }),
  });
}

/**
 * Fetch deterministic Business Understanding for current tenant business.
 */
export async function getBusinessUnderstanding(
  businessId?: string
): Promise<BusinessUnderstandingResponse> {
  const qStr = buildQueryString(businessId ? { business_id: businessId } : undefined);
  return apiRequest<BusinessUnderstandingResponse>(`/api/v1/semantic/understanding${qStr}`);
}

/**
 * Manually activate or refresh Business Understanding for tenant business.
 */
export async function activateBusinessUnderstanding(
  payload: SemanticActivationRequest = {},
  businessId?: string
): Promise<SemanticActivationResponse> {
  const qStr = buildQueryString(businessId ? { business_id: businessId } : undefined);
  return apiRequest<SemanticActivationResponse>(`/api/v1/semantic/activate${qStr}`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * List historical semantic revisions for tenant business.
 */
export async function listSemanticRevisions(
  businessId?: string
): Promise<SemanticRevisionSummary[]> {
  const qStr = buildQueryString(businessId ? { business_id: businessId } : undefined);
  return apiRequest<SemanticRevisionSummary[]>(`/api/v1/semantic/revisions${qStr}`);
}

/**
 * Fetch detected semantic conflicts requiring human operator review.
 */
export async function getSemanticConflicts(
  businessId?: string
): Promise<Array<Record<string, any>>> {
  const qStr = buildQueryString(businessId ? { business_id: businessId } : undefined);
  return apiRequest<Array<Record<string, any>>>(`/api/v1/semantic/conflicts${qStr}`);
}

/**
 * Fetch detailed representation for a specific semantic model revision.
 */
export async function getSemanticRevisionDetail(
  revisionId: string,
  businessId?: string
): Promise<BusinessUnderstandingResponse> {
  const qStr = buildQueryString(businessId ? { business_id: businessId } : undefined);
  return apiRequest<BusinessUnderstandingResponse>(
    `/api/v1/semantic/revisions/${encodeURIComponent(revisionId)}${qStr}`
  );
}

/**
 * Compute deterministic diff between proposed revision and active or base revision.
 */
export async function getSemanticRevisionDiff(
  revisionId: string,
  baseRevisionId?: string,
  businessId?: string
): Promise<SemanticDiffResponse> {
  const params: Record<string, string> = {};
  if (baseRevisionId) params.base_revision_id = baseRevisionId;
  if (businessId) params.business_id = businessId;
  const qStr = buildQueryString(Object.keys(params).length > 0 ? params : undefined);
  return apiRequest<SemanticDiffResponse>(
    `/api/v1/semantic/revisions/${encodeURIComponent(revisionId)}/diff${qStr}`
  );
}

/**
 * Approve a proposed semantic revision and atomically activate it.
 */
export async function approveSemanticRevision(
  revisionId: string,
  payload: SemanticReviewActionRequest = {},
  businessId?: string
): Promise<SemanticReviewActionResponse> {
  const qStr = buildQueryString(businessId ? { business_id: businessId } : undefined);
  return apiRequest<SemanticReviewActionResponse>(
    `/api/v1/semantic/revisions/${encodeURIComponent(revisionId)}/approve${qStr}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  );
}

/**
 * Reject a proposed semantic revision, preserving current active model.
 */
export async function rejectSemanticRevision(
  revisionId: string,
  payload: SemanticReviewActionRequest = {},
  businessId?: string
): Promise<SemanticReviewActionResponse> {
  const qStr = buildQueryString(businessId ? { business_id: businessId } : undefined);
  return apiRequest<SemanticReviewActionResponse>(
    `/api/v1/semantic/revisions/${encodeURIComponent(revisionId)}/reject${qStr}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  );
}

/**
 * Modify proposed definitions and generate a new immutable revision for review.
 */
export async function modifySemanticRevision(
  revisionId: string,
  payload: SemanticModifyRequest,
  businessId?: string
): Promise<SemanticReviewActionResponse> {
  const qStr = buildQueryString(businessId ? { business_id: businessId } : undefined);
  return apiRequest<SemanticReviewActionResponse>(
    `/api/v1/semantic/revisions/${encodeURIComponent(revisionId)}/modify${qStr}`,
    {
      method: 'POST',
      body: JSON.stringify(payload),
    }
  );
}
