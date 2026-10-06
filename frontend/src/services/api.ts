/**
 * Unified API Client for NEXUS Backend.
 * Handles base URL routing, error normalization, request tracing, and JSON deserialization.
 */

const API_BASE_URL = import.meta.env.VITE_API_URL || '';

export class ApiError extends Error {
  status: number;
  data: any;

  constructor(message: string, status: number, data?: any) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

/**
 * Serialize URL query parameters cleanly.
 */
export function buildQueryString(params?: Record<string, any>): string {
  if (!params) return '';
  const searchParams = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') {
      if (Array.isArray(value)) {
        value.forEach((v) => searchParams.append(key, String(v)));
      } else {
        searchParams.append(key, String(value));
      }
    }
  }
  const str = searchParams.toString();
  return str ? `?${str}` : '';
}

/**
 * Generic request executor.
 */
export async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE_URL}${endpoint.startsWith('/') ? endpoint : `/${endpoint}`}`;

  const headers: Record<string, string> = {
    'Accept': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  const authToken = typeof window !== 'undefined' ? localStorage.getItem('nexus_access_token') : null;
  if (authToken && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }

  const activeBizId = typeof window !== 'undefined' ? localStorage.getItem('nexus_business_id') : null;
  if (activeBizId && !headers['X-Business-ID']) {
    headers['X-Business-ID'] = activeBizId;
  }

  const apiKey =
    (typeof window !== 'undefined' ? localStorage.getItem('nexus_api_key') : null) ||
    import.meta.env.VITE_API_KEY ||
    'nexus-dev-key-change-in-production';

  if (apiKey && !headers['X-API-Key'] && !headers['Authorization']) {
    headers['X-API-Key'] = apiKey;
  }

  if (!(options.body instanceof FormData)) {
    if (!headers['Content-Type']) {
      headers['Content-Type'] = 'application/json';
    }
  } else {
    delete headers['Content-Type'];
  }

  try {
    const response = await fetch(url, {
      ...options,
      headers,
    });

    if (!response.ok) {
      let errorData: any = null;
      let errorMessage = `HTTP error ${response.status}: ${response.statusText}`;

      try {
        errorData = await response.json();
        if (errorData?.detail) {
          errorMessage = typeof errorData.detail === 'string'
            ? errorData.detail
            : JSON.stringify(errorData.detail);
        } else if (errorData?.message) {
          errorMessage = errorData.message;
        }
      } catch {
        // Response was not JSON
      }

      throw new ApiError(errorMessage, response.status, errorData);
    }

    return await response.json();
  } catch (err: any) {
    if (err instanceof ApiError) {
      throw err;
    }
    throw new ApiError(err?.message || 'Network error communicating with NEXUS backend', 0);
  }
}

/**
 * Health check endpoint.
 */
export async function getHealthStatus(): Promise<import('../types/api').HealthResponse> {
  return apiRequest('/api/v1/health');
}

/**
 * Phase 15 SaaS Onboarding & Business APIs
 */
export interface OnboardingStatusResponse {
  step?: string;
  is_complete?: boolean;
  business_id?: string;
  business_name?: string;
  onboarding_step?: string;
  data_readiness_status?: string;
  business?: {
    id: string;
    name: string;
    data_readiness_status?: string;
    onboarding_step?: string;
    industry?: string;
    country?: string;
    currency?: string;
    timezone?: string;
    business_type?: string;
    fiscal_year_start?: number;
  };
  datasets?: Array<{
    id: string;
    filename: string;
    file_type: string;
    row_count: number;
    column_count: number;
    readiness_status: string;
    quality_report?: any;
    schema_info?: any;
  }>;
  data_readiness?: {
    status: string;
    total_datasets: number;
    total_rows: number;
    domains_covered: string[];
    summary: string;
    datasets: Array<any>;
  };
}

export async function getOnboardingStatus(): Promise<OnboardingStatusResponse> {
  return apiRequest<OnboardingStatusResponse>('/api/v1/onboarding/status');
}

export async function saveOnboardingBusiness(data: {
  business_id?: string;
  name: string;
  industry?: string;
  country?: string;
  currency?: string;
  timezone?: string;
  business_type?: string;
  fiscal_year_start?: number;
}): Promise<any> {
  return apiRequest('/api/v1/onboarding/business', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function saveOnboardingContext(data: {
  rules?: Array<{ name: string; rule_type: string; rule_logic: string; priority?: number }>;
  terms?: Array<{ term: string; definition: string }>;
  kpis?: Array<{ name: string; calculation: string; target?: number }>;
  notes?: string;
}): Promise<any> {
  return apiRequest('/api/v1/onboarding/context', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function uploadOnboardingData(file: File): Promise<any> {
  const formData = new FormData();
  formData.append('file', file);
  return apiRequest('/api/v1/onboarding/data', {
    method: 'POST',
    body: formData,
  });
}

export async function completeOnboarding(): Promise<any> {
  return apiRequest('/api/v1/onboarding/complete', {
    method: 'POST',
  });
}

export async function listBusinesses(): Promise<any[]> {
  return apiRequest<any[]>('/api/v1/businesses/');
}

export async function createBusiness(data: {
  name: string;
  industry?: string;
  country?: string;
  currency?: string;
  timezone?: string;
  business_type?: string;
  fiscal_year_start?: number;
}): Promise<any> {
  return apiRequest('/api/v1/businesses/', {
    method: 'POST',
    body: JSON.stringify(data),
  });
}

export async function getBusiness(id: string): Promise<any> {
  return apiRequest(`/api/v1/businesses/${id}`);
}

export async function updateBusiness(id: string, data: any): Promise<any> {
  return apiRequest(`/api/v1/businesses/${id}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });
}
