import { apiRequest } from './api';
import { DocumentSummaryResponse, KnowledgeSearchResponse } from '../types/api';

/**
 * List all indexed business context documents.
 */
export async function listDocuments(): Promise<DocumentSummaryResponse[]> {
  return apiRequest<DocumentSummaryResponse[]>('/api/v1/knowledge/documents');
}

/**
 * Search business context via hybrid vector + fulltext search.
 */
export async function searchKnowledge(
  query: string,
  top_k: number = 3,
  domain_filter?: string
): Promise<KnowledgeSearchResponse> {
  return apiRequest<KnowledgeSearchResponse>('/api/v1/knowledge/search', {
    method: 'POST',
    body: JSON.stringify({
      query,
      top_k,
      domain_filter,
    }),
  });
}
