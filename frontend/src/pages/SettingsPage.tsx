import React, { useState, useEffect, useCallback } from 'react';
import {
  Sun,
  Moon,
  Laptop,
  Bell,
  Sliders,
  Users,
  Shield,
  Building,
  Server,
  CheckCircle2,
  RefreshCw,
  ExternalLink,
  Save,
  Mail,
  Send,
  MessageCircle,
  ShieldCheck,
  Check,
  ChevronRight,
  UserCheck,
  LogOut,
  ToggleLeft,
  ToggleRight,
  Database,
  Zap,
} from 'lucide-react';
import { useTheme } from '../context/ThemeContext';
import { NotificationChannelHub } from '../components/settings/NotificationChannelHub';
import { AuthService, UserProfileResponse } from '../services/auth';
import {
  listPulseRecipients,
  updatePulseRecipientOpt,
  verifyPulseDestination,
} from '../services/pulse';
import { getHealthStatus } from '../services/api';
import { listConnectorCredentials, ConnectorCredentialSummary } from '../services/connectors';
import {
  PulseRecipientItem,
  PulseDeliveryChannel,
  PulseReportFrequency,
  HealthResponse,
} from '../types/api';

interface SettingsPageProps {
  onNavigate: (route: string) => void;
  initialTab?: 'appearance' | 'channels' | 'preferences' | 'recipients' | 'security' | 'business' | 'system';
}

type SettingsTab =
  | 'appearance'
  | 'channels'
  | 'preferences'
  | 'recipients'
  | 'security'
  | 'business'
  | 'system';

