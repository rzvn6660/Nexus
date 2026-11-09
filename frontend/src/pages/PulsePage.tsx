import React, { useState, useEffect, useCallback } from 'react';
import {
  Activity,
  FileText,
  Clock,
  Download,
  Share2,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Plus,
  RotateCw,
  ChevronRight,
  TrendingUp,
  DollarSign,
  Package,
  ShieldCheck,
  AlertOctagon,
  Trash2,
  X,
  Bell,
} from 'lucide-react';
import { NotificationChannelHub } from '../components/settings/NotificationChannelHub';
import {
  getPulseDashboard,
  listPulseReports,
  getPulseReportDetail,
  downloadPulseReportPdf,
  generatePulseReport,
  listPulseSchedules,
  createPulseSchedule,
  updatePulseSchedule,
  deletePulseSchedule,
  listPulseDeliveries,
  retryPulseDelivery,
  listPulseRecipients,
  updatePulseRecipientOpt,
} from '../services/pulse';
import {
  PulseDashboardOverview,
  PulseReportListItem,
  PulseReportDetail,
  PulseScheduleResponse,
  PulseScheduleCreateRequest,
  PulseDeliveryLogItem,
  PulseRecipientItem,
  PulseReportType,
  PulseReportFrequency,
  PulseDeliveryChannel,
} from '../types/api';
import { formatCurrency, formatNumber, formatDate } from '../utils/formatters';
import { LoadingState } from '../components/common/LoadingState';

interface PulsePageProps {
  onNavigate: (route: string) => void;
  onAskQuery?: (query: string) => void;
}

