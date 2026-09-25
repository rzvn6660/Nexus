import { apiRequest } from './api';
import { InvestigationRequest, InvestigationResponse } from '../types/api';

/**
 * Execute multi-step diagnostic investigation answering 'Why did this happen?'.
 */
export async function analyzeInvestigation(
  payload: InvestigationRequest
): Promise<InvestigationResponse> {
  return apiRequest<InvestigationResponse>('/api/v1/investigation/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
