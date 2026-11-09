/**
 * API client service for NEXUS Pulse (Management Intelligence & Automated Reporting).
 */

import { apiRequest, buildQueryString } from './api';
import { AuthService } from './auth';
import {
  PulseChannelConfigureRequest,
  PulseChannelStatusItem,
  PulseDashboardOverview,
  PulseDeliveryChannel,
  PulseDeliveryLogItem,
  PulseDestinationVerifyRequest,
  PulseDestinationVerifyResponse,
  PulseGenerateReportRequest,
  PulseRecipientItem,
  PulseRecipientOptRequest,
  PulseReportDetail,
  PulseReportListItem,
  PulseScheduleCreateRequest,
  PulseScheduleResponse,
  PulseScheduleUpdateRequest,
  PulseTestDispatchRequest,
} from '../types/api';

export interface PulseDashboardFilterParams {
  date_from?: string;
  date_to?: string;
  comparison_date_from?: string;
  comparison_date_to?: string;
}

/**
 * Fetch Executive Dashboard Overview with aggregated KPIs, insights, trends, and risk distributions.
 */
export async function getPulseDashboard(
  params?: PulseDashboardFilterParams
): Promise<PulseDashboardOverview> {
  const query = buildQueryString(params);
  return apiRequest<PulseDashboardOverview>(`/api/v1/pulse/dashboard${query}`);
}

/**
 * Trigger manual ad-hoc report generation with full PDF and digital format.
 */
