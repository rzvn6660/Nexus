import { apiRequest, buildQueryString } from './api';
import {
  BusinessUnderstandingResponse,
  KPIResponse,
  SemanticActivationRequest,
  SemanticActivationResponse,
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
