import { apiRequest } from './api';
import { AgentAnalyzeRequest, AgentResponse } from '../types/api';

/**
 * Execute agentic business intelligence analysis via LangGraph.
 */
export async function analyzeBusinessQuery(
  payload: AgentAnalyzeRequest
): Promise<AgentResponse> {
  return apiRequest<AgentResponse>('/api/v1/agent/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
