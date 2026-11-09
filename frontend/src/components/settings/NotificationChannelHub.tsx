import React, { useState, useEffect, useCallback } from 'react';
import {
  Mail,
  Send,
  MessageCircle,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  Unlink2,
  Eye,
  EyeOff,
  Zap,
} from 'lucide-react';
import {
  getPulseChannelStatuses,
  configurePulseChannel,
  disconnectPulseChannel,
  verifyPulseDestination,
  sendPulseTestDispatch,
  listPulseReports,
} from '../../services/pulse';
import {
  PulseChannelStatusItem,
  PulseDeliveryChannel,
  PulseChannelConfigureRequest,
  PulseDestinationVerifyResponse,
  PulseDeliveryLogItem,
  PulseReportListItem,
} from '../../types/api';

interface NotificationChannelHubProps {
  onStatusChange?: () => void;
}

export const NotificationChannelHub: React.FC<NotificationChannelHubProps> = ({
  onStatusChange,
}) => {
  const [channelStatuses, setChannelStatuses] = useState<PulseChannelStatusItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [savingChannel, setSavingChannel] = useState<string | null>(null);
  const [disconnectingChannel, setDisconnectingChannel] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Email Config State
  const [emailUseMailpit, setEmailUseMailpit] = useState<boolean>(true);
  const [emailSmtpHost, setEmailSmtpHost] = useState<string>('127.0.0.1');
  const [emailSmtpPort, setEmailSmtpPort] = useState<number>(1025);
  const [emailSmtpUser, setEmailSmtpUser] = useState<string>('');
  const [emailSmtpPassword, setEmailSmtpPassword] = useState<string>('');
  const [emailFromAddress, setEmailFromAddress] = useState<string>('pulse-reports@nexus.local');

  // Telegram Config State
  const [telegramBotToken, setTelegramBotToken] = useState<string>('');
  const [showTelegramToken, setShowTelegramToken] = useState<boolean>(false);

  // WhatsApp Config State
  const [whatsappPhoneId, setWhatsappPhoneId] = useState<string>('');
  const [whatsappApiToken, setWhatsappApiToken] = useState<string>('');
  const [whatsappBizAcctId, setWhatsappBizAcctId] = useState<string>('');
  const [whatsappRehearsalMock, setWhatsappRehearsalMock] = useState<boolean>(true);
  const [showWhatsappToken, setShowWhatsappToken] = useState<boolean>(false);

  // Active configure modal
  const [activeConfigureChannel, setActiveConfigureChannel] = useState<PulseDeliveryChannel | null>(null);

  // Verification tool state
  const [verifyChannel, setVerifyChannel] = useState<PulseDeliveryChannel>('EMAIL');
  const [verifyDest, setVerifyDest] = useState<string>('');
  const [verifying, setVerifying] = useState<boolean>(false);
  const [verifyResult, setVerifyResult] = useState<PulseDestinationVerifyResponse | null>(null);

  // Test Dispatch tool state
  const [availableReports, setAvailableReports] = useState<PulseReportListItem[]>([]);
  const [dispatchReportId, setDispatchReportId] = useState<string>('');
  const [dispatchChannel, setDispatchChannel] = useState<PulseDeliveryChannel>('EMAIL');
  const [dispatchDestination, setDispatchDestination] = useState<string>('owner@nexus.local');
  const [dispatchRecipientName, setDispatchRecipientName] = useState<string>('Store General Manager');
  const [dispatching, setDispatching] = useState<boolean>(false);
  const [dispatchResult, setDispatchResult] = useState<PulseDeliveryLogItem | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [statuses, reportsRes] = await Promise.all([
        getPulseChannelStatuses(),
        listPulseReports(1, 10).catch(() => ({ success: false, data: { items: [], total_count: 0, page: 1, page_size: 10 } })),
      ]);
      setChannelStatuses(statuses);
      if (reportsRes.success && reportsRes.data?.items?.length) {
        setAvailableReports(reportsRes.data.items);
        if (!dispatchReportId) {
          setDispatchReportId(reportsRes.data.items[0].id);
        }
      }
    } catch (err: any) {
      console.error('Failed to load channel statuses:', err);
    } finally {
      setLoading(false);
    }
  }, [dispatchReportId]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const emailStatus = channelStatuses.find((s) => s.channel === 'EMAIL');
  const telegramStatus = channelStatuses.find((s) => s.channel === 'TELEGRAM');
  const whatsappStatus = channelStatuses.find((s) => s.channel === 'WHATSAPP');

  // Configure Email
  const handleSaveEmail = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingChannel('EMAIL');
    try {
      const payload: PulseChannelConfigureRequest = {
        channel: 'EMAIL',
        use_mailpit: emailUseMailpit,
        smtp_host: emailUseMailpit ? '127.0.0.1' : emailSmtpHost,
        smtp_port: emailUseMailpit ? 1025 : emailSmtpPort,
        smtp_user: emailUseMailpit ? undefined : emailSmtpUser,
        smtp_password: emailUseMailpit ? undefined : emailSmtpPassword,
        from_email: emailFromAddress,
      };
      await configurePulseChannel(payload);
      showToast('Email delivery configuration updated successfully.');
      setActiveConfigureChannel(null);
      await loadData();
      onStatusChange?.();
    } catch (err: any) {
      showToast(err.message || 'Failed to configure email.');
    } finally {
      setSavingChannel(null);
    }
  };

  // Configure Telegram
  const handleSaveTelegram = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!telegramBotToken.trim()) {
      showToast('Please provide a Telegram bot token.');
      return;
    }
    setSavingChannel('TELEGRAM');
    try {
      const payload: PulseChannelConfigureRequest = {
        channel: 'TELEGRAM',
        bot_token: telegramBotToken.trim(),
      };
      await configurePulseChannel(payload);
      showToast('Telegram bot verified and saved successfully!');
      setActiveConfigureChannel(null);
      await loadData();
      onStatusChange?.();
    } catch (err: any) {
      showToast(err.message || 'Telegram bot verification failed.');
    } finally {
      setSavingChannel(null);
    }
  };

  // Configure WhatsApp
  const handleSaveWhatsApp = async (e: React.FormEvent) => {
    e.preventDefault();
    setSavingChannel('WHATSAPP');
    try {
      let payload: PulseChannelConfigureRequest;
      if (whatsappRehearsalMock) {
        payload = {
          channel: 'WHATSAPP',
          whatsapp_phone_number_id: 'mock_phone_id',
          whatsapp_api_token: 'mock_token',
          whatsapp_business_account_id: 'mock_waba_id',
        };
      } else {
        if (!whatsappPhoneId.trim() || !whatsappApiToken.trim()) {
          showToast('Please provide Meta Phone Number ID and API Token.');
          setSavingChannel(null);
          return;
        }
        payload = {
          channel: 'WHATSAPP',
          whatsapp_phone_number_id: whatsappPhoneId.trim(),
          whatsapp_api_token: whatsappApiToken.trim(),
          whatsapp_business_account_id: whatsappBizAcctId.trim() || undefined,
        };
      }
      await configurePulseChannel(payload);
      showToast('WhatsApp configuration saved.');
      setActiveConfigureChannel(null);
      await loadData();
      onStatusChange?.();
    } catch (err: any) {
      showToast(err.message || 'Failed to save WhatsApp configuration.');
    } finally {
      setSavingChannel(null);
    }
  };

  // Disconnect Channel
  const handleDisconnect = async (channel: PulseDeliveryChannel) => {
    if (!confirm(`Are you sure you want to disconnect ${channel}? It will revert to the safe rehearsal sandbox.`)) {
      return;
    }
    setDisconnectingChannel(channel);
    try {
      await disconnectPulseChannel(channel);
      showToast(`${channel} channel disconnected and reset to sandbox.`);
      await loadData();
      onStatusChange?.();
    } catch (err: any) {
      showToast(err.message || `Failed to disconnect ${channel}.`);
    } finally {
      setDisconnectingChannel(null);
    }
  };

  // Verify Destination
  const handleVerifyDestination = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!verifyDest.trim()) return;
    setVerifying(true);
    setVerifyResult(null);
    try {
      const res = await verifyPulseDestination({
        channel: verifyChannel,
        destination: verifyDest.trim(),
      });
      setVerifyResult(res);
    } catch (err: any) {
      setVerifyResult({
        valid: false,
        channel: verifyChannel,
        destination: verifyDest.trim(),
        error: err.message || 'Validation request failed.',
      });
    } finally {
      setVerifying(false);
    }
  };

  // Dispatch Test Report
  const handleSendTestDispatch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!dispatchDestination.trim()) {
      showToast('Please enter a recipient destination.');
      return;
    }
    const reportToUse = dispatchReportId || (availableReports[0]?.id ?? 'mock_report_summary');
    setDispatching(true);
    setDispatchResult(null);
    try {
      const res = await sendPulseTestDispatch({
        report_id: reportToUse,
        channel: dispatchChannel,
        destination: dispatchDestination.trim(),
        recipient_name: dispatchRecipientName.trim() || undefined,
      });
      setDispatchResult(res);
      showToast(`Test message sent via ${dispatchChannel}! Status: ${res.status}`);
      onStatusChange?.();
    } catch (err: any) {
      showToast(err.message || 'Test dispatch failed.');
    } finally {
      setDispatching(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Toast */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 bg-slate-900 text-white px-5 py-3 rounded-lg shadow-xl border border-slate-700 animate-slide-up">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-sm font-medium">{toastMessage}</span>
        </div>
      )}

      {/* Header Overview Card */}
      <div className="bg-surface rounded-xl border border-surface-border p-5 shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
                Manager Self-Service Notification Hub
              </h3>
              <span className="px-2 py-0.5 text-xs font-semibold rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-800">
                ₹0.00 / mo Ready
              </span>
            </div>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              Connect and verify manager channels for automated intelligence briefs and executive alerts.
            </p>
          </div>
          <button
            onClick={loadData}
            disabled={loading}
            className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-medium rounded-lg border border-surface-border bg-surface hover:bg-surface-elevated text-slate-700 dark:text-slate-300 transition-colors"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            <span>Refresh Statuses</span>
          </button>
        </div>
      </div>

      {/* 3 Channel Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {/* ============================================================== */}
        {/* CARD 1: EMAIL (MAILPIT & SMTP) */}
        {/* ============================================================== */}
        <div className="bg-surface rounded-xl border border-surface-border p-5 flex flex-col justify-between shadow-xs transition-all hover:border-slate-300 dark:hover:border-slate-600">
          <div>
            <div className="flex items-center justify-between">
              <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400 flex items-center justify-center">
                <Mail className="w-5 h-5" />
              </div>
              <span
                className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                  emailStatus?.status === 'LOCAL_MAILPIT'
                    ? 'bg-emerald-100 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-800'
                    : emailStatus?.is_live
                    ? 'bg-blue-100 dark:bg-blue-950/50 text-blue-700 dark:text-blue-400 border border-blue-300 dark:border-blue-800'
                    : 'bg-amber-100 dark:bg-amber-950/50 text-amber-700 dark:text-amber-400 border border-amber-300 dark:border-amber-800'
                }`}
              >
                {emailStatus?.status === 'LOCAL_MAILPIT'
                  ? 'Local Mailpit (₹0)'
                  : emailStatus?.is_live
                  ? 'SMTP Configured'
                  : 'Safe Sandbox'}
              </span>
            </div>

            <h4 className="text-base font-semibold text-slate-900 dark:text-white mt-4">
              Email Notifications
            </h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Delivers executive PDF reports and formatted KPI digests to leadership inboxes.
            </p>

            <div className="mt-4 p-3 rounded-lg bg-surface-elevated border border-surface-border space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">Mode:</span>
                <span className="font-mono font-medium text-slate-700 dark:text-slate-300">
                  {emailStatus?.status || 'LOCAL_MAILPIT'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">From / Hint:</span>
                <span className="font-mono font-medium text-slate-700 dark:text-slate-300 truncate max-w-[150px]">
                  {emailStatus?.destination_hint || '127.0.0.1:1025'}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-5 pt-4 border-t border-surface-border flex items-center justify-between gap-2">
            <a
              href="http://localhost:8025"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 text-xs text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
              title="Open Mailpit Web Inbox to inspect local emails"
            >
              <span>Mailpit Inbox (8025)</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </a>
            <button
              onClick={() => setActiveConfigureChannel('EMAIL')}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white transition-colors"
            >
              Configure
            </button>
          </div>
        </div>

        {/* ============================================================== */}
        {/* CARD 2: TELEGRAM BOT */}
        {/* ============================================================== */}
        <div className="bg-surface rounded-xl border border-surface-border p-5 flex flex-col justify-between shadow-xs transition-all hover:border-slate-300 dark:hover:border-slate-600">
          <div>
            <div className="flex items-center justify-between">
              <div className="w-10 h-10 rounded-lg bg-sky-100 dark:bg-sky-950/50 text-sky-600 dark:text-sky-400 flex items-center justify-center">
                <Send className="w-5 h-5" />
              </div>
              <span
                className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                  telegramStatus?.is_live
                    ? 'bg-emerald-100 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-800'
                    : 'bg-amber-100 dark:bg-amber-950/50 text-amber-700 dark:text-amber-400 border border-amber-300 dark:border-amber-800'
                }`}
              >
                {telegramStatus?.is_live ? 'Active Bot' : 'Rehearsal Sandbox'}
              </span>
            </div>

            <h4 className="text-base font-semibold text-slate-900 dark:text-white mt-4">
              Telegram Manager Bot
            </h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Sends instant critical alerts, morning executive briefings, and secure report download links.
            </p>

            <div className="mt-4 p-3 rounded-lg bg-surface-elevated border border-surface-border space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">Bot Handle:</span>
                <span className="font-mono font-medium text-slate-700 dark:text-slate-300">
                  {telegramStatus?.provider_details?.bot_username
                    ? `@${telegramStatus.provider_details.bot_username}`
                    : 'Sandbox Bot'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">Security:</span>
                <span className="text-emerald-600 dark:text-emerald-400 font-medium">
                  {telegramStatus?.is_live ? 'Verified via getMe' : 'Zero-cost Mock'}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-5 pt-4 border-t border-surface-border flex items-center justify-between gap-2">
            {telegramStatus?.is_live ? (
              <button
                onClick={() => handleDisconnect('TELEGRAM')}
                disabled={disconnectingChannel === 'TELEGRAM'}
                className="inline-flex items-center gap-1 text-xs text-rose-600 hover:text-rose-700 dark:text-rose-400"
              >
                <Unlink2 className="w-3.5 h-3.5" />
                <span>Disconnect</span>
              </button>
            ) : (
              <span className="text-xs text-slate-400">Free via @BotFather</span>
            )}
            <button
              onClick={() => setActiveConfigureChannel('TELEGRAM')}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white transition-colors"
            >
              {telegramStatus?.is_live ? 'Update Token' : 'Connect Bot'}
            </button>
          </div>
        </div>

        {/* ============================================================== */}
        {/* CARD 3: WHATSAPP BUSINESS */}
        {/* ============================================================== */}
        <div className="bg-surface rounded-xl border border-surface-border p-5 flex flex-col justify-between shadow-xs transition-all hover:border-slate-300 dark:hover:border-slate-600">
          <div>
            <div className="flex items-center justify-between">
              <div className="w-10 h-10 rounded-lg bg-emerald-100 dark:bg-emerald-950/50 text-emerald-600 dark:text-emerald-400 flex items-center justify-center">
                <MessageCircle className="w-5 h-5" />
              </div>
              <span
                className={`text-xs px-2.5 py-1 rounded-full font-medium ${
                  whatsappStatus?.is_live
                    ? 'bg-emerald-100 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-800'
                    : 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800'
                }`}
              >
                {whatsappStatus?.is_live ? 'Meta Cloud API' : 'Safe Rehearsal (₹0)'}
              </span>
            </div>

            <h4 className="text-base font-semibold text-slate-900 dark:text-white mt-4">
              WhatsApp Business
            </h4>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              High-priority management briefs delivered directly to store owners and executives.
            </p>

            <div className="mt-4 p-3 rounded-lg bg-surface-elevated border border-surface-border space-y-1.5 text-xs">
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">Mode:</span>
                <span className="font-mono font-medium text-slate-700 dark:text-slate-300">
                  {whatsappStatus?.is_live ? 'Live Meta Cloud API' : 'Safe Rehearsal Mock'}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500 dark:text-slate-400">Phone ID:</span>
                <span className="font-mono font-medium text-slate-700 dark:text-slate-300 truncate max-w-[150px]">
                  {whatsappStatus?.destination_hint || 'rehearsal_sandbox'}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-5 pt-4 border-t border-surface-border flex items-center justify-between gap-2">
            {whatsappStatus?.is_live ? (
              <button
                onClick={() => handleDisconnect('WHATSAPP')}
                disabled={disconnectingChannel === 'WHATSAPP'}
                className="inline-flex items-center gap-1 text-xs text-rose-600 hover:text-rose-700 dark:text-rose-400"
              >
                <Unlink2 className="w-3.5 h-3.5" />
                <span>Revert to Mock</span>
              </button>
            ) : (
              <span className="text-xs text-slate-400">No Meta fees incurred</span>
            )}
            <button
              onClick={() => setActiveConfigureChannel('WHATSAPP')}
              className="px-3 py-1.5 text-xs font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white transition-colors"
            >
              Configure
            </button>
          </div>
        </div>
      </div>

      {/* Interactive Verification and Test Tools Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* ============================================================== */}
        {/* TOOL 1: DESTINATION FORMAT & CARRIER VERIFIER */}
        {/* ============================================================== */}
        <div className="bg-surface rounded-xl border border-surface-border p-5 shadow-xs">
          <div className="flex items-center gap-2 mb-2">
            <ShieldCheck className="w-5 h-5 text-indigo-600 dark:text-indigo-400" />
            <h4 className="text-sm font-semibold text-slate-900 dark:text-white">
              Recipient Destination Verifier
            </h4>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
            Pre-flight test recipient phone numbers, email addresses, or Telegram chat IDs for format compliance and delivery routing.
          </p>

          <form onSubmit={handleVerifyDestination} className="space-y-4">
            <div className="grid grid-cols-3 gap-2">
              {(['EMAIL', 'TELEGRAM', 'WHATSAPP'] as PulseDeliveryChannel[]).map((c) => (
                <button
                  type="button"
                  key={c}
                  onClick={() => {
                    setVerifyChannel(c);
                    setVerifyResult(null);
                  }}
                  className={`py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                    verifyChannel === c
                      ? 'bg-indigo-600 text-white border-indigo-600'
                      : 'bg-surface-elevated text-slate-700 dark:text-slate-300 border-surface-border hover:bg-surface-highlight'
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                {verifyChannel === 'EMAIL' && 'Email Address (e.g. cfo@company.com)'}
                {verifyChannel === 'TELEGRAM' && 'Telegram Numeric Chat ID (e.g. 123456789)'}
                {verifyChannel === 'WHATSAPP' && 'Phone Number with Country Code (e.g. +14155552671)'}
              </label>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={verifyDest}
                  onChange={(e) => setVerifyDest(e.target.value)}
                  placeholder={
                    verifyChannel === 'EMAIL'
                      ? 'manager@domain.com'
                      : verifyChannel === 'TELEGRAM'
                      ? '123456789'
                      : '+14155552671'
                  }
                  className="flex-1 px-3 py-2 text-sm rounded-lg border border-surface-border bg-surface text-slate-900 dark:text-white focus:outline-hidden focus:ring-2 focus:ring-indigo-500 font-mono"
                />
                <button
                  type="submit"
                  disabled={verifying || !verifyDest.trim()}
                  className="px-4 py-2 text-xs font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white transition-colors flex items-center gap-1.5"
                >
                  {verifying ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <ShieldCheck className="w-3.5 h-3.5" />}
                  <span>Verify</span>
                </button>
              </div>
            </div>

            {verifyResult && (
              <div
                className={`p-3 rounded-lg border text-xs flex items-start gap-2.5 ${
                  verifyResult.valid
                    ? 'bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800 text-emerald-800 dark:text-emerald-300'
                    : 'bg-rose-50 dark:bg-rose-950/30 border-rose-200 dark:border-rose-800 text-rose-800 dark:text-rose-300'
                }`}
              >
                {verifyResult.valid ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" />
                ) : (
                  <AlertTriangle className="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
                )}
                <div>
                  <p className="font-semibold">
                    {verifyResult.valid ? 'Destination is Valid & Reachable' : 'Validation Error'}
                  </p>
                  <p className="mt-0.5 font-mono text-[11px]">
                    {verifyResult.valid
                      ? `Normalized: ${verifyResult.normalized_destination}`
                      : verifyResult.error}
                  </p>
                </div>
              </div>
            )}
          </form>
        </div>

        {/* ============================================================== */}
        {/* TOOL 2: TEST REPORT DISPATCH SIMULATOR */}
        {/* ============================================================== */}
        <div className="bg-surface rounded-xl border border-surface-border p-5 shadow-xs">
          <div className="flex items-center gap-2 mb-2">
            <Zap className="w-5 h-5 text-amber-500" />
            <h4 className="text-sm font-semibold text-slate-900 dark:text-white">
              Send Live Test Dispatch
            </h4>
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
            Simulate a real executive report dispatch across configured channels without triggering an automated schedule.
          </p>

          <form onSubmit={handleSendTestDispatch} className="space-y-3">
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                  Channel
                </label>
                <select
                  value={dispatchChannel}
                  onChange={(e) => setDispatchChannel(e.target.value as PulseDeliveryChannel)}
                  className="w-full px-3 py-1.5 text-xs rounded-lg border border-surface-border bg-surface text-slate-900 dark:text-white"
                >
                  <option value="EMAIL">Email (Mailpit / SMTP)</option>
                  <option value="TELEGRAM">Telegram Bot</option>
                  <option value="WHATSAPP">WhatsApp Business</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                  Recipient Name
                </label>
                <input
                  type="text"
                  value={dispatchRecipientName}
                  onChange={(e) => setDispatchRecipientName(e.target.value)}
                  className="w-full px-3 py-1.5 text-xs rounded-lg border border-surface-border bg-surface text-slate-900 dark:text-white"
                  placeholder="Manager Name"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                Destination (Email, Chat ID, or Phone)
              </label>
              <input
                type="text"
                value={dispatchDestination}
                onChange={(e) => setDispatchDestination(e.target.value)}
                className="w-full px-3 py-1.5 text-xs rounded-lg border border-surface-border bg-surface text-slate-900 dark:text-white font-mono"
                placeholder={
                  dispatchChannel === 'EMAIL'
                    ? 'owner@nexus.local'
                    : dispatchChannel === 'TELEGRAM'
                    ? '123456789'
                    : '+14155552671'
                }
              />
            </div>

            <div className="flex items-center justify-between pt-1">
              <span className="text-[11px] text-slate-500 dark:text-slate-400">
                Uses snapshot report {availableReports.length > 0 ? `(${availableReports[0].id.slice(0, 8)})` : ''}
              </span>
              <button
                type="submit"
                disabled={dispatching || !dispatchDestination.trim()}
                className="px-4 py-2 text-xs font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white transition-colors flex items-center gap-1.5"
              >
                {dispatching ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                <span>Send Test Brief</span>
              </button>
            </div>

            {dispatchResult && (
              <div className="mt-3 p-3 rounded-lg bg-surface-elevated border border-surface-border text-xs space-y-1">
                <div className="flex justify-between items-center">
                  <span className="font-semibold text-slate-900 dark:text-white">Delivery Result:</span>
                  <span
                    className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                      dispatchResult.status === 'DELIVERED' || dispatchResult.status === 'SENT'
                        ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                        : 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
                    }`}
                  >
                    {dispatchResult.status}
                  </span>
                </div>
                <div className="text-slate-500 dark:text-slate-400 font-mono text-[11px]">
                  Log #{dispatchResult.id} | External ID: {dispatchResult.external_message_id || 'LOCAL_SIMULATION'}
                </div>
              </div>
            )}
          </form>
        </div>
      </div>

      {/* ============================================================== */}
      {/* CONFIGURATION MODAL */}
      {/* ============================================================== */}
      {activeConfigureChannel && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/60 backdrop-blur-xs p-4 overflow-y-auto">
          <div className="bg-surface rounded-2xl border border-surface-border shadow-2xl max-w-xl w-full p-6 text-slate-900 dark:text-white my-8">
            <div className="flex items-center justify-between pb-4 border-b border-surface-border">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-indigo-100 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400">
                  {activeConfigureChannel === 'EMAIL' && <Mail className="w-5 h-5" />}
                  {activeConfigureChannel === 'TELEGRAM' && <Send className="w-5 h-5" />}
                  {activeConfigureChannel === 'WHATSAPP' && <MessageCircle className="w-5 h-5" />}
                </div>
                <div>
                  <h3 className="text-base font-bold">
                    Configure {activeConfigureChannel === 'EMAIL' ? 'Email (Mailpit / SMTP)' : activeConfigureChannel === 'TELEGRAM' ? 'Telegram Bot' : 'WhatsApp Business'}
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Zero-cost local testing and production credentials.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setActiveConfigureChannel(null)}
                className="p-1 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-200"
              >
                ✕
              </button>
            </div>

            {/* EMAIL FORM */}
            {activeConfigureChannel === 'EMAIL' && (
              <form onSubmit={handleSaveEmail} className="mt-4 space-y-4">
                <div className="p-3 rounded-lg bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-900 text-xs text-blue-900 dark:text-blue-300">
                  <p className="font-semibold mb-1">Local Development Standard (₹0.00/mo)</p>
                  <p>
                    By default, NEXUS runs Mailpit on port 1025. Emails are captured safely without external network calls. You can view all captured emails in the Mailpit web interface at <a href="http://localhost:8025" target="_blank" rel="noreferrer" className="underline font-bold">http://localhost:8025</a>.
                  </p>
                </div>

                <div className="flex items-center gap-3 p-3 rounded-lg border border-surface-border bg-surface-elevated">
                  <input
                    type="checkbox"
                    id="mailpit-toggle"
                    checked={emailUseMailpit}
                    onChange={(e) => setEmailUseMailpit(e.target.checked)}
                    className="w-4 h-4 text-indigo-600 rounded-sm focus:ring-indigo-500"
                  />
                  <label htmlFor="mailpit-toggle" className="text-xs font-medium cursor-pointer">
                    Enable Zero-Cost Local Mailpit (Recommended for Local Operations)
                  </label>
                </div>

                {!emailUseMailpit && (
                  <div className="space-y-3 pt-2">
                    <div className="grid grid-cols-3 gap-3">
                      <div className="col-span-2">
                        <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                          SMTP Server Host
                        </label>
                        <input
                          type="text"
                          value={emailSmtpHost}
                          onChange={(e) => setEmailSmtpHost(e.target.value)}
                          placeholder="smtp.sendgrid.net"
                          className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                          SMTP Port
                        </label>
                        <input
                          type="number"
                          value={emailSmtpPort}
                          onChange={(e) => setEmailSmtpPort(parseInt(e.target.value) || 587)}
                          className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface font-mono"
                        />
                      </div>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                          SMTP Username
                        </label>
                        <input
                          type="text"
                          value={emailSmtpUser}
                          onChange={(e) => setEmailSmtpUser(e.target.value)}
                          placeholder="apikey"
                          className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface font-mono"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                          SMTP Password
                        </label>
                        <input
                          type="password"
                          value={emailSmtpPassword}
                          onChange={(e) => setEmailSmtpPassword(e.target.value)}
                          className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface font-mono"
                        />
                      </div>
                    </div>
                  </div>
                )}

                <div>
                  <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                    From Address
                  </label>
                  <input
                    type="email"
                    value={emailFromAddress}
                    onChange={(e) => setEmailFromAddress(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface font-mono"
                  />
                </div>

                <div className="flex justify-end gap-3 pt-4 border-t border-surface-border">
                  <button
                    type="button"
                    onClick={() => setActiveConfigureChannel(null)}
                    className="px-4 py-2 text-xs font-medium rounded-lg border border-surface-border hover:bg-surface-elevated"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={savingChannel === 'EMAIL'}
                    className="px-4 py-2 text-xs font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white flex items-center gap-1.5"
                  >
                    {savingChannel === 'EMAIL' && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                    <span>Save Email Configuration</span>
                  </button>
                </div>
              </form>
            )}

            {/* TELEGRAM FORM */}
            {activeConfigureChannel === 'TELEGRAM' && (
              <form onSubmit={handleSaveTelegram} className="mt-4 space-y-4">
                <div className="p-3 rounded-lg bg-surface-elevated border border-surface-border text-xs space-y-1.5">
                  <p className="font-semibold text-slate-900 dark:text-white">How to connect Telegram in 60 seconds:</p>
                  <ol className="list-decimal list-inside space-y-1 text-slate-600 dark:text-slate-300">
                    <li>Open Telegram and search for <b>@BotFather</b>.</li>
                    <li>Send <code>/newbot</code> and follow prompts to pick a name and username.</li>
                    <li>Copy the HTTP API Bot Token provided by BotFather.</li>
                    <li>Message <b>@userinfobot</b> on Telegram to get your numeric Chat ID for receiving briefs.</li>
                  </ol>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                    Telegram Bot Token
                  </label>
                  <div className="relative">
                    <input
                      type={showTelegramToken ? 'text' : 'password'}
                      value={telegramBotToken}
                      onChange={(e) => setTelegramBotToken(e.target.value)}
                      placeholder="123456789:ABCdefGHIjklMNOpqrSTUvwxYZ"
                      className="w-full pl-3 pr-10 py-2 text-xs rounded-lg border border-surface-border bg-surface font-mono"
                    />
                    <button
                      type="button"
                      onClick={() => setShowTelegramToken(!showTelegramToken)}
                      className="absolute right-2.5 top-2.5 text-slate-400 hover:text-slate-600"
                    >
                      {showTelegramToken ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                    </button>
                  </div>
                  <p className="text-[11px] text-slate-500 mt-1">
                    NEXUS calls Telegram's <code>getMe</code> endpoint automatically upon save to verify token authenticity.
                  </p>
                </div>

                <div className="flex justify-end gap-3 pt-4 border-t border-surface-border">
                  <button
                    type="button"
                    onClick={() => setActiveConfigureChannel(null)}
                    className="px-4 py-2 text-xs font-medium rounded-lg border border-surface-border hover:bg-surface-elevated"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={savingChannel === 'TELEGRAM'}
                    className="px-4 py-2 text-xs font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white flex items-center gap-1.5"
                  >
                    {savingChannel === 'TELEGRAM' && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                    <span>Verify & Link Bot</span>
                  </button>
                </div>
              </form>
            )}

            {/* WHATSAPP FORM */}
            {activeConfigureChannel === 'WHATSAPP' && (
              <form onSubmit={handleSaveWhatsApp} className="mt-4 space-y-4">
                <div className="p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-900 text-xs text-emerald-900 dark:text-emerald-300">
                  <p className="font-semibold mb-1">Zero-Cost Safe Rehearsal Mock</p>
                  <p>
                    You can test the entire WhatsApp delivery flow without a paid Meta Business Account. Safe rehearsal records deliveries, verifies recipient numbers, and logs message payloads without sending SMS/WhatsApp messages.
                  </p>
                </div>

                <div className="flex items-center gap-3 p-3 rounded-lg border border-surface-border bg-surface-elevated">
                  <input
                    type="checkbox"
                    id="wa-mock-toggle"
                    checked={whatsappRehearsalMock}
                    onChange={(e) => setWhatsappRehearsalMock(e.target.checked)}
                    className="w-4 h-4 text-emerald-600 rounded-sm focus:ring-emerald-500"
                  />
                  <label htmlFor="wa-mock-toggle" className="text-xs font-medium cursor-pointer">
                    Enable Safe Rehearsal Mock (Recommended for Zero-Cost Beta)
                  </label>
                </div>

                {!whatsappRehearsalMock && (
                  <div className="space-y-3 pt-2">
                    <div>
                      <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                        Meta Phone Number ID
                      </label>
                      <input
                        type="text"
                        value={whatsappPhoneId}
                        onChange={(e) => setWhatsappPhoneId(e.target.value)}
                        placeholder="100987654321098"
                        className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface font-mono"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                        WhatsApp Business Account ID (WABA ID)
                      </label>
                      <input
                        type="text"
                        value={whatsappBizAcctId}
                        onChange={(e) => setWhatsappBizAcctId(e.target.value)}
                        placeholder="998877665544332"
                        className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface font-mono"
                      />
                    </div>

                    <div>
                      <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                        Meta Cloud API Bearer Token
                      </label>
                      <div className="relative">
                        <input
                          type={showWhatsappToken ? 'text' : 'password'}
                          value={whatsappApiToken}
                          onChange={(e) => setWhatsappApiToken(e.target.value)}
                          placeholder="EAAB..."
                          className="w-full pl-3 pr-10 py-2 text-xs rounded-lg border border-surface-border bg-surface font-mono"
                        />
                        <button
                          type="button"
                          onClick={() => setShowWhatsappToken(!showWhatsappToken)}
                          className="absolute right-2.5 top-2.5 text-slate-400 hover:text-slate-600"
                        >
                          {showWhatsappToken ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                <div className="flex justify-end gap-3 pt-4 border-t border-surface-border">
                  <button
                    type="button"
                    onClick={() => setActiveConfigureChannel(null)}
                    className="px-4 py-2 text-xs font-medium rounded-lg border border-surface-border hover:bg-surface-elevated"
                  >
                    Cancel
                  </button>
                  <button
                    type="submit"
                    disabled={savingChannel === 'WHATSAPP'}
                    className="px-4 py-2 text-xs font-medium rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white flex items-center gap-1.5"
                  >
                    {savingChannel === 'WHATSAPP' && <RefreshCw className="w-3.5 h-3.5 animate-spin" />}
                    <span>Save WhatsApp Configuration</span>
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
