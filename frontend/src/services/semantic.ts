import { apiRequest, buildQueryString } from './api';
import { KPIResponse, SemanticResolveResponse } from '../types/api';

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
 * Resolve natural language terminology against the ontology.
 */
export async function resolveTerminology(query: string): Promise<SemanticResolveResponse> {
  return apiRequest<SemanticResolveResponse>('/api/v1/semantic/resolve', {
    method: 'POST',
    body: JSON.stringify({ query }),
  });
}