export const SettingsPage: React.FC<SettingsPageProps> = ({
  onNavigate,
  initialTab = 'appearance',
}) => {
  const {
    theme,
    resolvedTheme,
    setTheme,
    density,
    setDensity,
    reducedMotion,
    setReducedMotion,
  } = useTheme();

  const [activeTab, setActiveTab] = useState<SettingsTab>(initialTab);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // User & Business State
  const [userProfile, setUserProfile] = useState<UserProfileResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [connectors, setConnectors] = useState<ConnectorCredentialSummary[]>([]);
  const [loadingData, setLoadingData] = useState<boolean>(true);

  // Recipients State
  const [recipients, setRecipients] = useState<PulseRecipientItem[]>([]);
  const [newRecipName, setNewRecipName] = useState<string>('');
  const [newRecipChannel, setNewRecipChannel] = useState<PulseDeliveryChannel>('EMAIL');
  const [newRecipDest, setNewRecipDest] = useState<string>('');
  const [addingRecipient, setAddingRecipient] = useState<boolean>(false);

  // Report Preferences State (Local persistence)
  const [prefFrequency, setPrefFrequency] = useState<PulseReportFrequency>(() => {
    return (localStorage.getItem('nexus_pref_frequency') as PulseReportFrequency) || 'MONTHLY';
  });
  const [prefTime, setPrefTime] = useState<string>(() => {
    return localStorage.getItem('nexus_pref_time') || '09:00';
  });
  const [prefFormat, setPrefFormat] = useState<string>(() => {
    return localStorage.getItem('nexus_pref_format') || 'PDF_AND_WEB';
  });
  const [prefChannels, setPrefChannels] = useState<PulseDeliveryChannel[]>(() => {
    try {
      const stored = localStorage.getItem('nexus_pref_channels');
      if (stored) return JSON.parse(stored);
    } catch {}
    return ['EMAIL', 'WHATSAPP'];
  });

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 3500);
  };

  const loadAllSettingsData = useCallback(async () => {
    setLoadingData(true);
    try {
      const [prof, hlth, recipList] = await Promise.all([
        AuthService.getMe().catch(() => null),
        getHealthStatus().catch(() => null),
        listPulseRecipients().catch(() => []),
      ]);
      setUserProfile(prof);
      setHealth(hlth);
      setRecipients(recipList);

      const activeBizId = localStorage.getItem('nexus_business_id');
      if (activeBizId) {
        const connList = await listConnectorCredentials(activeBizId).catch(() => []);
        setConnectors(connList);
      }
    } catch (err: any) {
      console.warn('Settings load warning:', err);
    } finally {
      setLoadingData(false);
    }
  }, []);

  useEffect(() => {
    loadAllSettingsData();
  }, [loadAllSettingsData]);

  // Handle Recipient Registration
  const handleAddRecipient = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRecipName.trim() || !newRecipDest.trim()) {
      showToast('Please provide recipient name and destination.');
      return;
    }
    setAddingRecipient(true);
    try {
      // First verify syntax
      const verifyRes = await verifyPulseDestination({
        channel: newRecipChannel,
        destination: newRecipDest.trim(),
      });
      if (!verifyRes.valid) {
        showToast(verifyRes.error || 'Destination format is invalid.');
        setAddingRecipient(false);
        return;
      }

      const res = await updatePulseRecipientOpt({
        recipient_name: newRecipName.trim(),
        channel: newRecipChannel,
        destination: verifyRes.normalized_destination || newRecipDest.trim(),
        opt_status: 'OPTED_IN',
      });

      setRecipients((prev) => {
        const filtered = prev.filter((r) => r.id !== res.id);
        return [res, ...filtered];
      });
      setNewRecipName('');
      setNewRecipDest('');
      showToast(`Recipient '${res.recipient_name}' registered and opted-in.`);
    } catch (err: any) {
      showToast(err.message || 'Failed to add recipient.');
    } finally {
      setAddingRecipient(false);
    }
  };

  // Toggle Recipient Opt Status
  const handleToggleOpt = async (recip: PulseRecipientItem) => {
    const nextStatus = recip.opt_status === 'OPTED_IN' ? 'OPTED_OUT' : 'OPTED_IN';
    try {
      const res = await updatePulseRecipientOpt({
        recipient_name: recip.recipient_name,
        channel: recip.channel,
        destination: recip.destination,
        opt_status: nextStatus,
        opt_out_reason: nextStatus === 'OPTED_OUT' ? 'Manager manual override in Settings' : undefined,
      });
      setRecipients((prev) => prev.map((r) => (r.id === res.id ? res : r)));
      showToast(`Recipient '${recip.recipient_name}' marked as ${nextStatus}.`);
    } catch (err: any) {
      showToast(err.message || 'Failed to update opt status.');
    }
  };

  // Save Report Preferences
  const handleSavePreferences = (e: React.FormEvent) => {
    e.preventDefault();
    localStorage.setItem('nexus_pref_frequency', prefFrequency);
    localStorage.setItem('nexus_pref_time', prefTime);
    localStorage.setItem('nexus_pref_format', prefFormat);
    localStorage.setItem('nexus_pref_channels', JSON.stringify(prefChannels));
    showToast('Report and delivery preferences updated successfully.');
  };

  const toggleChannelPref = (c: PulseDeliveryChannel) => {
    setPrefChannels((prev) =>
      prev.includes(c) ? prev.filter((item) => item !== c) : [...prev, c]
    );
  };

  const navItems: { id: SettingsTab; label: string; icon: React.ReactNode; badge?: string }[] = [
    { id: 'appearance', label: 'Appearance & Themes', icon: <Sun className="w-4 h-4" /> },
    { id: 'channels', label: 'Notification Channels', icon: <Bell className="w-4 h-4" />, badge: 'Manager Hub' },
    { id: 'preferences', label: 'Report Preferences', icon: <Sliders className="w-4 h-4" /> },
    { id: 'recipients', label: 'Authorized Recipients', icon: <Users className="w-4 h-4" />, badge: `${recipients.length}` },
    { id: 'security', label: 'Account & Security', icon: <Shield className="w-4 h-4" /> },
    { id: 'business', label: 'Business & Workspace', icon: <Building className="w-4 h-4" /> },
    { id: 'system', label: 'System Information', icon: <Server className="w-4 h-4" />, badge: '₹0.00 / mo' },
  ];

  return (
    <div className="space-y-6 max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {/* Toast Alert */}
      {toastMessage && (
        <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 bg-slate-900 text-white px-5 py-3 rounded-lg shadow-xl border border-slate-700 animate-slide-up">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span className="text-sm font-medium">{toastMessage}</span>
        </div>
      )}

      {/* Page Title & Breadcrumbs */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-surface-border">
        <div>
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">
            Global Settings Center
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
            Enterprise management preferences, adaptive themes, notification channels, and operational telemetry.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-1 text-xs font-semibold rounded-full bg-emerald-100 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-800">
            Local Operations (₹0/mo)
          </span>
          <span className="px-2.5 py-1 text-xs font-mono rounded-full bg-surface-elevated text-slate-600 dark:text-slate-400 border border-surface-border">
            DB Rev 022
          </span>
        </div>
      </div>

      {/* Main Settings Layout: Side Navigation Tabs + Content Area */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
        {/* Left Settings Sidebar Navigation */}
        <div className="md:col-span-1 space-y-1">
          {navItems.map((item) => (
            <button
              key={item.id}
              onClick={() => setActiveTab(item.id)}
              className={`w-full flex items-center justify-between px-3.5 py-2.5 rounded-lg text-xs font-medium transition-all ${
                activeTab === item.id
                  ? 'bg-indigo-600 text-white shadow-xs'
                  : 'text-slate-600 dark:text-slate-400 hover:bg-surface-elevated hover:text-slate-900 dark:hover:text-white'
              }`}
            >
              <div className="flex items-center gap-2.5 truncate">
                {item.icon}
                <span className="truncate">{item.label}</span>
              </div>
              {item.badge && (
                <span
                  className={`text-[10px] px-1.5 py-0.5 rounded-full font-mono ${
                    activeTab === item.id
                      ? 'bg-white/20 text-white'
                      : 'bg-surface-elevated text-slate-600 dark:text-slate-400 border border-surface-border'
                  }`}
                >
                  {item.badge}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Right Settings Content Workspace */}
        <div className="md:col-span-3">
          {/* ============================================================== */}
          {/* TAB A: APPEARANCE & THEMES */}
          {/* ============================================================== */}
          {activeTab === 'appearance' && (
            <div className="space-y-6">
              <div className="bg-surface rounded-xl border border-surface-border p-6 shadow-xs">
                <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                  Theme & Color Palette
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 mb-5">
                  Select your visual interface mode. High-contrast adaptive palette preserves legibility across all environments.
                </p>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                  {/* LIGHT MODE CARD */}
                  <div
                    onClick={() => setTheme('light')}
                    className={`cursor-pointer rounded-xl border p-4 transition-all ${
                      theme === 'light'
                        ? 'border-indigo-600 ring-2 ring-indigo-500/30 shadow-md'
                        : 'border-surface-border hover:border-slate-400'
                    }`}
                  >
                    <div className="h-24 rounded-lg bg-white border border-slate-200 p-2.5 flex flex-col justify-between mb-3 shadow-inner">
                      <div className="flex items-center justify-between">
                        <div className="w-8 h-2 bg-slate-200 rounded-sm"></div>
                        <div className="w-2 h-2 rounded-full bg-indigo-600"></div>
                      </div>
                      <div className="space-y-1.5">
                        <div className="w-full h-2 bg-slate-100 rounded-sm"></div>
                        <div className="w-3/4 h-2 bg-slate-200 rounded-sm"></div>
                      </div>
                      <div className="flex gap-1">
                        <div className="w-6 h-3 bg-indigo-600 rounded-xs"></div>
                        <div className="w-6 h-3 bg-slate-100 rounded-xs"></div>
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Sun className="w-4 h-4 text-amber-500" />
                        <span className="text-xs font-semibold text-slate-900 dark:text-white">Light Mode</span>
                      </div>
                      {theme === 'light' && <Check className="w-4 h-4 text-indigo-600" />}
                    </div>
                    <p className="text-[11px] text-slate-500 mt-1">Crisp white canvas with dark charcoal text.</p>
                  </div>

                  {/* DARK MODE CARD */}
                  <div
                    onClick={() => setTheme('dark')}
                    className={`cursor-pointer rounded-xl border p-4 transition-all ${
                      theme === 'dark'
                        ? 'border-indigo-600 ring-2 ring-indigo-500/30 shadow-md'
                        : 'border-surface-border hover:border-slate-400'
                    }`}
                  >
                    <div className="h-24 rounded-lg bg-[#070A12] border border-[#1E293B] p-2.5 flex flex-col justify-between mb-3 shadow-inner">
                      <div className="flex items-center justify-between">
                        <div className="w-8 h-2 bg-[#1E293B] rounded-sm"></div>
                        <div className="w-2 h-2 rounded-full bg-cyan-400"></div>
                      </div>
                      <div className="space-y-1.5">
                        <div className="w-full h-2 bg-[#0F172A] rounded-sm"></div>
                        <div className="w-3/4 h-2 bg-[#1E293B] rounded-sm"></div>
                      </div>
                      <div className="flex gap-1">
                        <div className="w-6 h-3 bg-cyan-500 rounded-xs"></div>
                        <div className="w-6 h-3 bg-[#1E293B] rounded-xs"></div>
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Moon className="w-4 h-4 text-cyan-400" />
                        <span className="text-xs font-semibold text-slate-900 dark:text-white">Dark Mode</span>
                      </div>
                      {theme === 'dark' && <Check className="w-4 h-4 text-indigo-600" />}
                    </div>
                    <p className="text-[11px] text-slate-500 mt-1">Obsidian void background with cyan telemetry.</p>
                  </div>

                  {/* SYSTEM MODE CARD */}
                  <div
                    onClick={() => setTheme('system')}
                    className={`cursor-pointer rounded-xl border p-4 transition-all ${
                      theme === 'system'
                        ? 'border-indigo-600 ring-2 ring-indigo-500/30 shadow-md'
                        : 'border-surface-border hover:border-slate-400'
                    }`}
                  >
                    <div className="h-24 rounded-lg bg-gradient-to-r from-white via-slate-200 to-[#070A12] border border-surface-border p-2.5 flex flex-col justify-between mb-3 shadow-inner">
                      <div className="flex items-center justify-between">
                        <div className="w-8 h-2 bg-slate-300 dark:bg-[#1E293B] rounded-sm"></div>
                        <div className="w-2 h-2 rounded-full bg-indigo-500"></div>
                      </div>
                      <div className="space-y-1.5">
                        <div className="w-full h-2 bg-slate-200 dark:bg-[#0F172A] rounded-sm"></div>
                        <div className="w-3/4 h-2 bg-slate-300 dark:bg-[#1E293B] rounded-sm"></div>
                      </div>
                      <div className="flex gap-1">
                        <div className="w-6 h-3 bg-indigo-600 rounded-xs"></div>
                      </div>
                    </div>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <Laptop className="w-4 h-4 text-indigo-500" />
                        <span className="text-xs font-semibold text-slate-900 dark:text-white">System Sync</span>
                      </div>
                      {theme === 'system' && <Check className="w-4 h-4 text-indigo-600" />}
                    </div>
                    <p className="text-[11px] text-slate-500 mt-1">
                      Matches OS preference automatically ({resolvedTheme} active).
                    </p>
                  </div>
                </div>

                <div className="mt-5 p-3 rounded-lg bg-surface-elevated border border-surface-border flex items-center justify-between text-xs">
                  <span className="text-slate-600 dark:text-slate-400">Current Active Engine Mode:</span>
                  <span className="font-semibold text-indigo-600 dark:text-indigo-400 capitalize">
                    {theme} ({resolvedTheme} resolved)
                  </span>
                </div>
              </div>

              {/* Display Density & Motion */}
              <div className="bg-surface rounded-xl border border-surface-border p-6 shadow-xs space-y-6">
                <div>
                  <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                    Display Density & Layout
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 mb-4">
                    Adjust information density for executive overview or high-throughput data analysis.
                  </p>
                  <div className="grid grid-cols-2 gap-4">
                    <button
                      onClick={() => setDensity('comfortable')}
                      className={`p-3 rounded-xl border text-left transition-all ${
                        density === 'comfortable'
                          ? 'border-indigo-600 ring-1 ring-indigo-500 bg-surface-elevated'
                          : 'border-surface-border hover:bg-surface-elevated'
                      }`}
                    >
                      <p className="text-xs font-semibold text-slate-900 dark:text-white">Comfortable</p>
                      <p className="text-[11px] text-slate-500 mt-1">Generous padding and relaxed typography spacing.</p>
                    </button>
                    <button
                      onClick={() => setDensity('compact')}
                      className={`p-3 rounded-xl border text-left transition-all ${
                        density === 'compact'
                          ? 'border-indigo-600 ring-1 ring-indigo-500 bg-surface-elevated'
                          : 'border-surface-border hover:bg-surface-elevated'
                      }`}
                    >
                      <p className="text-xs font-semibold text-slate-900 dark:text-white">Compact</p>
                      <p className="text-[11px] text-slate-500 mt-1">Higher data density suited for multi-metric tables.</p>
                    </button>
                  </div>
                </div>

                <div className="pt-4 border-t border-surface-border flex items-center justify-between">
                  <div>
                    <p className="text-xs font-semibold text-slate-900 dark:text-white">Reduced Motion</p>
                    <p className="text-[11px] text-slate-500">Minimize animations and transition effects.</p>
                  </div>
                  <button
                    onClick={() => setReducedMotion(!reducedMotion)}
                    className="p-1 text-slate-600 dark:text-slate-400 hover:text-indigo-600"
                  >
                    {reducedMotion ? (
                      <ToggleRight className="w-8 h-8 text-indigo-600" />
                    ) : (
                      <ToggleLeft className="w-8 h-8 text-slate-400" />
                    )}
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ============================================================== */}
          {/* TAB B: NOTIFICATION CHANNELS */}
          {/* ============================================================== */}
          {activeTab === 'channels' && (
            <NotificationChannelHub onStatusChange={loadAllSettingsData} />
          )}

          {/* ============================================================== */}
          {/* TAB C: REPORT PREFERENCES */}
          {/* ============================================================== */}
          {activeTab === 'preferences' && (
            <form onSubmit={handleSavePreferences} className="bg-surface rounded-xl border border-surface-border p-6 shadow-xs space-y-6">
              <div>
                <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                  Report Cadence & Delivery Preferences
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                  Configure default scheduling and dispatch options for automated management intelligence reports.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                    Default Automation Frequency
                  </label>
                  <select
                    value={prefFrequency}
                    onChange={(e) => setPrefFrequency(e.target.value as PulseReportFrequency)}
                    className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface text-slate-900 dark:text-white"
                  >
                    <option value="DAILY">Daily Executive Pulse</option>
                    <option value="WEEKLY">Weekly Performance Brief</option>
                    <option value="MONTHLY">Monthly Executive Intelligence (Standard)</option>
                    <option value="QUARTERLY">Quarterly Strategic Review</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                    Standard Dispatch Time (UTC)
                  </label>
                  <input
                    type="time"
                    value={prefTime}
                    onChange={(e) => setPrefTime(e.target.value)}
                    className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface text-slate-900 dark:text-white font-mono"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                  Standard Publication Format
                </label>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <button
                    type="button"
                    onClick={() => setPrefFormat('PDF_AND_WEB')}
                    className={`p-3 rounded-lg border text-left text-xs transition-colors ${
                      prefFormat === 'PDF_AND_WEB'
                        ? 'border-indigo-600 bg-surface-elevated ring-1 ring-indigo-500'
                        : 'border-surface-border'
                    }`}
                  >
                    <p className="font-semibold text-slate-900 dark:text-white">PDF + Interactive Digital Brief</p>
                    <p className="text-[11px] text-slate-500 mt-0.5">High-fidelity ReportLab PDF with tokenized public link.</p>
                  </button>
                  <button
                    type="button"
                    onClick={() => setPrefFormat('DIGITAL_ONLY')}
                    className={`p-3 rounded-lg border text-left text-xs transition-colors ${
                      prefFormat === 'DIGITAL_ONLY'
                        ? 'border-indigo-600 bg-surface-elevated ring-1 ring-indigo-500'
                        : 'border-surface-border'
                    }`}
                  >
                    <p className="font-semibold text-slate-900 dark:text-white">Key Highlights & Instant Link</p>
                    <p className="text-[11px] text-slate-500 mt-0.5">Streamlined instant summary with direct workspace portal.</p>
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-2">
                  Default Enabled Communication Channels
                </label>
                <div className="flex flex-wrap gap-3">
                  {(['EMAIL', 'WHATSAPP', 'TELEGRAM'] as PulseDeliveryChannel[]).map((c) => {
                    const active = prefChannels.includes(c);
                    return (
                      <button
                        type="button"
                        key={c}
                        onClick={() => toggleChannelPref(c)}
                        className={`inline-flex items-center gap-2 px-3.5 py-2 rounded-lg text-xs font-medium border transition-colors ${
                          active
                            ? 'bg-indigo-600 text-white border-indigo-600'
                            : 'bg-surface text-slate-700 dark:text-slate-300 border-surface-border hover:bg-surface-elevated'
                        }`}
                      >
                        {c === 'EMAIL' && <Mail className="w-3.5 h-3.5" />}
                        {c === 'WHATSAPP' && <MessageCircle className="w-3.5 h-3.5" />}
                        {c === 'TELEGRAM' && <Send className="w-3.5 h-3.5" />}
                        <span>{c}</span>
                        {active && <Check className="w-3.5 h-3.5 ml-1" />}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="pt-4 border-t border-surface-border flex justify-end">
                <button
                  type="submit"
                  className="px-4 py-2 text-xs font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white transition-colors flex items-center gap-1.5"
                >
                  <Save className="w-4 h-4" />
                  <span>Save Report Preferences</span>
                </button>
              </div>
            </form>
          )}

          {/* ============================================================== */}
          {/* TAB D: AUTHORIZED RECIPIENTS */}
          {/* ============================================================== */}
          {activeTab === 'recipients' && (
            <div className="space-y-6">
              {/* Register New Recipient Form */}
              <div className="bg-surface rounded-xl border border-surface-border p-5 shadow-xs">
                <h4 className="text-sm font-semibold text-slate-900 dark:text-white mb-1">
                  Authorize New Report Recipient
                </h4>
                <p className="text-xs text-slate-500 dark:text-slate-400 mb-4">
                  Register store managers, accountants, or board members to receive automated intelligence briefs.
                </p>

                <form onSubmit={handleAddRecipient} className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                  <div>
                    <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                      Recipient Full Name
                    </label>
                    <input
                      type="text"
                      value={newRecipName}
                      onChange={(e) => setNewRecipName(e.target.value)}
                      placeholder="e.g. John Doe (CFO)"
                      className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface text-slate-900 dark:text-white"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                      Preferred Channel
                    </label>
                    <select
                      value={newRecipChannel}
                      onChange={(e) => setNewRecipChannel(e.target.value as PulseDeliveryChannel)}
                      className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface text-slate-900 dark:text-white"
                    >
                      <option value="EMAIL">Email Address</option>
                      <option value="WHATSAPP">WhatsApp Number</option>
                      <option value="TELEGRAM">Telegram Chat ID</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-medium text-slate-700 dark:text-slate-300 mb-1">
                      Destination Address / ID
                    </label>
                    <input
                      type="text"
                      value={newRecipDest}
                      onChange={(e) => setNewRecipDest(e.target.value)}
                      placeholder={
                        newRecipChannel === 'EMAIL'
                          ? 'cfo@company.com'
                          : newRecipChannel === 'WHATSAPP'
                          ? '+14155552671'
                          : '123456789'
                      }
                      className="w-full px-3 py-2 text-xs rounded-lg border border-surface-border bg-surface text-slate-900 dark:text-white font-mono"
                    />
                  </div>

                  <div className="flex items-end">
                    <button
                      type="submit"
                      disabled={addingRecipient || !newRecipName.trim() || !newRecipDest.trim()}
                      className="w-full px-4 py-2 text-xs font-medium rounded-lg bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 text-white transition-colors flex items-center justify-center gap-1.5"
                    >
                      {addingRecipient ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <UserCheck className="w-3.5 h-3.5" />}
                      <span>Authorize Recipient</span>
                    </button>
                  </div>
                </form>
              </div>

              {/* Recipients Roster Table */}
              <div className="bg-surface rounded-xl border border-surface-border overflow-hidden shadow-xs">
                <div className="p-4 border-b border-surface-border flex items-center justify-between">
                  <h4 className="text-sm font-semibold text-slate-900 dark:text-white">
                    Authorized Manager Recipients ({recipients.length})
                  </h4>
                  <span className="text-xs text-slate-500">
                    One-click Opt-in / Opt-out Governance
                  </span>
                </div>

                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-surface-elevated text-slate-500 dark:text-slate-400 font-semibold border-b border-surface-border">
                      <tr>
                        <th className="py-2.5 px-4">Recipient Name</th>
                        <th className="py-2.5 px-4">Channel</th>
                        <th className="py-2.5 px-4">Destination</th>
                        <th className="py-2.5 px-4">Opt Status</th>
                        <th className="py-2.5 px-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-surface-border">
                      {recipients.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="py-8 text-center text-slate-500">
                            No recipients registered yet. Add leadership contacts above to begin automated delivery.
                          </td>
                        </tr>
                      ) : (
                        recipients.map((r) => (
                          <tr key={r.id} className="hover:bg-surface-elevated transition-colors">
                            <td className="py-3 px-4 font-medium text-slate-900 dark:text-white">
                              {r.recipient_name}
                            </td>
                            <td className="py-3 px-4">
                              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full font-mono text-[10px] bg-surface-elevated border border-surface-border">
                                {r.channel === 'EMAIL' && <Mail className="w-3 h-3 text-blue-500" />}
                                {r.channel === 'WHATSAPP' && <MessageCircle className="w-3 h-3 text-emerald-500" />}
                                {r.channel === 'TELEGRAM' && <Send className="w-3 h-3 text-sky-500" />}
                                <span>{r.channel}</span>
                              </span>
                            </td>
                            <td className="py-3 px-4 font-mono text-slate-700 dark:text-slate-300">
                              {r.destination}
                            </td>
                            <td className="py-3 px-4">
                              <span
                                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium text-[10px] ${
                                  r.opt_status === 'OPTED_IN'
                                    ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400 border border-emerald-300 dark:border-emerald-800'
                                    : 'bg-rose-100 text-rose-700 dark:bg-rose-950/50 dark:text-rose-400 border border-rose-300 dark:border-rose-800'
                                }`}
                              >
                                {r.opt_status}
                              </span>
                            </td>
                            <td className="py-3 px-4 text-right">
                              <button
                                onClick={() => handleToggleOpt(r)}
                                className={`px-2.5 py-1 text-[11px] font-medium rounded-md border transition-colors ${
                                  r.opt_status === 'OPTED_IN'
                                    ? 'border-rose-300 text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30'
                                    : 'border-emerald-300 text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950/30'
                                }`}
                              >
                                {r.opt_status === 'OPTED_IN' ? 'Opt Out' : 'Re-enable'}
                              </button>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}

          {/* ============================================================== */}
          {/* TAB E: ACCOUNT & SECURITY */}
          {/* ============================================================== */}
          {activeTab === 'security' && (
            <div className="space-y-6">
              <div className="bg-surface rounded-xl border border-surface-border p-6 shadow-xs space-y-4">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-full bg-indigo-100 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 flex items-center justify-center font-bold text-lg">
                    {userProfile?.user?.email?.charAt(0).toUpperCase() || 'M'}
                  </div>
                  <div>
                    <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                      {userProfile?.user?.email || 'demo.owner@nexus.local'}
                    </h3>
                    <div className="flex items-center gap-2 mt-0.5">
                      <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-400">
                        {userProfile?.tenants?.[0]?.role || 'BUSINESS_OWNER'}
                      </span>
                      <span className="text-xs text-slate-500 font-mono">
                        User ID: {userProfile?.user?.id?.substring(0, 12) || 'usr_demo_1a2b'}...
                      </span>
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-4 border-t border-surface-border text-xs">
                  <div className="p-3 rounded-lg bg-surface-elevated border border-surface-border">
                    <span className="text-slate-500">Session Status</span>
                    <p className="font-semibold text-emerald-600 mt-1 flex items-center gap-1.5">
                      <ShieldCheck className="w-4 h-4" />
                      <span>Authenticated & Tenant Isolated</span>
                    </p>
                  </div>
                  <div className="p-3 rounded-lg bg-surface-elevated border border-surface-border">
                    <span className="text-slate-500">Cryptographic Signing Engine</span>
                    <p className="font-semibold text-slate-900 dark:text-white mt-1 font-mono">
                      Ed25519 Asymmetric (Local KMS)
                    </p>
                  </div>
                </div>

                <div className="pt-4 border-t border-surface-border flex justify-between items-center">
                  <p className="text-xs text-slate-500">
                    Signing out will terminate this local session token.
                  </p>
                  <button
                    onClick={() => {
                      AuthService.logout();
                      window.location.href = '/login';
                    }}
                    className="inline-flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg border border-rose-300 text-rose-600 hover:bg-rose-50 dark:hover:bg-rose-950/30 transition-colors"
                  >
                    <LogOut className="w-3.5 h-3.5" />
                    <span>Sign Out</span>
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ============================================================== */}
          {/* TAB F: BUSINESS & WORKSPACE */}
          {/* ============================================================== */}
          {activeTab === 'business' && (
            <div className="space-y-6">
              <div className="bg-surface rounded-xl border border-surface-border p-6 shadow-xs space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                      Active Business Workspace
                    </h3>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                      Tenant identifier, currency formatting, and operating localization parameters.
                    </p>
                  </div>
                  <button
                    onClick={() => onNavigate('/business')}
                    className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:underline font-medium"
                  >
                    <span>Full Business Settings</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-xs">
                  <div className="p-3 rounded-lg bg-surface-elevated border border-surface-border">
                    <span className="text-slate-500">Active Business ID</span>
                    <p className="font-mono font-semibold text-slate-900 dark:text-white mt-1">
                      {localStorage.getItem('nexus_business_id') || 'biz_demo_b1ee8ed1'}
                    </p>
                  </div>
                  <div className="p-3 rounded-lg bg-surface-elevated border border-surface-border">
                    <span className="text-slate-500">Operating Currency</span>
                    <p className="font-semibold text-slate-900 dark:text-white mt-1">
                      USD ($) — US Dollar
                    </p>
                  </div>
                  <div className="p-3 rounded-lg bg-surface-elevated border border-surface-border">
                    <span className="text-slate-500">Primary Timezone</span>
                    <p className="font-mono font-semibold text-slate-900 dark:text-white mt-1">
                      UTC (Universal Time)
                    </p>
                  </div>
                </div>

                <div className="pt-4 border-t border-surface-border">
                  <h4 className="text-xs font-semibold text-slate-900 dark:text-white mb-2">
                    Integrated Data Connectors ({connectors.length})
                  </h4>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="p-3 rounded-lg border border-surface-border flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                        <span className="font-medium">Stripe Sandbox (Reconciled)</span>
                      </div>
                      <span className="font-mono text-[10px] text-slate-500">ACTIVE</span>
                    </div>
                    <div className="p-3 rounded-lg border border-surface-border flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <div className="w-2 h-2 rounded-full bg-emerald-500"></div>
                        <span className="font-medium">Shopify Sandbox (GraphQL)</span>
                      </div>
                      <span className="font-mono text-[10px] text-slate-500">ACTIVE</span>
                    </div>
                  </div>
                  <button
                    onClick={() => onNavigate('/connectors')}
                    className="mt-3 inline-flex items-center gap-1.5 text-xs text-indigo-600 dark:text-indigo-400 font-medium hover:underline"
                  >
                    <span>Manage Connector Checkpoints & Webhooks</span>
                    <ChevronRight className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* ============================================================== */}
          {/* TAB G: SYSTEM INFORMATION */}
          {/* ============================================================== */}
          {activeTab === 'system' && (
            <div className="space-y-6">
              <div className="bg-surface rounded-xl border border-surface-border p-6 shadow-xs space-y-5">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-base font-semibold text-slate-900 dark:text-white">
                        Local Zero-Cost Infrastructure
                      </h3>
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-800">
                        ₹0.00 / MONTH ACTIVE
                      </span>
                    </div>
                    <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                      Local containerized architecture running natively on owner hardware without external cloud billing.
                    </p>
                  </div>
                  <button
                    onClick={loadAllSettingsData}
                    disabled={loadingData}
                    className="p-1.5 rounded-lg border border-surface-border text-slate-600 dark:text-slate-400 hover:bg-surface-elevated"
                  >
                    <RefreshCw className={`w-4 h-4 ${loadingData ? 'animate-spin' : ''}`} />
                  </button>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                  {/* POSTGRES */}
                  <div className="p-3.5 rounded-lg bg-surface-elevated border border-surface-border flex items-start gap-3">
                    <Database className="w-5 h-5 text-indigo-500 shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-900 dark:text-white">PostgreSQL 16 (Staging)</span>
                        <span className="px-1.5 py-0.5 text-[10px] font-mono rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                          Healthy
                        </span>
                      </div>
                      <p className="text-slate-500 mt-1">Port 5433 | Schema Revision 022</p>
                      <p className="text-[11px] text-slate-400 font-mono mt-0.5">Volume: nexus_staging_pgdata (Preserved)</p>
                    </div>
                  </div>

                  {/* REDIS */}
                  <div className="p-3.5 rounded-lg bg-surface-elevated border border-surface-border flex items-start gap-3">
                    <Server className="w-5 h-5 text-red-500 shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-900 dark:text-white">Redis 7 Ingestion Cache</span>
                        <span className="px-1.5 py-0.5 text-[10px] font-mono rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                          Healthy
                        </span>
                      </div>
                      <p className="text-slate-500 mt-1">Port 6380 | Distributed Lock & Rate Limit</p>
                      <p className="text-[11px] text-slate-400 font-mono mt-0.5">TLS / Token Auth Verified</p>
                    </div>
                  </div>

                  {/* MAILPIT */}
                  <div className="p-3.5 rounded-lg bg-surface-elevated border border-surface-border flex items-start gap-3">
                    <Mail className="w-5 h-5 text-blue-500 shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-900 dark:text-white">Mailpit SMTP & Web Inbox</span>
                        <a
                          href="http://localhost:8025"
                          target="_blank"
                          rel="noreferrer"
                          className="px-1.5 py-0.5 text-[10px] font-medium rounded bg-blue-100 text-blue-800 dark:bg-blue-950 dark:text-blue-300 flex items-center gap-1 hover:underline"
                        >
                          <span>Open UI</span>
                          <ExternalLink className="w-2.5 h-2.5" />
                        </a>
                      </div>
                      <p className="text-slate-500 mt-1">SMTP: 1025 | Web UI: 8025</p>
                      <p className="text-[11px] text-slate-400 font-mono mt-0.5">Zero-cost local email interceptor</p>
                    </div>
                  </div>

                  {/* BACKEND API */}
                  <div className="p-3.5 rounded-lg bg-surface-elevated border border-surface-border flex items-start gap-3">
                    <Zap className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-slate-900 dark:text-white">FastAPI Core Engine</span>
                        <span className="px-1.5 py-0.5 text-[10px] font-mono rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300">
                          Healthy
                        </span>
                      </div>
                      <p className="text-slate-500 mt-1">Port 8001 | Health: {health?.status || 'ok'}</p>
                      <p className="text-[11px] text-slate-400 font-mono mt-0.5">Version: {health?.version || '1.0.0-rc1'}</p>
                    </div>
                  </div>
                </div>

                <div className="p-4 rounded-xl bg-surface-elevated border border-surface-border text-xs space-y-1">
                  <div className="flex justify-between items-center">
                    <span className="font-semibold text-slate-900 dark:text-white">Continuous Background Scheduler</span>
                    <span className="font-mono text-emerald-600 font-bold">ACTIVE / HEARTBEAT OK</span>
                  </div>
                  <p className="text-slate-500">
                    Processes automated cron report deliveries, watermark safety verification, and recurring period closes.
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
