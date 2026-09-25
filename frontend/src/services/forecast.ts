import { apiRequest } from './api';
import {
  ForecastAnalyzeRequest,
  ForecastRequest,
  ForecastResponse,
} from '../types/api';

/**
 * Generate structured time-series forecast with backtesting and prediction intervals.
 */
export async function generateStructuredForecast(
  payload: ForecastRequest
): Promise<ForecastResponse> {
  return apiRequest<ForecastResponse>('/api/v1/forecast', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Natural language forecast analysis endpoint.
 */
export async function analyzeForecastQuery(
  payload: ForecastAnalyzeRequest
): Promise<ForecastResponse> {
  return apiRequest<ForecastResponse>('/api/v1/forecast/analyze', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