export const PulsePage: React.FC<PulsePageProps> = ({ onNavigate, onAskQuery }) => {
  // Navigation Tabs: 'dashboard' | 'reports' | 'automation' | 'channels' | 'deliveries'
  const [activeTab, setActiveTab] = useState<'dashboard' | 'reports' | 'automation' | 'channels' | 'deliveries'>('dashboard');

  // Dashboard Overview state
  const [dashboard, setDashboard] = useState<PulseDashboardOverview | null>(null);
  const [loadingDashboard, setLoadingDashboard] = useState<boolean>(true);
  const [dashboardError, setDashboardError] = useState<string | null>(null);
  const [dateRangeFilter, setDateRangeFilter] = useState<'30d' | 'month' | 'last_month' | '7d'>('30d');

  // Reports History state
  const [reports, setReports] = useState<PulseReportListItem[]>([]);
  const [reportsTotal, setReportsTotal] = useState<number>(0);
  const [reportsPage, setReportsPage] = useState<number>(1);
  const [loadingReports, setLoadingReports] = useState<boolean>(false);
  const [selectedReportDetail, setSelectedReportDetail] = useState<PulseReportDetail | null>(null);
  const [loadingReportDetail, setLoadingReportDetail] = useState<boolean>(false);

  // Generate Report Modal
  const [showGenerateModal, setShowGenerateModal] = useState<boolean>(false);
  const [genReportType, setGenReportType] = useState<PulseReportType>('MONTHLY_EXECUTIVE');
  const [genPeriodStart, setGenPeriodStart] = useState<string>(
    new Date(Date.now() - 30 * 86400000).toISOString().split('T')[0]
  );
  const [genPeriodEnd, setGenPeriodEnd] = useState<string>(new Date().toISOString().split('T')[0]);
  const [genTitle, setGenTitle] = useState<string>('');
  const [generatingReport, setGeneratingReport] = useState<boolean>(false);

  // Schedules state
  const [schedules, setSchedules] = useState<PulseScheduleResponse[]>([]);
  const [loadingSchedules, setLoadingSchedules] = useState<boolean>(false);
  const [showScheduleModal, setShowScheduleModal] = useState<boolean>(false);
  const [savingSchedule, setSavingSchedule] = useState<boolean>(false);

  // New Schedule form
  const [newScheduleName, setNewScheduleName] = useState<string>('Executive Monthly Brief');
  const [newSchedReportType, setNewSchedReportType] = useState<PulseReportType>('MONTHLY_EXECUTIVE');
  const [newSchedFrequency, setNewSchedFrequency] = useState<PulseReportFrequency>('MONTHLY');
  const [newSchedTime, setNewSchedTime] = useState<string>('09:00');
  const [newSchedTimezone, setNewSchedTimezone] = useState<string>('UTC');
  const [newSchedDayOfMonth, setNewSchedDayOfMonth] = useState<number>(1);
  const [newSchedDayOfWeek, setNewSchedDayOfWeek] = useState<number>(0);
  const [newSchedChannels, setNewSchedChannels] = useState<PulseDeliveryChannel[]>(['EMAIL', 'WHATSAPP']);
  const [newRecipientName, setNewRecipientName] = useState<string>('Executive Leadership');
  const [newRecipientChannel, setNewRecipientChannel] = useState<PulseDeliveryChannel>('EMAIL');
  const [newRecipientDest, setNewRecipientDest] = useState<string>('cfo@company.com');

  // Delivery Logs state
  const [deliveryLogs, setDeliveryLogs] = useState<PulseDeliveryLogItem[]>([]);
  const [loadingLogs, setLoadingLogs] = useState<boolean>(false);

  // Recipient Preferences state
  const [recipients, setRecipients] = useState<PulseRecipientItem[]>([]);

  // Toast notice
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = useCallback((msg: string) => {
    setToastMessage(msg);
    setTimeout(() => {
      setToastMessage(null);
    }, 4000);
  }, []);

  // 1. Fetch Dashboard Overview
  const fetchDashboard = useCallback(async () => {
    setLoadingDashboard(true);
    setDashboardError(null);
    try {
      const now = new Date();
      let start: Date;
      let end = now;

      if (dateRangeFilter === '30d') {
        start = new Date(now.getTime() - 30 * 86400000);
      } else if (dateRangeFilter === '7d') {
        start = new Date(now.getTime() - 7 * 86400000);
      } else if (dateRangeFilter === 'month') {
        start = new Date(now.getFullYear(), now.getMonth(), 1);
      } else {
        // last_month
        start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
        end = new Date(now.getFullYear(), now.getMonth(), 0, 23, 59, 59);
      }

      const data = await getPulseDashboard({
        date_from: start.toISOString(),
        date_to: end.toISOString(),
      });
      setDashboard(data);
    } catch (err: any) {
      setDashboardError(err.message || 'Failed to load executive intelligence overview.');
    } finally {
      setLoadingDashboard(false);
    }
  }, [dateRangeFilter]);

  // 2. Fetch Reports History
  const fetchReports = useCallback(async () => {
    setLoadingReports(true);
    try {
      const res = await listPulseReports(reportsPage, 20);
      if (res.success && res.data) {
        setReports(res.data.items);
        setReportsTotal(res.data.total_count);
      }
    } catch (err: any) {
      console.error('Failed to load pulse reports:', err);
    } finally {
      setLoadingReports(false);
    }
  }, [reportsPage]);

  // 3. Fetch Automation & Deliveries
  const fetchAutomation = useCallback(async () => {
    setLoadingSchedules(true);
    setLoadingLogs(true);
    try {
      const [schedList, delivRes, recipList] = await Promise.all([
        listPulseSchedules(),
        listPulseDeliveries(undefined, 1, 50),
        listPulseRecipients(),
      ]);
      setSchedules(schedList);
      if (delivRes.success && delivRes.data) {
        setDeliveryLogs(delivRes.data.items);
      }
      setRecipients(recipList);
    } catch (err: any) {
      console.error('Failed to load pulse automation metadata:', err);
    } finally {
      setLoadingSchedules(false);
      setLoadingLogs(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab === 'dashboard') {
      fetchDashboard();
    } else if (activeTab === 'reports') {
      fetchReports();
    } else if (activeTab === 'automation' || activeTab === 'channels' || activeTab === 'deliveries') {
      fetchAutomation();
      if (reports.length === 0) {
        fetchReports();
      }
    }
  }, [activeTab, fetchDashboard, fetchReports, fetchAutomation, reports.length]);

  // Handlers
  const handleGenerateReportSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (generatingReport) return;
    setGeneratingReport(true);
    try {
      const idempotencyKey = `gen_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
      const res = await generatePulseReport({
        report_type: genReportType,
        date_from: new Date(genPeriodStart).toISOString(),
        date_to: new Date(genPeriodEnd + 'T23:59:59Z').toISOString(),
        report_title: genTitle.trim() || undefined,
        idempotency_key: idempotencyKey,
      });
      showToast(`Report '${res.data.report_title}' generated successfully!`);
      setShowGenerateModal(false);
      fetchReports();
      setActiveTab('reports');
    } catch (err: any) {
      alert(`Generation failed: ${err.message}`);
    } finally {
      setGeneratingReport(false);
    }
  };

  const handleDownloadPdf = async (reportId: string, title: string) => {
    try {
      const safeFilename = `NEXUS_Pulse_${title.replace(/[^a-zA-Z0-9]/g, '_')}.pdf`;
      await downloadPulseReportPdf(reportId, safeFilename);
      showToast('PDF downloaded successfully.');
    } catch (err: any) {
      alert(`Download failed: ${err.message}`);
    }
  };

  const handleViewReportDetail = async (reportId: string) => {
    setLoadingReportDetail(true);
    try {
      const detail = await getPulseReportDetail(reportId);
      setSelectedReportDetail(detail);
    } catch (err: any) {
      alert(`Failed to load report: ${err.message}`);
    } finally {
      setLoadingReportDetail(false);
    }
  };

  const handleCopyPublicLink = (accessToken: string) => {
    const url = `${window.location.origin}/pulse/public/report?token=${accessToken}`;
    navigator.clipboard.writeText(url);
    showToast('Secure expiring public report link copied to clipboard (valid 30 days).');
  };

  const handleToggleScheduleActive = async (sched: PulseScheduleResponse) => {
    try {
      const updated = await updatePulseSchedule(sched.id, {
        is_enabled: !sched.is_enabled,
      });
      setSchedules((prev) => prev.map((s) => (s.id === updated.id ? updated : s)));
      showToast(`Schedule '${sched.schedule_name}' ${updated.is_enabled ? 'activated' : 'paused'}.`);
    } catch (err: any) {
      alert(`Toggle failed: ${err.message}`);
    }
  };

  const handleDeleteSchedule = async (scheduleId: number) => {
    if (!confirm('Are you sure you want to delete this automated report schedule?')) return;
    try {
      await deletePulseSchedule(scheduleId);
      setSchedules((prev) => prev.filter((s) => s.id !== scheduleId));
      showToast('Schedule deleted.');
    } catch (err: any) {
      alert(`Delete failed: ${err.message}`);
    }
  };

  const handleCreateScheduleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingSchedule(true);
    try {
      const payload: PulseScheduleCreateRequest = {
        schedule_name: newScheduleName,
        report_type: newSchedReportType,
        frequency: newSchedFrequency,
        time_of_day: newSchedTime,
        timezone: newSchedTimezone,
        day_of_month: newSchedFrequency === 'MONTHLY' ? newSchedDayOfMonth : undefined,
        day_of_week: newSchedFrequency === 'WEEKLY' ? newSchedDayOfWeek : undefined,
        channel_types: newSchedChannels,
        recipients: [
          {
            name: newRecipientName,
            channel: newRecipientChannel,
            destination: newRecipientDest,
            role: 'Executive',
          },
        ],
        kpi_categories: ['FINANCIAL', 'CUSTOMER', 'CHURN', 'RETENTION', 'PRODUCT', 'OPERATIONAL'],
      };
      const created = await createPulseSchedule(payload);
      setSchedules((prev) => [created, ...prev]);
      setShowScheduleModal(false);
      showToast(`Schedule '${created.schedule_name}' created.`);
    } catch (err: any) {
      alert(`Schedule creation failed: ${err.message}`);
    } finally {
      setSavingSchedule(false);
    }
  };

  const handleRetryDelivery = async (deliveryId: number) => {
    try {
      const res = await retryPulseDelivery(deliveryId);
      setDeliveryLogs((prev) => prev.map((l) => (l.id === res.id ? res : l)));
      showToast(`Delivery #${deliveryId} retried. New status: ${res.status}`);
    } catch (err: any) {
      alert(`Retry failed: ${err.message}`);
    }
  };

  const handleToggleRecipientOpt = async (recip: PulseRecipientItem) => {
    const nextStatus = recip.opt_status === 'OPTED_IN' ? 'OPTED_OUT' : 'OPTED_IN';
    try {
      const res = await updatePulseRecipientOpt({
        recipient_name: recip.recipient_name,
        channel: recip.channel,
        destination: recip.destination,
        opt_status: nextStatus,
        opt_out_reason: nextStatus === 'OPTED_OUT' ? 'Manager dashboard manual override' : undefined,
      });
      setRecipients((prev) => prev.map((r) => (r.id === res.id ? res : r)));
      showToast(`Recipient '${recip.recipient_name}' marked as ${nextStatus}.`);
    } catch (err: any) {
      alert(`Opt update failed: ${err.message}`);
    }
  };

  return (
    <div className="min-h-full pb-16 text-slate-900 dark:text-slate-100">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 bg-slate-900 text-white px-5 py-3 rounded-lg shadow-xl border border-slate-700 animate-slide-up">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-sm font-medium">{toastMessage}</span>
        </div>
      )}

      {/* Top Header Bar */}
      <div className="bg-surface border-b border-surface-border sticky top-0 z-30 shadow-xs">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
            <div>
              <div className="flex items-center gap-3">
                <div className="p-2 bg-indigo-600 text-white rounded-lg shadow-xs">
                  <Activity className="w-6 h-6" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">NEXUS Pulse</h1>
                    <span className="px-2 py-0.5 text-xs font-semibold uppercase tracking-wider bg-indigo-50 dark:bg-indigo-950/50 text-indigo-700 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800 rounded-full">
                      Management Intelligence
                    </span>
                  </div>
                  <p className="text-sm text-slate-500 dark:text-slate-400">
                    Automated executive intelligence, performance scorecards, and multi-channel publication
                  </p>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {onAskQuery && (
                <button
                  onClick={() => onAskQuery('Analyze current NEXUS Pulse executive KPIs, anomalies, and management recommendations')}
                  className="inline-flex items-center gap-2 px-3.5 py-2 bg-indigo-50 dark:bg-indigo-950/50 hover:bg-indigo-100 dark:hover:bg-indigo-900/50 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800 text-sm font-medium rounded-lg transition-colors"
                  title="Ask NEXUS AI Copilot about Pulse metrics"
                >
                  <Activity className="w-4 h-4" />
                  <span>Ask NEXUS</span>
                </button>
              )}
              <button
                onClick={() => setShowGenerateModal(true)}
                className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium rounded-lg shadow-xs transition-colors"
              >
                <FileText className="w-4 h-4" />
                <span>Generate Report Now</span>
              </button>
            </div>
          </div>

          {/* Navigation Tabs */}
          <div className="flex items-center gap-6 mt-6 border-b border-surface-border overflow-x-auto">
            <button
              onClick={() => setActiveTab('dashboard')}
              className={`pb-3 text-sm font-medium border-b-2 flex items-center gap-2 whitespace-nowrap transition-colors ${activeTab === 'dashboard'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
            >
              <TrendingUp className="w-4 h-4" />
              <span>Executive Dashboard</span>
            </button>
            <button
              onClick={() => setActiveTab('reports')}
              className={`pb-3 text-sm font-medium border-b-2 flex items-center gap-2 whitespace-nowrap transition-colors ${activeTab === 'reports'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
            >
              <FileText className="w-4 h-4" />
              <span>Reports & Publications</span>
              {reportsTotal > 0 && (
                <span className="px-1.5 py-0.5 text-xs bg-surface-elevated text-slate-700 dark:text-slate-300 rounded-full font-mono">
                  {reportsTotal}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab('automation')}
              className={`pb-3 text-sm font-medium border-b-2 flex items-center gap-2 whitespace-nowrap transition-colors ${activeTab === 'automation'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
            >
              <Clock className="w-4 h-4" />
              <span>Automation & Schedules</span>
              {schedules.length > 0 && (
                <span className="px-1.5 py-0.5 text-xs bg-surface-elevated text-slate-700 dark:text-slate-300 rounded-full font-mono">
                  {schedules.length}
                </span>
              )}
            </button>
            <button
              onClick={() => setActiveTab('channels')}
              className={`pb-3 text-sm font-medium border-b-2 flex items-center gap-2 whitespace-nowrap transition-colors ${activeTab === 'channels'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
            >
              <Bell className="w-4 h-4" />
              <span>Notification Settings</span>
              <span className="px-1.5 py-0.5 text-xs bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800 rounded-full font-mono text-[10px]">
                Manager Hub
              </span>
            </button>
            <button
              onClick={() => setActiveTab('deliveries')}
              className={`pb-3 text-sm font-medium border-b-2 flex items-center gap-2 whitespace-nowrap transition-colors ${activeTab === 'deliveries'
                ? 'border-indigo-600 text-indigo-600 dark:text-indigo-400'
                : 'border-transparent text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
            >
              <Activity className="w-4 h-4" />
              <span>Delivery History</span>
              {deliveryLogs.length > 0 && (
                <span className="px-1.5 py-0.5 text-xs bg-surface-elevated text-slate-700 dark:text-slate-300 rounded-full font-mono">
                  {deliveryLogs.length}
                </span>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Main Workspace Body */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6">
        {/* ============================================================== */}
        {/* TAB 1: EXECUTIVE DASHBOARD */}
        {/* ============================================================== */}
        {activeTab === 'dashboard' && (
          <div className="space-y-6">
            {/* Filter Bar & Freshness */}
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-surface p-4 rounded-xl border border-surface-border shadow-xs">
              <div className="flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mr-2">
                  Period Window:
                </span>
                {(['30d', 'month', 'last_month', '7d'] as const).map((range) => (
                  <button
                    key={range}
                    onClick={() => setDateRangeFilter(range)}
                    className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors ${
                      dateRangeFilter === range
                        ? 'bg-indigo-600 text-white'
                        : 'bg-void text-slate-700 dark:text-slate-300 hover:bg-surface-elevated border border-surface-border'
                    }`}
                  >
                    {range === '30d' && 'Last 30 Days'}
                    {range === 'month' && 'This Month'}
                    {range === 'last_month' && 'Last Month'}
                    {range === '7d' && 'Last 7 Days'}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
                {dashboard && (
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                    <span>
                      Sync Latency: <b className="text-slate-700 dark:text-slate-200">{dashboard.data_freshness_hours?.toFixed(1) || '0.0'} hrs</b>
                    </span>
                  </div>
                )}
                <button
                  onClick={fetchDashboard}
                  className="inline-flex items-center gap-1.5 text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 font-medium transition-colors"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Refresh Telemetry</span>
                </button>
              </div>
            </div>

            {loadingDashboard && <LoadingState message="Aggregating executive intelligence and verified KPIs..." />}

            {dashboardError && (
              <div className="p-4 bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-800 rounded-xl text-rose-700 dark:text-rose-300 text-sm flex items-center gap-3">
                <AlertOctagon className="w-5 h-5 flex-shrink-0" />
                <span>{dashboardError}</span>
              </div>
            )}

            {dashboard && !loadingDashboard && (
              <>
                {/* Authoritative Watermark & Governance Banner */}
                <div
                  className={`p-4 rounded-xl border flex flex-col sm:flex-row sm:items-center justify-between gap-4 ${dashboard.is_actionable
                    ? 'bg-emerald-50/60 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800/60 text-emerald-900 dark:text-emerald-200'
                    : 'bg-amber-50/70 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800/60 text-amber-900 dark:text-amber-200'
                    }`}
                >
                  <div className="flex items-center gap-3">
                    {dashboard.is_actionable ? (
                      <ShieldCheck className="w-6 h-6 text-emerald-600 dark:text-emerald-400 flex-shrink-0" />
                    ) : (
                      <AlertTriangle className="w-6 h-6 text-amber-600 dark:text-amber-400 flex-shrink-0" />
                    )}
                    <div>
                      <div className="font-semibold text-sm flex items-center gap-2">
                        <span>
                          {dashboard.is_actionable
                            ? 'Authoritative Production Data Certified'
                            : 'Diagnostic & Synthetic Telemetry Notice'}
                        </span>
                        <span
                          className={`px-2 py-0.5 text-xs font-mono uppercase rounded ${dashboard.is_actionable ? 'bg-emerald-100 dark:bg-emerald-900/60 text-emerald-800 dark:text-emerald-300' : 'bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-300'
                            }`}
                        >
                          Status: {dashboard.watermark_status}
                        </span>
                      </div>
                      <p className="text-xs text-slate-600 dark:text-slate-300 mt-0.5">
                        {dashboard.is_actionable
                          ? 'All commercial transactions, payments, and settlements are cryptographically sealed through period-close boundaries.'
                          : 'Tenant ingestion boundary is incomplete or in diagnostic rehearsal mode. Prescriptive retention proposals remain advisory only.'}
                      </p>
                    </div>
                  </div>

                  <div className="text-xs text-right text-slate-500 dark:text-slate-400 whitespace-nowrap">
                    Period: {formatDate(dashboard.period_start)} – {formatDate(dashboard.period_end)}
                  </div>
                </div>

                {/* Core Financial & Performance Scorecard */}
                <div>
                  <h2 className="text-base font-semibold text-slate-900 dark:text-white mb-3 flex items-center gap-2">
                    <DollarSign className="w-4 h-4 text-indigo-500" />
                    <span>Commercial & Financial Scorecard</span>
                  </h2>
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    {/* Total Revenue */}
                    <div className="bg-surface p-5 rounded-xl border border-surface-border shadow-xs relative overflow-hidden">
                      <div className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        Total Commercial Revenue
                      </div>
                      <div className="text-2xl font-bold text-slate-900 dark:text-white mt-2">
                        {dashboard.kpi_payload.financial.total_revenue?.formatted_value || '$0.00'}
                      </div>
                      {dashboard.kpi_payload.financial.revenue_growth?.value !== null && (
                        <div className="mt-2 flex items-center gap-1.5 text-xs font-medium text-emerald-500">
                          <TrendingUp className="w-3.5 h-3.5" />
                          <span>
                            {dashboard.kpi_payload.financial.revenue_growth?.formatted_value || '0.0%'} vs Prior Period
                          </span>
                        </div>
                      )}
                      <div className="text-[11px] text-slate-400 mt-1">
                        Completed orders:{' '}
                        <b className="text-slate-700 dark:text-slate-200">{dashboard.kpi_payload.financial.total_orders?.formatted_value || '0'}</b>
                      </div>
                    </div>

                    {/* Average Order Value (AOV) */}
                    <div className="bg-surface p-5 rounded-xl border border-surface-border shadow-xs">
                      <div className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        Average Order Value
                      </div>
                      <div className="text-2xl font-bold text-slate-900 dark:text-white mt-2">
                        {dashboard.kpi_payload.financial.average_order_value?.formatted_value || '$0.00'}
                      </div>
                      <div className="text-xs text-slate-500 dark:text-slate-400 mt-2">
                        Order size baseline across active accounts
                      </div>
                      <div className="text-[11px] text-slate-400 mt-1">
                        Gross Margin:{' '}
                        <b className="text-slate-700 dark:text-slate-200">{dashboard.kpi_payload.financial.gross_margin?.formatted_value || 'N/A'}</b>
                      </div>
                    </div>

                    {/* Customer Cadence & Retention */}
                    <div className="bg-surface p-5 rounded-xl border border-surface-border shadow-xs">
                      <div className="text-xs font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                        Active Buyers & Repeat Rate
                      </div>
                      <div className="text-2xl font-bold text-slate-900 dark:text-white mt-2">
                        {dashboard.kpi_payload.customer.active_customers?.formatted_value || '0'}
                      </div>
                      <div className="text-xs text-indigo-500 font-medium mt-2">
                        Repeat Rate: {dashboard.kpi_payload.customer.repeat_purchase_rate?.formatted_value || '0.0%'}
                      </div>
                      <div className="text-[11px] text-slate-400 mt-1">
                        Evaluated for cadence: {dashboard.kpi_payload.churn.total_evaluated_customers?.formatted_value || '0'}
                      </div>
                    </div>

                    {/* Revenue at Churn Risk */}
                    <div className="p-5 rounded-xl border border-rose-300 dark:border-rose-900/50 bg-rose-50/40 dark:bg-rose-950/30 shadow-xs">
                      <div className="text-xs font-medium text-rose-700 dark:text-rose-400 uppercase tracking-wider">
                        Revenue at Churn Risk
                      </div>
                      <div className="text-2xl font-bold text-rose-900 dark:text-rose-200 mt-2">
                        {formatCurrency(dashboard.revenue_at_risk_usd)}
                      </div>
                      <div className="text-xs text-rose-700 dark:text-rose-400 font-medium mt-2">
                        {dashboard.critical_risk_count} Critical & High Risk Buyers
                      </div>
                      <div className="text-[11px] text-slate-500 dark:text-slate-400 mt-1">
                        Pending Reviews: <b className="text-slate-700 dark:text-slate-200">{dashboard.retention_pending_count} proposals</b>
                      </div>
                    </div>
                  </div>
                </div>

                {/* Charts & Risk Distribution Row */}
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                  {/* Revenue Progression Trend (2 Cols) */}
                  <div className="lg:col-span-2 bg-surface p-6 rounded-xl border border-surface-border shadow-xs">
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Commercial Revenue Progression</h3>
                        <p className="text-xs text-slate-500 dark:text-slate-400">Verified commercial sales by transaction date</p>
                      </div>
                      <span className="text-xs font-mono text-slate-500 dark:text-slate-400">Daily granularity</span>
                    </div>

                    {/* Mini SVG Trend Chart */}
                    <div className="h-48 w-full flex items-end gap-1 pt-6 pb-2 border-b border-surface-border">
                      {dashboard.kpi_payload.revenue_trend.length === 0 ? (
                        <div className="w-full h-full flex items-center justify-center text-xs text-slate-500 dark:text-slate-400">
                          No daily transactions recorded in selected window
                        </div>
                      ) : (
                        dashboard.kpi_payload.revenue_trend.map((pt, idx) => {
                          const maxRev = Math.max(
                            ...dashboard.kpi_payload.revenue_trend.map((p) => p.revenue),
                            1
                          );
                          const heightPct = Math.max((pt.revenue / maxRev) * 100, 4);
                          return (
                            <div
                              key={idx}
                              className="flex-1 flex flex-col items-center group relative h-full justify-end"
                            >
                              <div
                                style={{ height: `${heightPct}%` }}
                                className="w-full bg-indigo-500 hover:bg-indigo-600 rounded-t transition-all group-hover:shadow-md"
                              ></div>
                              {/* Hover Tooltip */}
                              <div className="absolute bottom-full mb-2 hidden group-hover:flex flex-col bg-slate-900 dark:bg-slate-800 text-white text-[10px] p-2 rounded shadow-lg z-20 whitespace-nowrap border border-slate-700">
                                <span className="font-semibold">{pt.date}</span>
                                <span>Revenue: {formatCurrency(pt.revenue)}</span>
                                <span>Orders: {pt.orders}</span>
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                    <div className="flex justify-between text-[11px] text-slate-500 dark:text-slate-400 mt-2">
                      <span>{dashboard.period_start.split('T')[0]}</span>
                      <span>{dashboard.period_end.split('T')[0]}</span>
                    </div>
                  </div>

                  {/* Customer Risk & Urgency Distribution (1 Col) */}
                  <div className="bg-surface p-6 rounded-xl border border-surface-border shadow-xs flex flex-col justify-between">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-900 dark:text-white mb-1">Customer Churn Exposure</h3>
                      <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">Empirical inter-purchase cadence ratio tiers</p>

                      <div className="space-y-3">
                        {/* Critical Risk */}
                        <div>
                          <div className="flex justify-between text-xs mb-1">
                            <span className="font-medium text-rose-700 dark:text-rose-400 flex items-center gap-1.5">
                              <span className="w-2 h-2 rounded-full bg-rose-500"></span>
                              Critical (&ge; 3.0x delay)
                            </span>
                            <span className="font-bold text-slate-800 dark:text-slate-200">
                              {dashboard.kpi_payload.risk_distribution.critical || 0}
                            </span>
                          </div>
                          <div className="w-full bg-surface-elevated rounded-full h-2 overflow-hidden border border-surface-border">
                            <div
                              className="bg-rose-500 h-2 rounded-full"
                              style={{
                                width: `${Math.min(
                                  ((dashboard.kpi_payload.risk_distribution.critical || 0) /
                                    Math.max(
                                      Object.values(dashboard.kpi_payload.risk_distribution).reduce(
                                        (a, b) => a + b,
                                        0
                                      ),
                                      1
                                    )) *
                                  100,
                                  100
                                )}%`,
                              }}
                            ></div>
                          </div>
                        </div>

                        {/* High Risk */}
                        <div>
                          <div className="flex justify-between text-xs mb-1">
                            <span className="font-medium text-amber-700 dark:text-amber-400 flex items-center gap-1.5">
                              <span className="w-2 h-2 rounded-full bg-amber-500"></span>
                              High (2.0x - 3.0x delay)
                            </span>
                            <span className="font-bold text-slate-800 dark:text-slate-200">
                              {dashboard.kpi_payload.risk_distribution.high || 0}
                            </span>
                          </div>
                          <div className="w-full bg-surface-elevated rounded-full h-2 overflow-hidden border border-surface-border">
                            <div
                              className="bg-amber-500 h-2 rounded-full"
                              style={{
                                width: `${Math.min(
                                  ((dashboard.kpi_payload.risk_distribution.high || 0) /
                                    Math.max(
                                      Object.values(dashboard.kpi_payload.risk_distribution).reduce(
                                        (a, b) => a + b,
                                        0
                                      ),
                                      1
                                    )) *
                                  100,
                                  100
                                )}%`,
                              }}
                            ></div>
                          </div>
                        </div>

                        {/* Medium / Watchlist */}
                        <div>
                          <div className="flex justify-between text-xs mb-1">
                            <span className="font-medium text-yellow-700 dark:text-yellow-400 flex items-center gap-1.5">
                              <span className="w-2 h-2 rounded-full bg-yellow-400"></span>
                              Watchlist (1.3x - 2.0x delay)
                            </span>
                            <span className="font-bold text-slate-800 dark:text-slate-200">
                              {dashboard.kpi_payload.risk_distribution.medium || 0}
                            </span>
                          </div>
                          <div className="w-full bg-surface-elevated rounded-full h-2 overflow-hidden border border-surface-border">
                            <div
                              className="bg-yellow-400 h-2 rounded-full"
                              style={{
                                width: `${Math.min(
                                  ((dashboard.kpi_payload.risk_distribution.medium || 0) /
                                    Math.max(
                                      Object.values(dashboard.kpi_payload.risk_distribution).reduce(
                                        (a, b) => a + b,
                                        0
                                      ),
                                      1
                                    )) *
                                  100,
                                  100
                                )}%`,
                              }}
                            ></div>
                          </div>
                        </div>

                        {/* Low / Healthy */}
                        <div>
                          <div className="flex justify-between text-xs mb-1">
                            <span className="font-medium text-emerald-700 dark:text-emerald-400 flex items-center gap-1.5">
                              <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
                              Healthy On-Schedule
                            </span>
                            <span className="font-bold text-slate-800 dark:text-slate-200">
                              {dashboard.kpi_payload.risk_distribution.low || 0}
                            </span>
                          </div>
                          <div className="w-full bg-surface-elevated rounded-full h-2 overflow-hidden border border-surface-border">
                            <div
                              className="bg-emerald-500 h-2 rounded-full"
                              style={{
                                width: `${Math.min(
                                  ((dashboard.kpi_payload.risk_distribution.low || 0) /
                                    Math.max(
                                      Object.values(dashboard.kpi_payload.risk_distribution).reduce(
                                        (a, b) => a + b,
                                        0
                                      ),
                                      1
                                    )) *
                                  100,
                                  100
                                )}%`,
                              }}
                            ></div>
                          </div>
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={() => onNavigate('/retention')}
                      className="mt-6 w-full py-2 bg-surface-elevated hover:bg-surface-border text-slate-700 dark:text-slate-200 text-xs font-semibold rounded-lg flex items-center justify-center gap-2 transition-colors border border-surface-border"
                    >
                      <span>Review Retention Queue</span>
                      <ChevronRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>

                {/* Top Products Table & Strategic Insights Row */}
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                  {/* Top-Selling Products */}
                  <div className="bg-surface p-6 rounded-xl border border-surface-border shadow-xs">
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Top-Selling Products</h3>
                        <p className="text-xs text-slate-500 dark:text-slate-400">Ranked by verified commercial revenue</p>
                      </div>
                      <Package className="w-4 h-4 text-slate-400 dark:text-slate-500" />
                    </div>

                    {dashboard.kpi_payload.top_products.length === 0 ? (
                      <div className="text-center py-8 text-xs text-slate-500 dark:text-slate-400">
                        No product transaction lines in selected period
                      </div>
                    ) : (
                      <div className="overflow-x-auto">
                        <table className="min-w-full divide-y divide-surface-border text-xs">
                          <thead>
                            <tr className="text-left text-slate-500 dark:text-slate-400 font-medium">
                              <th className="pb-2">SKU / Item</th>
                              <th className="pb-2">Category</th>
                              <th className="pb-2 text-right">Units</th>
                              <th className="pb-2 text-right">Revenue</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-surface-border">
                            {dashboard.kpi_payload.top_products.slice(0, 5).map((p, idx) => (
                              <tr key={idx} className="hover:bg-surface-elevated">
                                <td className="py-2.5">
                                  <div className="font-medium text-slate-800 dark:text-slate-200">{p.name}</div>
                                  <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">{p.sku}</span>
                                </td>
                                <td className="py-2.5 text-slate-600 dark:text-slate-300">{p.category}</td>
                                <td className="py-2.5 text-right font-medium text-slate-700 dark:text-slate-200">
                                  {formatNumber(p.units_sold)}
                                </td>
                                <td className="py-2.5 text-right font-bold text-slate-900 dark:text-white">
                                  {formatCurrency(p.revenue)}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>

                  {/* Strategic Insights & Prescriptive Recommendations */}
                  <div className="bg-surface p-6 rounded-xl border border-surface-border shadow-xs">
                    <div className="flex items-center justify-between mb-4">
                      <div>
                        <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                          Prescriptive Intelligence & Insights
                        </h3>
                        <p className="text-xs text-slate-500 dark:text-slate-400">
                          Auditable classification (Fact, KPI, Observation, Model, Action)
                        </p>
                      </div>
                      <span className="text-xs px-2 py-0.5 bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800 rounded-full font-medium">
                        {dashboard.insights.length} Synthesized
                      </span>
                    </div>

                    <div className="space-y-3 max-h-96 overflow-y-auto pr-1">
                      {dashboard.insights.map((ins, idx) => {
                        const typeBadgeColor =
                          ins.type === 'OBSERVED_FACT'
                            ? 'bg-blue-50 dark:bg-blue-950/50 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800'
                            : ins.type === 'CALCULATED_KPI'
                            ? 'bg-indigo-50 dark:bg-indigo-950/50 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800'
                            : ins.type === 'STATISTICAL_OBSERVATION'
                            ? 'bg-cyan-50 dark:bg-cyan-950/50 text-cyan-700 dark:text-cyan-300 border-cyan-200 dark:border-cyan-800'
                            : ins.type === 'RECOMMENDED_ACTION'
                            ? 'bg-amber-50 dark:bg-amber-950/50 text-amber-800 dark:text-amber-300 border-amber-200 dark:border-amber-800'
                            : 'bg-purple-50 dark:bg-purple-950/50 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800';

                        return (
                          <div
                            key={idx}
                            className="p-3.5 rounded-lg border border-surface-border bg-surface-elevated/50 hover:bg-surface-elevated transition-colors"
                          >
                            <div className="flex items-center justify-between gap-2 mb-1.5">
                              <span
                                className={`px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider rounded border ${typeBadgeColor}`}
                              >
                                {ins.type.replace('_', ' ')}
                              </span>
                              <span className="text-[10px] text-slate-500 dark:text-slate-400 uppercase font-mono">
                                {ins.category}
                              </span>
                            </div>
                            <div className="text-xs font-semibold text-slate-900 dark:text-white">{ins.title}</div>
                            <p className="text-xs text-slate-600 dark:text-slate-300 mt-1 leading-relaxed">{ins.description}</p>
                            {ins.action_suggestion && (
                              <div className="mt-2 text-xs font-medium text-indigo-700 dark:text-indigo-300 flex items-start gap-1.5 bg-indigo-50/60 dark:bg-indigo-950/40 p-2 rounded border border-indigo-100 dark:border-indigo-900">
                                <span className="font-bold uppercase tracking-wider text-[10px]">Action:</span>
                                <span>{ins.action_suggestion}</span>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        )}

        {/* ============================================================== */}
        {/* TAB 2: AUTOMATED REPORTS & HISTORY */}
        {/* ============================================================== */}
        {activeTab === 'reports' && (
          <div className="space-y-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 bg-surface p-4 rounded-xl border border-surface-border shadow-xs">
              <div>
                <h2 className="text-base font-semibold text-slate-900 dark:text-white">Generated Reports Archive</h2>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Immutable historical business intelligence packages with PDF and digital JSON artifacts
                </p>
              </div>

              <div className="flex items-center gap-3">
                <button
                  onClick={() => setShowGenerateModal(true)}
                  className="inline-flex items-center gap-2 px-3.5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded-lg shadow-xs transition-colors"
                >
                  <Plus className="w-4 h-4" />
                  <span>New Report Run</span>
                </button>
                <button
                  onClick={fetchReports}
                  className="p-2 border border-surface-border rounded-lg hover:bg-surface-elevated text-slate-600 dark:text-slate-300 transition-colors"
                  title="Refresh Reports"
                >
                  <RefreshCw className="w-4 h-4" />
                </button>
              </div>
            </div>

            {loadingReports && <LoadingState message="Loading historical report catalog..." />}

            {!loadingReports && reports.length === 0 ? (
              <div className="bg-surface rounded-xl border border-surface-border p-12 text-center">
                <FileText className="w-12 h-12 text-slate-300 dark:text-slate-600 mx-auto mb-3" />
                <h3 className="text-base font-semibold text-slate-800 dark:text-slate-200">No Reports Generated Yet</h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 max-w-sm mx-auto mt-1 mb-4">
                  Generate your first executive report or configure an automated monthly schedule to begin.
                </p>
                <button
                  onClick={() => setShowGenerateModal(true)}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded-lg"
                >
                  Generate Initial Report
                </button>
              </div>
            ) : (
              <div className="bg-surface rounded-xl border border-surface-border shadow-xs overflow-hidden">
                <table className="min-w-full divide-y divide-surface-border text-xs">
                  <thead className="bg-surface-elevated">
                    <tr className="text-left text-slate-500 dark:text-slate-400 font-medium">
                      <th className="py-3 px-4">Report Title & Type</th>
                      <th className="py-3 px-4">Period Window</th>
                      <th className="py-3 px-4">Watermark Status</th>
                      <th className="py-3 px-4">Generated At</th>
                      <th className="py-3 px-4 text-center">Deliveries</th>
                      <th className="py-3 px-4 text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-surface-border">
                    {reports.map((rep) => (
                      <tr key={rep.id} className="hover:bg-surface-elevated transition-colors">
                        <td className="py-3.5 px-4">
                          <div className="font-semibold text-slate-900 dark:text-white">{rep.report_title}</div>
                          <div className="flex items-center gap-2 mt-1">
                            <span className="px-2 py-0.5 text-[10px] font-mono bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800 rounded">
                              {rep.report_type}
                            </span>
                            <span className="text-[10px] text-slate-500 dark:text-slate-400 font-mono">ID: {rep.id.slice(0, 8)}...</span>
                          </div>
                        </td>
                        <td className="py-3.5 px-4 text-slate-600 dark:text-slate-300">
                          {formatDate(rep.period_start)} – {formatDate(rep.period_end)}
                        </td>
                        <td className="py-3.5 px-4">
                          <span
                            className={`px-2 py-0.5 text-[10px] font-mono rounded ${
                              rep.watermark_status === 'verified_complete'
                                ? 'bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
                                : 'bg-amber-50 dark:bg-amber-950/50 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800'
                            }`}
                          >
                            {rep.watermark_status}
                          </span>
                        </td>
                        <td className="py-3.5 px-4 text-slate-500 dark:text-slate-400">{formatDate(rep.created_at)}</td>
                        <td className="py-3.5 px-4 text-center font-bold text-slate-700 dark:text-slate-300">
                          {rep.deliveries_count}
                        </td>
                        <td className="py-3.5 px-4 text-right">
                          <div className="inline-flex items-center gap-2">
                            <button
                              onClick={() => handleViewReportDetail(rep.id)}
                              className="px-2.5 py-1 bg-surface-elevated hover:bg-surface-border text-slate-700 dark:text-slate-200 rounded font-medium text-xs transition-colors border border-surface-border"
                              title="View structured digital report"
                            >
                              View
                            </button>
                            <button
                              onClick={() => handleDownloadPdf(rep.id, rep.report_title)}
                              className="px-2.5 py-1 bg-indigo-50 dark:bg-indigo-950/50 hover:bg-indigo-100 text-indigo-700 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800 rounded font-medium text-xs flex items-center gap-1 transition-colors"
                              title="Download ReportLab PDF"
                            >
                              <Download className="w-3 h-3" />
                              <span>PDF</span>
                            </button>
                            <button
                              onClick={() => handleCopyPublicLink(rep.access_token)}
                              className="p-1 hover:bg-surface-elevated text-slate-500 dark:text-slate-400 rounded"
                              title="Copy 30-day expiring public link"
                            >
                              <Share2 className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {/* Reports Archive Pagination Controls */}
                <div className="p-3 border-t border-surface-border flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 bg-surface-elevated">
                  <span>
                    Showing {reports.length} of {reportsTotal} reports
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      disabled={reportsPage <= 1}
                      onClick={() => setReportsPage((p) => Math.max(1, p - 1))}
                      className="px-2.5 py-1 border border-surface-border rounded bg-surface hover:bg-surface-elevated text-slate-700 dark:text-slate-200 disabled:opacity-40"
                    >
                      Previous
                    </button>
                    <span className="font-semibold text-slate-700 dark:text-slate-200">Page {reportsPage}</span>
                    <button
                      disabled={reports.length < 20 || reportsPage * 20 >= reportsTotal}
                      onClick={() => setReportsPage((p) => p + 1)}
                      className="px-2.5 py-1 border border-surface-border rounded bg-surface hover:bg-surface-elevated text-slate-700 dark:text-slate-200 disabled:opacity-40"
                    >
                      Next
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ============================================================== */}
        {/* TAB 3: AUTOMATION & SCHEDULES */}
        {/* ============================================================== */}
        {activeTab === 'automation' && (
          <div className="space-y-6">
            {/* Scheduled Report Automations Table */}
            <div className="bg-surface rounded-xl border border-surface-border shadow-xs overflow-hidden">
              <div className="p-4 border-b border-surface-border flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                    Manager-Controlled Automation Schedules
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Recurring triggers with idempotent execution, cron timing, and duplicate delivery prevention
                  </p>
                </div>
                <button
                  onClick={() => setShowScheduleModal(true)}
                  className="inline-flex items-center gap-2 px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-medium rounded-lg transition-colors shadow-xs"
                >
                  <Plus className="w-3.5 h-3.5" />
                  <span>Create Schedule</span>
                </button>
              </div>

              {loadingSchedules && <LoadingState message="Loading scheduled report triggers..." />}

              {!loadingSchedules && schedules.length === 0 ? (
                <div className="p-8 text-center text-xs text-slate-500 dark:text-slate-400">
                  No automated schedules currently configured. Click "Create Schedule" to establish your cadence.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-surface-border text-xs">
                    <thead className="bg-surface-elevated text-slate-500 dark:text-slate-400">
                      <tr className="text-left font-medium">
                        <th className="py-3 px-4">Schedule Name</th>
                        <th className="py-3 px-4">Report Type</th>
                        <th className="py-3 px-4">Cadence / Time</th>
                        <th className="py-3 px-4">Channels</th>
                        <th className="py-3 px-4">Next Run (UTC)</th>
                        <th className="py-3 px-4 text-center">Status</th>
                        <th className="py-3 px-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-border">
                      {schedules.map((s) => (
                        <tr key={s.id} className="hover:bg-surface-elevated transition-colors">
                          <td className="py-3 px-4 font-semibold text-slate-900 dark:text-white">
                            {s.schedule_name}
                          </td>
                          <td className="py-3 px-4 text-slate-600 dark:text-slate-300">
                            <span className="font-mono text-[10px] bg-surface-elevated border border-surface-border px-2 py-0.5 rounded">
                              {s.report_type}
                            </span>
                          </td>
                          <td className="py-3 px-4 text-slate-600 dark:text-slate-300">
                            {s.frequency} at {s.time_of_day} ({s.timezone})
                          </td>
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-1.5">
                              {s.channel_types.map((ch, idx) => (
                                <span
                                  key={idx}
                                  className="px-1.5 py-0.5 text-[10px] font-mono bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800 rounded"
                                >
                                  {ch}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className="py-3 px-4 text-slate-500 dark:text-slate-400 font-mono text-[11px]">
                            {s.next_run_at ? formatDate(s.next_run_at) : '—'}
                          </td>
                          <td className="py-3 px-4 text-center">
                            <button
                              onClick={() => handleToggleScheduleActive(s)}
                              className={`px-2.5 py-1 text-[11px] font-semibold rounded-full border transition-colors ${s.is_enabled
                                ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-800'
                                : 'bg-surface-elevated text-slate-500 border-surface-border'
                                }`}
                            >
                              {s.is_enabled ? 'Active' : 'Paused'}
                            </button>
                          </td>
                          <td className="py-3 px-4 text-right">
                            <button
                              onClick={() => handleDeleteSchedule(s.id)}
                              className="p-1 text-slate-400 hover:text-rose-600 dark:hover:text-rose-400 rounded transition-colors"
                              title="Delete Schedule"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ============================================================== */}
        {/* TAB 4: NOTIFICATION SETTINGS (MANAGER SELF-SERVICE HUB) */}
        {/* ============================================================== */}
        {activeTab === 'channels' && (
          <div className="space-y-6">
            <NotificationChannelHub onStatusChange={fetchAutomation} />
          </div>
        )}

        {/* ============================================================== */}
        {/* TAB 5: DELIVERY HISTORY */}
        {/* ============================================================== */}
        {activeTab === 'deliveries' && (
          <div className="space-y-6">
            {/* Delivery Audit Log Table */}
            <div className="bg-surface rounded-xl border border-surface-border p-6 shadow-xs">
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
                    Multi-Channel Delivery Audit Logs ({deliveryLogs.length})
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Immutable ledger of dispatches, carrier statuses, and delivery confirmations
                  </p>
                </div>
                <button
                  onClick={fetchAutomation}
                  className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline font-medium flex items-center gap-1"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Refresh Telemetry</span>
                </button>
              </div>

              {loadingLogs && <LoadingState message="Loading delivery log audit records..." />}

              {!loadingLogs && deliveryLogs.length === 0 ? (
                <div className="text-center py-12 text-xs text-slate-500 dark:text-slate-400">
                  No delivery logs recorded yet. Send a test report from Notification Settings to verify the ledger.
                </div>
              ) : (
                <div className="overflow-x-auto max-h-96">
                  <table className="min-w-full divide-y divide-surface-border text-xs">
                    <thead className="bg-surface-elevated text-slate-500 dark:text-slate-400 sticky top-0">
                      <tr className="text-left font-medium">
                        <th className="py-2.5 px-3">Dispatched</th>
                        <th className="py-2.5 px-3">Channel</th>
                        <th className="py-2.5 px-3">Destination</th>
                        <th className="py-2.5 px-3 text-center">Status</th>
                        <th className="py-2.5 px-3 text-right">Action</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-border">
                      {deliveryLogs.map((log) => (
                        <tr key={log.id} className="hover:bg-surface-elevated transition-colors">
                          <td className="py-2.5 px-3 text-slate-500 dark:text-slate-400 whitespace-nowrap">
                            {formatDate(log.created_at)}
                          </td>
                          <td className="py-2.5 px-3">
                            <span className="font-mono text-[10px] bg-surface-elevated border border-surface-border px-1.5 py-0.5 rounded text-slate-700 dark:text-slate-300">
                              {log.channel}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 font-mono text-slate-800 dark:text-slate-200">
                            {log.recipient_destination}
                          </td>
                          <td className="py-2.5 px-3 text-center">
                            <span
                              className={`px-2 py-0.5 text-[10px] font-mono rounded-full font-semibold ${log.status === 'SENT' || log.status === 'MOCKED' || log.status === 'DELIVERED'
                                ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
                                : 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-400 border border-rose-200 dark:border-rose-800'
                                }`}
                            >
                              {log.status}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-right">
                            {log.status === 'FAILED' ? (
                              <button
                                onClick={() => handleRetryDelivery(log.id)}
                                className="px-2 py-0.5 bg-rose-50 hover:bg-rose-100 text-rose-700 dark:bg-rose-950 dark:text-rose-300 border border-rose-200 dark:border-rose-800 rounded font-medium text-[11px] flex items-center gap-1 ml-auto"
                              >
                                <RotateCw className="w-3 h-3" />
                                <span>Retry</span>
                              </button>
                            ) : (
                              <span className="text-[10px] text-slate-500 dark:text-slate-400">Delivered</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Recipient Opt Registry & Preference Control */}
            <div className="bg-surface rounded-xl border border-surface-border p-6 shadow-xs">
              <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400 mb-4">
                <div>
                  <h4 className="text-sm font-semibold text-slate-900 dark:text-white">
                    Recipient Opt Registry ({recipients.length})
                  </h4>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Consent & opt-out policy enforcement
                  </p>
                </div>
              </div>

              {recipients.length === 0 ? (
                <div className="text-xs text-slate-500 dark:text-slate-400 py-4 text-center">
                  No recipients registered yet. Register contacts in Settings or during schedule creation.
                </div>
              ) : (
                <div className="space-y-2 max-h-60 overflow-y-auto">
                  {recipients.map((recip) => (
                    <div
                      key={recip.id}
                      className="flex items-center justify-between p-3 rounded-lg bg-surface-elevated border border-surface-border text-xs"
                    >
                      <div>
                        <span className="font-medium text-slate-900 dark:text-white">{recip.recipient_name}</span>
                        <span className="text-slate-400 dark:text-slate-500 mx-1.5">•</span>
                        <span className="font-mono text-[11px] text-slate-600 dark:text-slate-300">{recip.destination}</span>
                        <span className="text-slate-400 dark:text-slate-500 mx-1.5">•</span>
                        <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 bg-surface border border-surface-border text-slate-700 dark:text-slate-300 rounded">
                          {recip.channel}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <span
                          className={`px-2 py-0.5 text-[10px] font-semibold rounded-full ${recip.opt_status === 'OPTED_IN'
                            ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                            : 'bg-rose-100 text-rose-800 dark:bg-rose-950 dark:text-rose-300'
                            }`}
                        >
                          {recip.opt_status}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleToggleRecipientOpt(recip)}
                          className="text-[11px] font-medium text-indigo-600 dark:text-indigo-400 hover:underline"
                        >
                          {recip.opt_status === 'OPTED_IN' ? 'Opt Out' : 'Opt In'}
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Loading Overlay for Report Details */}
      {loadingReportDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs">
          <div className="bg-surface p-6 rounded-xl shadow-xl flex items-center gap-3 border border-surface-border">
            <RefreshCw className="w-5 h-5 animate-spin text-indigo-600 dark:text-indigo-400" />
            <span className="text-sm font-medium text-slate-800 dark:text-slate-200">Loading digital report package...</span>
          </div>
        </div>
      )}

      {/* ============================================================== */}
      {/* MODAL: VIEW DIGITAL REPORT DETAIL */}
      {/* ============================================================== */}
      {selectedReportDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-xs p-4 overflow-y-auto">
          <div className="bg-surface rounded-2xl max-w-4xl w-full max-h-[90vh] flex flex-col shadow-2xl border border-surface-border animate-scale-in">
            {/* Modal Header */}
            <div className="p-6 border-b border-surface-border flex items-center justify-between bg-surface-elevated rounded-t-2xl">
              <div>
                <span className="px-2.5 py-0.5 text-xs font-mono uppercase bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-400 border border-indigo-200 dark:border-indigo-800 rounded-full font-semibold">
                  {selectedReportDetail.report_type}
                </span>
                <h3 className="text-xl font-bold text-slate-900 dark:text-white mt-1">{selectedReportDetail.report_title}</h3>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Period: {formatDate(selectedReportDetail.period_start)} –{' '}
                  {formatDate(selectedReportDetail.period_end)} | Created: {formatDate(selectedReportDetail.created_at)}
                </p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => handleDownloadPdf(selectedReportDetail.id, selectedReportDetail.report_title)}
                  className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-medium flex items-center gap-1.5 shadow-xs"
                >
                  <Download className="w-3.5 h-3.5" />
                  <span>Download PDF</span>
                </button>
                <button
                  onClick={() => setSelectedReportDetail(null)}
                  className="p-2 hover:bg-surface-elevated text-slate-500 dark:text-slate-400 rounded-lg"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>
            </div>

            {/* Modal Content */}
            <div className="p-6 overflow-y-auto space-y-6 text-sm flex-1 min-h-0">
              {/* Executive Summary Narrative */}
              <div className="bg-surface-elevated p-5 rounded-xl border border-surface-border">
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2 flex items-center gap-2">
                  <Activity className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                  <span>Executive Management Summary</span>
                </h4>
                <div className="text-xs text-slate-700 dark:text-slate-300 leading-relaxed whitespace-pre-line">
                  {selectedReportDetail.executive_summary}
                </div>
              </div>

              {/* Core Scorecard Grid */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
                  Scorecard Telemetry Grid
                </h4>
                <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
                  <div className="bg-surface p-3.5 rounded-lg border border-surface-border">
                    <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Total Revenue</span>
                    <span className="text-base font-bold text-slate-900 dark:text-white">
                      {selectedReportDetail.kpi_payload.financial.total_revenue?.formatted_value || '$0.00'}
                    </span>
                  </div>
                  <div className="bg-surface p-3.5 rounded-lg border border-surface-border">
                    <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Revenue Growth</span>
                    <span className="text-base font-bold text-emerald-600 dark:text-emerald-400">
                      {selectedReportDetail.kpi_payload.financial.revenue_growth?.formatted_value || 'N/A'}
                    </span>
                  </div>
                  <div className="bg-surface p-3.5 rounded-lg border border-surface-border">
                    <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Completed Orders</span>
                    <span className="text-base font-bold text-slate-900 dark:text-white">
                      {selectedReportDetail.kpi_payload.financial.total_orders?.formatted_value || '0'}
                    </span>
                  </div>
                  <div className="bg-surface p-3.5 rounded-lg border border-surface-border">
                    <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Average Order Value</span>
                    <span className="text-base font-bold text-slate-900 dark:text-white">
                      {selectedReportDetail.kpi_payload.financial.average_order_value?.formatted_value || '$0.00'}
                    </span>
                  </div>
                  <div className="bg-surface p-3.5 rounded-lg border border-surface-border">
                    <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Active Buyers</span>
                    <span className="text-base font-bold text-slate-900 dark:text-white">
                      {selectedReportDetail.kpi_payload.customer.active_customers?.formatted_value || '0'}
                    </span>
                  </div>
                  <div className="bg-surface p-3.5 rounded-lg border border-surface-border">
                    <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Repeat Purchase Rate</span>
                    <span className="text-base font-bold text-slate-900 dark:text-white">
                      {selectedReportDetail.kpi_payload.customer.repeat_purchase_rate?.formatted_value || '0.0%'}
                    </span>
                  </div>
                  <div className="bg-surface p-3.5 rounded-lg border border-surface-border">
                    <span className="text-slate-500 dark:text-slate-400 block text-[11px]">Gross Margin</span>
                    <span className="text-base font-bold text-slate-900 dark:text-white">
                      {selectedReportDetail.kpi_payload.financial.gross_margin?.formatted_value || 'N/A'}
                    </span>
                  </div>
                  <div className="bg-rose-50 dark:bg-rose-950/40 p-3.5 rounded-lg border border-rose-200 dark:border-rose-800">
                    <span className="text-rose-700 dark:text-rose-300 block text-[11px]">Revenue at Churn Risk</span>
                    <span className="text-base font-bold text-rose-900 dark:text-rose-200">
                      {selectedReportDetail.kpi_payload.churn.revenue_at_risk?.formatted_value || '$0.00'}
                    </span>
                  </div>
                </div>
              </div>

              {/* Strategic Insights */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3">
                  Documented Strategic Insights
                </h4>
                <div className="space-y-2.5">
                  {selectedReportDetail.insights.map((ins, idx) => (
                    <div key={idx} className="p-3 bg-surface rounded-lg border border-surface-border text-xs">
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-semibold text-slate-900 dark:text-white">{ins.title}</span>
                        <span className="font-mono text-[10px] text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/60 px-2 py-0.5 rounded border border-indigo-200 dark:border-indigo-800">
                          {ins.type}
                        </span>
                      </div>
                      <p className="text-slate-600 dark:text-slate-300">{ins.description}</p>
                    </div>
                  ))}
                </div>
              </div>

              {/* Data Provenance & Cryptographic Digest */}
              <div className="pt-4 border-t border-surface-border flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs text-slate-500 dark:text-slate-400">
                <div>
                  SHA-256 Digest:{' '}
                  <span className="font-mono text-slate-700 dark:text-slate-300">
                    {selectedReportDetail.pdf_sha256 || 'N/A'}
                  </span>
                </div>
                <div>Watermark State: {selectedReportDetail.watermark_status}</div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ============================================================== */}
      {/* MODAL: GENERATE REPORT NOW */}
      {/* ============================================================== */}
      {showGenerateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-xs p-4">
          <div className="bg-surface rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-surface-border animate-scale-in">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold text-slate-900 dark:text-white">Generate Management Report</h3>
              <button onClick={() => setShowGenerateModal(false)} className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleGenerateReportSubmit} className="space-y-4 text-xs">
              <div>
                <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Report Publication Type</label>
                <select
                  value={genReportType}
                  onChange={(e) => setGenReportType(e.target.value as PulseReportType)}
                  className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                >
                  <option value="MONTHLY_EXECUTIVE">Executive Monthly Report</option>
                  <option value="WEEKLY_MANAGEMENT">Weekly Management Summary</option>
                  <option value="CUSTOM">Custom Management Report</option>
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Period Start Date</label>
                  <input
                    type="date"
                    value={genPeriodStart}
                    onChange={(e) => setGenPeriodStart(e.target.value)}
                    className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                    required
                  />
                </div>
                <div>
                  <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Period End Date</label>
                  <input
                    type="date"
                    value={genPeriodEnd}
                    onChange={(e) => setGenPeriodEnd(e.target.value)}
                    className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Custom Title (Optional)</label>
                <input
                  type="text"
                  value={genTitle}
                  onChange={(e) => setGenTitle(e.target.value)}
                  placeholder="e.g. Q2 Mid-Quarter Executive Performance Brief"
                  className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                />
              </div>

              <div className="pt-2 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowGenerateModal(false)}
                  className="px-4 py-2 border border-surface-border text-slate-700 dark:text-slate-300 hover:bg-surface-elevated font-medium rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={generatingReport}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 dark:disabled:bg-slate-700 text-white font-medium rounded-lg flex items-center gap-2"
                >
                  {generatingReport ? (
                    <span>Compiling Report & PDF...</span>
                  ) : (
                    <>
                      <FileText className="w-4 h-4" />
                      <span>Compile Report</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ============================================================== */}
      {/* MODAL: CREATE REPORT SCHEDULE */}
      {/* ============================================================== */}
      {showScheduleModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/70 backdrop-blur-xs p-4 overflow-y-auto">
          <div className="bg-surface rounded-2xl max-w-lg w-full p-6 shadow-2xl border border-surface-border animate-scale-in">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-bold text-slate-900 dark:text-white">Create Report Automation Schedule</h3>
              <button onClick={() => setShowScheduleModal(false)} className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleCreateScheduleSubmit} className="space-y-4 text-xs">
              <div>
                <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Schedule Name</label>
                <input
                  type="text"
                  value={newScheduleName}
                  onChange={(e) => setNewScheduleName(e.target.value)}
                  className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Cadence / Frequency</label>
                  <select
                    value={newSchedFrequency}
                    onChange={(e) => setNewSchedFrequency(e.target.value as PulseReportFrequency)}
                    className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                  >
                    <option value="MONTHLY">Monthly</option>
                    <option value="WEEKLY">Weekly</option>
                    <option value="DAILY">Daily</option>
                  </select>
                </div>
                <div>
                  <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Publication Format</label>
                  <select
                    value={newSchedReportType}
                    onChange={(e) => setNewSchedReportType(e.target.value as PulseReportType)}
                    className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                  >
                    <option value="MONTHLY_EXECUTIVE">Executive Monthly</option>
                    <option value="WEEKLY_MANAGEMENT">Weekly Management</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Active Dispatch Channels</label>
                <div className="flex items-center gap-4">
                  {(['EMAIL', 'WHATSAPP', 'TELEGRAM'] as PulseDeliveryChannel[]).map((ch) => (
                    <label key={ch} className="inline-flex items-center gap-1.5 text-xs text-slate-700 dark:text-slate-300 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={newSchedChannels.includes(ch)}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setNewSchedChannels([...newSchedChannels, ch]);
                          } else {
                            if (newSchedChannels.length > 1) {
                              setNewSchedChannels(newSchedChannels.filter((c) => c !== ch));
                            }
                          }
                        }}
                        className="rounded border-surface-border text-indigo-600 focus:ring-indigo-500"
                      />
                      <span>{ch}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Trigger Time (HH:MM)</label>
                  <input
                    type="time"
                    value={newSchedTime}
                    onChange={(e) => setNewSchedTime(e.target.value)}
                    className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                    required
                  />
                </div>
                <div>
                  <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Timezone</label>
                  <select
                    value={newSchedTimezone}
                    onChange={(e) => setNewSchedTimezone(e.target.value)}
                    className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                  >
                    <option value="UTC">UTC</option>
                    <option value="America/New_York">America/New_York (EST/EDT)</option>
                    <option value="America/Los_Angeles">America/Los_Angeles (PST/PDT)</option>
                    <option value="Europe/London">Europe/London (GMT/BST)</option>
                    <option value="Asia/Tokyo">Asia/Tokyo (JST)</option>
                  </select>
                </div>
              </div>

              {newSchedFrequency === 'MONTHLY' && (
                <div>
                  <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Day of Month (1-31)</label>
                  <input
                    type="number"
                    min={1}
                    max={31}
                    value={newSchedDayOfMonth}
                    onChange={(e) => setNewSchedDayOfMonth(parseInt(e.target.value) || 1)}
                    className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                  />
                </div>
              )}

              {newSchedFrequency === 'WEEKLY' && (
                <div>
                  <label className="block font-medium text-slate-700 dark:text-slate-300 mb-1">Day of Week</label>
                  <select
                    value={newSchedDayOfWeek}
                    onChange={(e) => setNewSchedDayOfWeek(parseInt(e.target.value))}
                    className="w-full border border-surface-border rounded-lg px-3 py-2 bg-surface text-slate-900 dark:text-white"
                  >
                    <option value={0}>Monday</option>
                    <option value={1}>Tuesday</option>
                    <option value={2}>Wednesday</option>
                    <option value={3}>Thursday</option>
                    <option value={4}>Friday</option>
                    <option value={5}>Saturday</option>
                    <option value={6}>Sunday</option>
                  </select>
                </div>
              )}

              {/* Initial Primary Recipient */}
              <div className="pt-2 border-t border-surface-border space-y-2">
                <span className="font-semibold text-slate-800 dark:text-slate-200 block text-xs">Primary Recipient</span>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-slate-500 dark:text-slate-400 mb-1">Name</label>
                    <input
                      type="text"
                      value={newRecipientName}
                      onChange={(e) => setNewRecipientName(e.target.value)}
                      className="w-full border border-surface-border rounded-lg px-3 py-1.5 bg-surface text-slate-900 dark:text-white"
                      required
                    />
                  </div>
                  <div>
                    <label className="block text-slate-500 dark:text-slate-400 mb-1">Channel</label>
                    <select
                      value={newRecipientChannel}
                      onChange={(e) => setNewRecipientChannel(e.target.value as PulseDeliveryChannel)}
                      className="w-full border border-surface-border rounded-lg px-3 py-1.5 bg-surface text-slate-900 dark:text-white"
                    >
                      <option value="EMAIL">Email</option>
                      <option value="WHATSAPP">WhatsApp</option>
                      <option value="TELEGRAM">Telegram</option>
                    </select>
                  </div>
                </div>
                <div>
                  <label className="block text-slate-500 dark:text-slate-400 mb-1">Destination Address / Number</label>
                  <input
                    type="text"
                    value={newRecipientDest}
                    onChange={(e) => setNewRecipientDest(e.target.value)}
                    placeholder="email@company.com or +14155552671"
                    className="w-full border border-surface-border rounded-lg px-3 py-1.5 bg-surface text-slate-900 dark:text-white font-mono"
                    required
                  />
                </div>
              </div>

              <div className="pt-2 flex justify-end gap-3">
                <button
                  type="button"
                  onClick={() => setShowScheduleModal(false)}
                  className="px-4 py-2 border border-surface-border text-slate-700 dark:text-slate-300 hover:bg-surface-elevated font-medium rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingSchedule}
                  className="px-4 py-2 bg-indigo-600 hover:bg-indigo-700 disabled:bg-slate-300 dark:disabled:bg-slate-700 text-white font-medium rounded-lg flex items-center gap-2"
                >
                  {savingSchedule ? (
                    <span>Registering Schedule...</span>
                  ) : (
                    <>
                      <Clock className="w-4 h-4" />
                      <span>Activate Schedule</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