export async function generatePulseReport(
  payload: PulseGenerateReportRequest
): Promise<{
  success: boolean;
  data: {
    report_id: string;
    report_title: string;
    report_type: string;
    access_token: string;
    token_expires_at: string;
    created_at?: string;
  };
}> {
  return apiRequest('/api/v1/pulse/reports/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * List past generated management intelligence reports.
 */
export async function listPulseReports(
  page: number = 1,
  pageSize: number = 20
): Promise<{
  success: boolean;
  data: {
    items: PulseReportListItem[];
    total_count: number;
    page: number;
    page_size: number;
  };
}> {
  const query = buildQueryString({ page, page_size: pageSize });
  return apiRequest(`/api/v1/pulse/reports${query}`);
}

/**
 * Fetch full digital report detail including structured KPI breakdown, executive prose, and metadata.
 */
export async function getPulseReportDetail(reportId: string): Promise<PulseReportDetail> {
  return apiRequest<PulseReportDetail>(`/api/v1/pulse/reports/${encodeURIComponent(reportId)}`);
}

/**
 * Download high-fidelity ReportLab PDF for a report (Authenticated & Tenant Authorized).
 */
export async function downloadPulseReportPdf(
  reportId: string,
  filename: string = 'NEXUS_Pulse_Report.pdf'
): Promise<void> {
  const token = AuthService.getToken() || (typeof window !== 'undefined' ? localStorage.getItem('nexus_access_token') : null);
  const bizId = AuthService.getActiveBusinessId() || (typeof window !== 'undefined' ? localStorage.getItem('nexus_business_id') : null);
  const apiKey = (typeof window !== 'undefined' ? localStorage.getItem('nexus_api_key') : null) || import.meta.env.VITE_API_KEY;

  const headers: Record<string, string> = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;
  if (bizId) headers['X-Business-ID'] = bizId;
  if (apiKey && !headers['Authorization']) headers['X-API-Key'] = apiKey;

  const url = `/api/v1/pulse/reports/${encodeURIComponent(reportId)}/pdf`;
  const response = await fetch(url, { headers });
  if (!response.ok) {
    let detail = '';
    try {
      const errJson = await response.json();
      detail = errJson.detail || '';
    } catch {
      // response is not JSON
    }
    const suffix = detail ? `: ${detail}` : '';
    throw new Error(`Failed to download report PDF (${response.status})${suffix}`);
  }

  const blob = await response.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = downloadUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(downloadUrl);
}

/**
 * Download high-fidelity ReportLab PDF for a public report using secure expiring token.
 */
export async function downloadPublicPulseReportPdf(
  token: string,
  filename: string = 'NEXUS_Pulse_Report.pdf'
): Promise<void> {
  const url = `/api/v1/pulse/public/reports/${encodeURIComponent(token)}/pdf`;
  const response = await fetch(url);
  if (!response.ok) {
    let detail = '';
    try {
      const errJson = await response.json();
      detail = errJson.detail || '';
    } catch {
      // response is not JSON
    }
    const suffix = detail ? `: ${detail}` : '';
    throw new Error(`Failed to download public report PDF (${response.status})${suffix}`);
  }

  const blob = await response.blob();
  const downloadUrl = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = downloadUrl;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(downloadUrl);
}

/**
 * Access public token-authorized report without requiring session authentication.
 */
export async function getPublicPulseReport(token: string): Promise<PulseReportDetail> {
  return apiRequest<PulseReportDetail>(`/api/v1/pulse/public/reports/${encodeURIComponent(token)}`);
}

/**
 * List configured report automation schedules.
 */
export async function listPulseSchedules(): Promise<PulseScheduleResponse[]> {
  return apiRequest<PulseScheduleResponse[]>('/api/v1/pulse/schedules');
}

/**
 * Create a new automated recurring report schedule.
 */
export async function createPulseSchedule(
  payload: PulseScheduleCreateRequest
): Promise<PulseScheduleResponse> {
  return apiRequest<PulseScheduleResponse>('/api/v1/pulse/schedules', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Update an existing report schedule (e.g. pause, resume, change cadence or recipients).
 */
export async function updatePulseSchedule(
  scheduleId: number,
  payload: PulseScheduleUpdateRequest
): Promise<PulseScheduleResponse> {
  return apiRequest<PulseScheduleResponse>(`/api/v1/pulse/schedules/${scheduleId}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

/**
 * Delete a report automation schedule.
 */
export async function deletePulseSchedule(
  scheduleId: number
): Promise<{ success: boolean; message: string }> {
  return apiRequest(`/api/v1/pulse/schedules/${scheduleId}`, {
    method: 'DELETE',
  });
}

/**
 * Dispatch test notification through WhatsApp, Telegram, or Email.
 */
export async function sendPulseTestDispatch(
  payload: PulseTestDispatchRequest
): Promise<PulseDeliveryLogItem> {
  return apiRequest<PulseDeliveryLogItem>('/api/v1/pulse/dispatch/test', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * List multi-channel notification delivery audit logs.
 */
export async function listPulseDeliveries(
  reportId?: string,
  page: number = 1,
  pageSize: number = 50
): Promise<{
  success: boolean;
  data: {
    items: PulseDeliveryLogItem[];
    total_count: number;
    page: number;
    page_size: number;
  };
}> {
  const query = buildQueryString({
    report_id: reportId,
    page,
    page_size: pageSize,
  });
  return apiRequest(`/api/v1/pulse/deliveries${query}`);
}

/**
 * Retry a failed or incomplete report delivery.
 */
export async function retryPulseDelivery(deliveryId: number): Promise<PulseDeliveryLogItem> {
  return apiRequest<PulseDeliveryLogItem>(`/api/v1/pulse/deliveries/${deliveryId}/retry`, {
    method: 'POST',
  });
}

/**
 * List registered report recipients and their opt statuses.
 */
export async function listPulseRecipients(): Promise<PulseRecipientItem[]> {
  return apiRequest<PulseRecipientItem[]>('/api/v1/pulse/recipients');
}

/**
 * Register or update recipient opt status.
 */
export async function updatePulseRecipientOpt(
  payload: PulseRecipientOptRequest
): Promise<PulseRecipientItem> {
  return apiRequest<PulseRecipientItem>('/api/v1/pulse/recipients/opt', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Fetch multi-channel status and connection summary.
 */
export async function getPulseChannelStatuses(): Promise<PulseChannelStatusItem[]> {
  return apiRequest<PulseChannelStatusItem[]>('/api/v1/pulse/channels/status');
}

/**
 * Configure channel credentials or toggle zero-cost local Mailpit.
 */
export async function configurePulseChannel(
  payload: PulseChannelConfigureRequest
): Promise<PulseChannelStatusItem> {
  return apiRequest<PulseChannelStatusItem>('/api/v1/pulse/channels/configure', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

/**
 * Disconnect a channel and revert to safe rehearsal mock.
 */
export async function disconnectPulseChannel(
  channel: PulseDeliveryChannel
): Promise<PulseChannelStatusItem> {
  return apiRequest<PulseChannelStatusItem>(
    `/api/v1/pulse/channels/disconnect?channel=${encodeURIComponent(channel)}`,
    {
      method: 'POST',
    }
  );
}

/**
 * Validate syntax and reachable structure of a recipient destination.
 */
export async function verifyPulseDestination(
  payload: PulseDestinationVerifyRequest
): Promise<PulseDestinationVerifyResponse> {
  return apiRequest<PulseDestinationVerifyResponse>('/api/v1/pulse/channels/verify-destination', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}
