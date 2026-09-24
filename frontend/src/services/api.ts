import { HealthResponse } from '../types/api';

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

/**
 * Fetch system health status from NEXUS backend.
 */
export async function getHealthStatus(): Promise<HealthResponse> {
  const response = await fetch(`${API_BASE_URL}/api/health`, {
    headers: {
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`API health check failed with status: ${response.status}`);
  }

  return response.json();
}
