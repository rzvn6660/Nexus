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
