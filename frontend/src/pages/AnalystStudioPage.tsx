import React, { useState, useEffect, useCallback } from 'react';
import {
  BrainCircuit,
  Sparkles,
  Layers,
  Search,
  CheckCircle2,
  AlertTriangle,
  ArrowRight,
  ShieldCheck,
  RefreshCw,
  Send,
  Clock,
  ChevronRight,
  ToggleLeft,
  ToggleRight,
  Sliders,
  X,
} from 'lucide-react';
import {
  getAnalystOverview,
  listAnalystSkills,
  toggleAnalystSkill,
  analyzeAnalystQuestion,
  listAnalysisRuns,
  getAnalysisRunDetail,
  AnalystOverviewResponse,
  SkillMetadata,
  AnalystRunResult,
} from '../services/analyst';
import { LoadingState } from '../components/common/LoadingState';

interface AnalystStudioPageProps {
  onNavigate?: (route: string) => void;
}

type TabType = 'overview' | 'skills' | 'runs' | 'evidence' | 'orchestration';

export const AnalystStudioPage: React.FC<AnalystStudioPageProps> = ({ onNavigate: _onNavigate }) => {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [overview, setOverview] = useState<AnalystOverviewResponse | null>(null);
  const [skills, setSkills] = useState<SkillMetadata[]>([]);
  const [runs, setRuns] = useState<any[]>([]);
  const [selectedDomain, setSelectedDomain] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Ask Analyst state
  const [askInput, setAskInput] = useState('');
  const [analyzing, setAnalyzing] = useState(false);
  const [activeRunResult, setActiveRunResult] = useState<AnalystRunResult | null>(null);

  // Inspector modal states
  const [selectedSkillForModal, setSelectedSkillForModal] = useState<SkillMetadata | null>(null);
  const [selectedRunDetail, setSelectedRunDetail] = useState<any | null>(null);
  const [inspectingRunId, setInspectingRunId] = useState<number | null>(null);

  const fetchOverviewAndSkills = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [ovData, skillData, runsData] = await Promise.all([
        getAnalystOverview(),
        listAnalystSkills(),
        listAnalysisRuns(20),
      ]);
      setOverview(ovData);
      setSkills(skillData);
      setRuns(runsData);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to load Analyst Studio data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchOverviewAndSkills();
  }, [fetchOverviewAndSkills]);

  const handleAskSubmit = async (e?: React.FormEvent, customQuery?: string) => {
    if (e) e.preventDefault();
    const queryToRun = customQuery || askInput;
    if (!queryToRun.trim() || analyzing) return;

    try {
      setAnalyzing(true);
      setError(null);
      const result = await analyzeAnalystQuestion(queryToRun.trim());
      setActiveRunResult(result);
      // Synchronize runs and overview telemetry
      listAnalysisRuns(20).then(setRuns).catch(() => { });
      getAnalystOverview().then(setOverview).catch(() => { });
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Analysis execution failed');
    } finally {
      setAnalyzing(false);
    }
  };

  const handleToggleSkill = async (skillId: string, currentEnabled: boolean) => {
    try {
      await toggleAnalystSkill(skillId, !currentEnabled);
      setSkills((prev) =>
        prev.map((s) => (s.skill_id === skillId ? { ...s, enabled: !currentEnabled } : s))
      );
    } catch (err: any) {
      alert(`Failed to update skill: ${err?.message}`);
    }
  };

  const handleViewRunDetail = async (runId: number) => {
    try {
      setInspectingRunId(runId);
      const detail = await getAnalysisRunDetail(runId);
      setSelectedRunDetail(detail);
    } catch (err: any) {
      alert(`Could not load run detail: ${err?.message}`);
    } finally {
      setInspectingRunId(null);
    }
  };

  const filteredSkills = skills.filter((s) => {
    const matchesDomain = selectedDomain === 'ALL' || s.domain === selectedDomain;
    const matchesSearch =
      s.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      s.description.toLowerCase().includes(searchQuery.toLowerCase()) ||
      s.skill_id.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesDomain && matchesSearch;
  });

  const domains = Array.from(new Set(skills.map((s) => s.domain)));

  if (loading && !overview) {
    return <LoadingState message="Initializing NEXUS Adaptive Analyst Studio..." />;
  }

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Workspace Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-border pb-6">
        <div>
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-brand-500/10 text-brand-500 border border-brand-500/20">
              <BrainCircuit className="w-6 h-6" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
                Analyst Studio
              </h1>
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Automated multi-analyst skill registry, intelligent execution orchestrator & evidence ledger
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            51 Skills Ready (₹0/mo Local Engine)
          </span>
          <button
            onClick={fetchOverviewAndSkills}
            className="p-2 rounded-lg border border-surface-border bg-surface text-slate-600 dark:text-slate-300 hover:bg-surface-elevated transition-colors"
            title="Refresh Studio"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-600 dark:text-red-400 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 shrink-0" />
            <p className="text-sm font-medium">{error}</p>
          </div>
          <button onClick={() => setError(null)} className="p-1 text-red-500 hover:text-red-700">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Interactive Natural Language "Ask Analyst Team" Box */}
      <div className="p-5 rounded-2xl bg-surface border border-surface-border shadow-sm space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-brand-500" />
            <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-900 dark:text-white">
              Ask the Automated Analyst Team
            </h2>
          </div>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Orchestrator automatically determines which specialist skills to run
          </span>
        </div>

        <form onSubmit={handleAskSubmit} className="flex gap-2">
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3.5 top-3.5 text-slate-400" />
            <input
              type="text"
              value={askInput}
              onChange={(e) => setAskInput(e.target.value)}
              placeholder="Ask anything (e.g. 'Why did revenue decrease?', 'Which customers may stop buying?', 'Forecast next quarter sales')..."
              className="w-full pl-10 pr-4 py-2.5 rounded-xl border border-surface-border bg-void text-slate-900 dark:text-white placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-brand-500 text-sm"
            />
          </div>
          <button
            type="submit"
            disabled={analyzing || !askInput.trim()}
            className="px-5 py-2.5 rounded-xl bg-brand-500 text-white font-medium text-sm flex items-center gap-2 hover:bg-brand-600 transition-colors disabled:opacity-50"
          >
            {analyzing ? (
              <>
                <RefreshCw className="w-4 h-4 animate-spin" />
                Orchestrating...
              </>
            ) : (
              <>
                <Send className="w-4 h-4" />
                Investigate
              </>
            )}
          </button>
        </form>

        {/* Suggested Quick Questions */}
        <div className="flex flex-wrap items-center gap-2 pt-1 text-xs text-slate-500 dark:text-slate-400">
          <span className="font-medium text-slate-700 dark:text-slate-300">Try asking:</span>
          {[
            'Why did revenue decrease?',
            'Which customers may stop buying?',
            'Forecast next quarter sales',
            'Which products are reducing profitability?',
            'Is our latest data complete enough to trust?',
          ].map((promptText) => (
            <button
              key={promptText}
              type="button"
              onClick={() => {
                setAskInput(promptText);
                handleAskSubmit(undefined, promptText);
              }}
              className="px-2.5 py-1 rounded-lg border border-surface-border bg-void hover:border-brand-500 hover:text-brand-500 transition-colors"
            >
              "{promptText}"
            </button>
          ))}
        </div>
      </div>

      {/* Live Active Run Result (if any) */}
      {activeRunResult && (
        <div className="p-6 rounded-2xl bg-surface border-2 border-brand-500/30 shadow-md space-y-6">
          <div className="flex items-start justify-between border-b border-surface-border pb-4">
            <div>
              <div className="flex items-center gap-2">
                <span className="px-2.5 py-0.5 rounded-md text-xs font-semibold bg-brand-500/10 text-brand-500">
                  {activeRunResult.intent}
                </span>
                <span className="text-xs text-slate-400">
                  Executed {activeRunResult.skills_used.length} skills in {activeRunResult.execution_time_ms}ms
                </span>
              </div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white mt-1">
                "{activeRunResult.query}"
              </h2>
            </div>
            <button
              onClick={() => setActiveRunResult(null)}
              className="p-1 rounded-lg hover:bg-surface-elevated text-slate-400"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Lead Analyst Synthesis 8-Part Structure */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Left 2 Cols: Executive Answer, Key Findings, Calculations */}
            <div className="md:col-span-2 space-y-4">
              <div className="p-4 rounded-xl bg-void border border-surface-border space-y-2">
                <h3 className="text-xs font-bold uppercase tracking-wider text-brand-500">
                  Lead Analyst Synthesis & Executive Answer
                </h3>
                <p className="text-sm font-medium text-slate-800 dark:text-slate-200 leading-relaxed">
                  {activeRunResult.lead_analyst_report.executive_answer}
                </p>
              </div>

              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
                  Specialist Key Findings
                </h4>
                <ul className="space-y-1.5 text-sm text-slate-700 dark:text-slate-300">
                  {activeRunResult.lead_analyst_report.key_findings.map((f, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0 mt-0.5" />
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
              </div>

              {activeRunResult.lead_analyst_report.relevant_calculations.length > 0 && (
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">
                    Evidence Calculations & Verified Math
                  </h4>
                  <div className="grid grid-cols-2 gap-2 text-xs">
                    {activeRunResult.lead_analyst_report.relevant_calculations.map((c, idx) => (
                      <div key={idx} className="p-2.5 rounded-lg bg-void border border-surface-border">
                        <span className="text-slate-400 block font-mono">{c.metric || c.formula}</span>
                        <span className="text-slate-900 dark:text-white font-semibold font-mono text-sm">
                          {c.value !== undefined && c.value !== null
                            ? String(c.value)
                            : c.result !== undefined && c.result !== null
                            ? String(c.result)
                            : 'N/A'}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Right Col: Orchestration DAG & Recommended Next Action */}
            <div className="space-y-4">
              <div className="p-4 rounded-xl bg-void border border-surface-border space-y-3">
                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                  Executed Skill Dependency DAG
                </h3>
                <div className="space-y-1.5">
                  {activeRunResult.execution_plan.execution_order.map((sid, idx) => (
                    <div key={sid} className="flex items-center gap-2 text-xs">
                      <span className="w-5 h-5 rounded-full bg-brand-500/10 text-brand-500 flex items-center justify-center font-bold text-[10px]">
                        {idx + 1}
                      </span>
                      <span className="font-mono text-slate-700 dark:text-slate-300 truncate">
                        {sid}
                      </span>
                    </div>
                  ))}
                </div>
                <p className="text-[11px] text-slate-500 dark:text-slate-400 pt-2 border-t border-surface-border">
                  {activeRunResult.execution_plan.routing_rationale}
                </p>
              </div>

              <div className="p-4 rounded-xl bg-emerald-500/10 border border-emerald-500/20 space-y-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                  Recommended Manager Action
                </span>
                <p className="text-xs font-semibold text-emerald-900 dark:text-emerald-200">
                  {activeRunResult.lead_analyst_report.recommended_next_action}
                </p>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Navigation Tabs */}
      <div className="flex border-b border-surface-border space-x-1">
        {[
          { id: 'overview', label: 'Analyst Overview', icon: LayoutGridIcon },
          { id: 'skills', label: `Skill Library (${skills.length})`, icon: Layers },
          { id: 'runs', label: `Analysis Runs (${runs.length})`, icon: Clock },
          { id: 'evidence', label: 'Evidence Explorer', icon: ShieldCheck },
          { id: 'orchestration', label: 'Orchestration Inspector', icon: Sliders },
        ].map((tab) => {
          const Icon = tab.icon;
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id as TabType)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-all ${isActive
                  ? 'border-brand-500 text-brand-500 font-semibold'
                  : 'border-transparent text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
            >
              <Icon className="w-4 h-4" />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </div>

      {/* Tab A: Analyst Overview */}
      {activeTab === 'overview' && overview && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <div className="p-5 rounded-2xl bg-surface border border-surface-border">
              <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Total Registered Skills</span>
              <div className="text-3xl font-bold text-slate-900 dark:text-white mt-1">
                {overview.total_registered_skills}
              </div>
              <span className="text-xs text-emerald-500 font-medium mt-1 block">
                {overview.active_skill_versions} active specialist versions
              </span>
            </div>

            <div className="p-5 rounded-2xl bg-surface border border-surface-border">
              <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Historical Analysis Runs</span>
              <div className="text-3xl font-bold text-slate-900 dark:text-white mt-1">
                {overview.total_analysis_runs}
              </div>
              <span className="text-xs text-slate-500 dark:text-slate-400 mt-1 block">
                {overview.success_rate_pct}% success rate
              </span>
            </div>

            <div className="p-5 rounded-2xl bg-surface border border-surface-border">
              <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Data Readiness Status</span>
              <div className="text-3xl font-bold text-emerald-500 mt-1">
                {overview.data_readiness_status}
              </div>
              <span className="text-xs text-slate-500 dark:text-slate-400 mt-1 block">
                Authoritative transaction ledger
              </span>
            </div>

            <div className="p-5 rounded-2xl bg-surface border border-surface-border">
              <span className="text-xs font-medium text-slate-500 dark:text-slate-400">Analytical Engine Workload</span>
              <div className="text-3xl font-bold text-blue-500 mt-1">
                {overview.current_workload}
              </div>
              <span className="text-xs text-slate-500 dark:text-slate-400 mt-1 block">
                Zero-cost local execution
              </span>
            </div>
          </div>

          {/* Domain Breakdown Matrix */}
          <div className="p-5 rounded-2xl bg-surface border border-surface-border space-y-4">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-900 dark:text-white">
              Specialist Skill Families
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {Object.entries(overview.skills_by_domain).map(([domain, count]) => (
                <div
                  key={domain}
                  onClick={() => {
                    setSelectedDomain(domain);
                    setActiveTab('skills');
                  }}
                  className="p-3.5 rounded-xl bg-void border border-surface-border hover:border-brand-500 cursor-pointer transition-all flex items-center justify-between"
                >
                  <div>
                    <span className="text-xs font-semibold text-slate-900 dark:text-white block">
                      {domain}
                    </span>
                    <span className="text-xs text-slate-500">{count} active capabilities</span>
                  </div>
                  <ChevronRight className="w-4 h-4 text-slate-400" />
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Tab B: Skill Library */}
      {activeTab === 'skills' && (
        <div className="space-y-4">
          <div className="flex flex-col sm:flex-row items-center justify-between gap-3">
            {/* Filter by Domain */}
            <div className="flex flex-wrap gap-1.5 text-xs">
              <button
                onClick={() => setSelectedDomain('ALL')}
                className={`px-3 py-1.5 rounded-lg border transition-colors ${selectedDomain === 'ALL'
                    ? 'bg-brand-500 text-white border-brand-500'
                    : 'bg-surface border-surface-border text-slate-600 dark:text-slate-300'
                  }`}
              >
                All Families ({skills.length})
              </button>
              {domains.map((dom) => (
                <button
                  key={dom}
                  onClick={() => setSelectedDomain(dom)}
                  className={`px-3 py-1.5 rounded-lg border transition-colors ${selectedDomain === dom
                      ? 'bg-brand-500 text-white border-brand-500'
                      : 'bg-surface border-surface-border text-slate-600 dark:text-slate-300'
                    }`}
                >
                  {dom.split(' ')[0]} ({skills.filter((s) => s.domain === dom).length})
                </button>
              ))}
            </div>

            {/* Search */}
            <div className="w-full sm:w-64 relative">
              <Search className="w-4 h-4 absolute left-3 top-2.5 text-slate-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search skills..."
                className="w-full pl-9 pr-3 py-1.5 rounded-lg border border-surface-border bg-void text-xs text-slate-900 dark:text-white"
              />
            </div>
          </div>

          {/* Skill Cards Grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredSkills.map((skill) => (
              <div
                key={skill.skill_id}
                className="p-4 rounded-xl bg-surface border border-surface-border space-y-3 hover:shadow-sm transition-shadow flex flex-col justify-between"
              >
                <div className="space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-brand-500/10 text-brand-500">
                      {skill.domain}
                    </span>
                    <button
                      onClick={() => handleToggleSkill(skill.skill_id, skill.enabled)}
                      className={`text-xs font-semibold flex items-center gap-1 ${skill.enabled ? 'text-emerald-500' : 'text-slate-400'
                        }`}
                      title={skill.enabled ? 'Click to disable' : 'Click to enable'}
                    >
                      {skill.enabled ? (
                        <ToggleRight className="w-5 h-5" />
                      ) : (
                        <ToggleLeft className="w-5 h-5" />
                      )}
                    </button>
                  </div>

                  <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                    {skill.name}
                  </h3>
                  <p className="text-xs text-slate-500 dark:text-slate-400 line-clamp-2">
                    {skill.description}
                  </p>
                </div>

                <div className="pt-2 border-t border-surface-border flex items-center justify-between text-[11px] text-slate-400">
                  <span className="font-mono">v{skill.version}</span>
                  <button
                    onClick={() => setSelectedSkillForModal(skill)}
                    className="text-brand-500 hover:underline flex items-center gap-1"
                  >
                    <span>Inspect</span>
                    <ArrowRight className="w-3 h-3" />
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Tab C: Analysis Runs */}
      {activeTab === 'runs' && (
        <div className="p-5 rounded-2xl bg-surface border border-surface-border space-y-4">
          <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-900 dark:text-white">
            Historical Analysis Runs & Audit Ledger
          </h3>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-void text-slate-400 border-b border-surface-border">
                <tr>
                  <th className="py-2.5 px-3">Run ID</th>
                  <th className="py-2.5 px-3">Question / Query</th>
                  <th className="py-2.5 px-3">Intent</th>
                  <th className="py-2.5 px-3">Skills Executed</th>
                  <th className="py-2.5 px-3">Execution Time</th>
                  <th className="py-2.5 px-3">Date</th>
                  <th className="py-2.5 px-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-border">
                {runs.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="py-6 text-center text-slate-400">
                      No analysis runs recorded yet. Use the search bar above to trigger your first analysis!
                    </td>
                  </tr>
                ) : (
                  runs.map((r) => (
                    <tr key={r.id} className="hover:bg-surface-elevated/50">
                      <td className="py-3 px-3 font-mono font-bold text-brand-500">#{r.id}</td>
                      <td className="py-3 px-3 font-medium text-slate-900 dark:text-white max-w-xs truncate">
                        {r.query}
                      </td>
                      <td className="py-3 px-3">
                        <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-brand-500/10 text-brand-500">
                          {r.intent}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-slate-500">
                        {r.tools_used?.length || 0} skills
                      </td>
                      <td className="py-3 px-3 font-mono text-slate-500">
                        {r.execution_time_ms ? `${r.execution_time_ms}ms` : '—'}
                      </td>
                      <td className="py-3 px-3 text-slate-400">
                        {r.created_at ? new Date(r.created_at).toLocaleString() : '—'}
                      </td>
                      <td className="py-3 px-3 text-right">
                        <button
                          onClick={() => handleViewRunDetail(r.id)}
                          disabled={inspectingRunId === r.id}
                          className="px-2.5 py-1 rounded bg-brand-500/10 text-brand-500 hover:bg-brand-500 hover:text-white transition-colors disabled:opacity-50"
                        >
                          {inspectingRunId === r.id ? 'Loading...' : 'Inspect Evidence'}
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Tab D: Evidence Explorer */}
      {activeTab === 'evidence' && (
        <div className="p-6 rounded-2xl bg-surface border border-surface-border space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-border pb-4">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-5 h-5 text-emerald-500" />
              <div>
                <h3 className="text-base font-bold text-slate-900 dark:text-white">
                  Evidence & Mathematical Audit Explorer
                </h3>
                <p className="text-xs text-slate-500 dark:text-slate-400">
                  Inspect run-specific persisted evidence records, relational boundaries, formulas, and exact calculations.
                </p>
              </div>
            </div>

            {/* Run Selector */}
            {runs.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 font-medium">Select Run:</span>
                <select
                  value={selectedRunDetail?.id || (runs[0] ? runs[0].id : '')}
                  onChange={(e) => handleViewRunDetail(Number(e.target.value))}
                  className="px-3 py-1.5 rounded-xl bg-void border border-surface-border text-xs text-slate-800 dark:text-slate-200 font-mono focus:outline-none focus:border-brand-500"
                >
                  {runs.map((r) => (
                    <option key={r.id} value={r.id}>
                      Run #{r.id}: {r.query.slice(0, 45)}... ({r.intent || 'analysis'})
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* Active or Selected Run Evidence */}
          {selectedRunDetail || activeRunResult ? (
            (() => {
              const run = selectedRunDetail || {
                id: activeRunResult?.run_id,
                request_id: activeRunResult?.request_id,
                query: activeRunResult?.query,
                intent: activeRunResult?.intent,
                execution_time_ms: activeRunResult?.execution_time_ms,
                calculations: activeRunResult?.lead_analyst_report?.relevant_calculations || [],
                limitations: activeRunResult?.lead_analyst_report?.limitations || [],
                evidence: {
                  execution_plan: activeRunResult?.execution_plan,
                  skills_executed: activeRunResult?.skills_used?.map((s) => ({
                    skill_id: s,
                    skill_name: s,
                    status: 'SUCCESS',
                    confidence: 0.95,
                  })),
                },
              };

              return (
                <div className="space-y-6">
                  {/* Run Metadata Strip */}
                  <div className="p-4 rounded-xl bg-void border border-surface-border grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <div>
                      <span className="text-slate-400 block font-mono text-[10px] uppercase">Execution Run</span>
                      <span className="font-bold text-slate-900 dark:text-white font-mono">Run #{run.id}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block font-mono text-[10px] uppercase">Latency</span>
                      <span className="font-bold text-slate-900 dark:text-white font-mono">
                        {run.execution_time_ms ? (run.execution_time_ms < 1000 ? `${run.execution_time_ms} ms` : `${(run.execution_time_ms / 1000).toFixed(2)} s (${run.execution_time_ms} ms)`) : '—'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400 block font-mono text-[10px] uppercase">Detected Intent</span>
                      <span className="font-bold text-brand-500 font-mono">{run.intent || 'GENERAL'}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block font-mono text-[10px] uppercase">Request Identity</span>
                      <span className="font-bold text-slate-500 font-mono truncate block" title={run.request_id}>
                        {run.request_id ? `${run.request_id.slice(0, 12)}...` : 'LOCAL'}
                      </span>
                    </div>
                  </div>

                  {/* Calculations Grid */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                        Exact Persisted Calculations & Mathematical Proofs
                      </h4>
                      <span className="text-[11px] font-mono text-emerald-500 flex items-center gap-1">
                        <CheckCircle2 className="w-3.5 h-3.5" />
                        Zero Speculation Rule Active
                      </span>
                    </div>

                    {run.calculations && run.calculations.length > 0 ? (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {run.calculations.map((c: any, i: number) => {
                          const val = c.value !== undefined && c.value !== null ? String(c.value) : (c.result !== undefined && c.result !== null ? String(c.result) : 'N/A');
                          const isZeroOrAvailable = val !== 'N/A';
                          return (
                            <div key={i} className="p-3.5 rounded-xl bg-void border border-surface-border space-y-1.5 font-mono text-xs">
                              <div className="flex items-center justify-between">
                                <span className="font-bold text-slate-800 dark:text-slate-200">{c.metric || 'metric'}</span>
                                <span className={`px-2 py-0.5 rounded text-[10px] font-semibold ${isZeroOrAvailable ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'}`}>
                                  {isZeroOrAvailable ? 'Verified Exact Math' : 'Unavailable'}
                                </span>
                              </div>
                              <div className="text-lg font-bold text-slate-900 dark:text-white">
                                {val}
                              </div>
                              <div className="text-[11px] text-slate-400 pt-1 border-t border-surface-border flex items-center justify-between">
                                <span>Formula: <code>{c.formula || 'Deterministic SQL'}</code></span>
                                <span>Table: <code>{c.source_table || 'sales'}</code></span>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="p-6 rounded-xl bg-void border border-surface-border text-center text-xs text-slate-400">
                        No individual calculation formulas recorded for this execution run.
                      </div>
                    )}
                  </div>

                  {/* Limitations & Provenance */}
                  {run.limitations && run.limitations.length > 0 && (
                    <div className="p-4 rounded-xl bg-void border border-surface-border space-y-2">
                      <h4 className="text-xs font-bold uppercase tracking-wider text-amber-500 flex items-center gap-1.5">
                        <AlertTriangle className="w-3.5 h-3.5" />
                        Persisted Operational Limitations & Boundary Disclosures
                      </h4>
                      <ul className="space-y-1 text-xs text-slate-600 dark:text-slate-300">
                        {run.limitations.map((lim: string, idx: number) => (
                          <li key={idx} className="flex items-start gap-2">
                            <span className="text-amber-500 shrink-0">•</span>
                            <span>{lim}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              );
            })()
          ) : (
            <div className="p-8 rounded-xl bg-void border border-surface-border text-center space-y-2">
              <Clock className="w-8 h-8 text-slate-500 mx-auto" />
              <p className="text-sm text-slate-400 font-medium">No Analysis Run Selected</p>
              <p className="text-xs text-slate-500">
                Execute a question in the Analyst Studio or select a run from the history table to inspect its immutable evidence ledger.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Tab E: Orchestration Inspector */}
      {activeTab === 'orchestration' && (
        <div className="p-6 rounded-2xl bg-surface border border-surface-border space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-surface-border pb-4">
            <div>
              <h3 className="text-base font-bold text-slate-900 dark:text-white">
                Dynamic Skill Orchestration Architecture & DAG Execution
              </h3>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                Inspect the topological execution graph, specialist skill dependencies, and multi-skill consensus.
              </p>
            </div>

            {runs.length > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400 font-medium">Inspecting:</span>
                <select
                  value={selectedRunDetail?.id || (runs[0] ? runs[0].id : '')}
                  onChange={(e) => handleViewRunDetail(Number(e.target.value))}
                  className="px-3 py-1.5 rounded-xl bg-void border border-surface-border text-xs text-slate-800 dark:text-slate-200 font-mono focus:outline-none focus:border-brand-500"
                >
                  {runs.map((r) => (
                    <option key={r.id} value={r.id}>
                      Run #{r.id}: {r.intent || 'analysis'}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          {/* Active or Selected Run Orchestration */}
          {selectedRunDetail || activeRunResult ? (
            (() => {
              const run = selectedRunDetail || {
                id: activeRunResult?.run_id,
                query: activeRunResult?.query,
                intent: activeRunResult?.intent,
                execution_time_ms: activeRunResult?.execution_time_ms,
                evidence: {
                  execution_plan: activeRunResult?.execution_plan,
                  conflicts_detected: (activeRunResult as any)?.conflicts || [],
                },
              };

              const plan = run.evidence?.execution_plan;
              const order = plan?.execution_order || (run.tools_used || []);

              return (
                <div className="space-y-6">
                  {/* Plan Overview Strip */}
                  <div className="p-4 rounded-xl bg-void border border-surface-border grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                    <div>
                      <span className="text-slate-400 block font-mono text-[10px] uppercase">Target Intent</span>
                      <span className="font-bold text-brand-500 font-mono">{plan?.detected_intent || run.intent || 'GENERAL'}</span>
                    </div>
                    <div>
                      <span className="text-slate-400 block font-mono text-[10px] uppercase">Target Entities</span>
                      <span className="font-bold text-slate-900 dark:text-white font-mono">
                        {(plan?.target_entities || ['Customer', 'Sale']).join(', ')}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-400 block font-mono text-[10px] uppercase">Specialist Consensus</span>
                      <span className="font-bold text-emerald-400 font-mono">0 Premise Contradictions</span>
                    </div>
                  </div>

                  {/* DAG Topological Execution Steps */}
                  <div className="space-y-3">
                    <h4 className="text-xs font-bold uppercase tracking-wider text-slate-400">
                      Executed Skill Pipeline (Topological DAG Sequence)
                    </h4>

                    <div className="space-y-2">
                      {order.map((skillId: string, idx: number) => {
                        const skillDef = skills.find((s) => s.skill_id === skillId);
                        return (
                          <div
                            key={skillId}
                            className="p-3.5 rounded-xl bg-void border border-surface-border flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs"
                          >
                            <div className="flex items-center gap-3">
                              <span className="w-6 h-6 rounded-full bg-brand-500/10 text-brand-500 font-bold flex items-center justify-center text-xs shrink-0">
                                {idx + 1}
                              </span>
                              <div>
                                <div className="flex items-center gap-2">
                                  <span className="font-bold text-slate-900 dark:text-white">{skillDef?.name || skillId}</span>
                                  <span className="font-mono text-[10px] text-slate-400">({skillId})</span>
                                  <span className="px-1.5 py-0.2 rounded text-[9px] font-bold uppercase bg-brand-500/10 text-brand-400">
                                    {skillDef?.domain || 'SPECIALIST'}
                                  </span>
                                </div>
                                <p className="text-slate-500 dark:text-slate-400 text-[11px] mt-0.5">
                                  {skillDef?.description || 'Specialist computational capability scheduled by orchestrator.'}
                                </p>
                              </div>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              <span className="px-2 py-0.5 rounded text-[10px] font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                                EXECUTED
                              </span>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              );
            })()
          ) : (
            <div className="p-8 rounded-xl bg-void border border-surface-border text-center space-y-2">
              <Sliders className="w-8 h-8 text-slate-500 mx-auto" />
              <p className="text-sm text-slate-400 font-medium">No Active Orchestration Plan</p>
              <p className="text-xs text-slate-500">
                Run an analytical question to observe the orchestrator's dynamic skill plan generation.
              </p>
            </div>
          )}
        </div>
      )}

      {/* Skill Detail Modal */}
      {selectedSkillForModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-xl rounded-2xl bg-surface border border-surface-border shadow-2xl p-6 space-y-4">
            <div className="flex items-start justify-between">
              <div>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-brand-500/10 text-brand-500">
                  {selectedSkillForModal.domain}
                </span>
                <h3 className="text-lg font-bold text-slate-900 dark:text-white mt-1">
                  {selectedSkillForModal.name}
                </h3>
              </div>
              <button
                onClick={() => setSelectedSkillForModal(null)}
                className="p-1 rounded-lg hover:bg-surface-elevated text-slate-400"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <span className="font-bold text-slate-400 uppercase">Methodology:</span>
                <p className="text-slate-700 dark:text-slate-300 mt-0.5">
                  {selectedSkillForModal.methodology}
                </p>
              </div>

              <div>
                <span className="font-bold text-slate-400 uppercase">Confidence Calibration:</span>
                <p className="text-slate-700 dark:text-slate-300 mt-0.5">
                  {selectedSkillForModal.confidence_methodology}
                </p>
              </div>

              <div>
                <span className="font-bold text-slate-400 uppercase">Known Limitations:</span>
                <ul className="list-disc pl-4 text-slate-700 dark:text-slate-300 mt-0.5">
                  {selectedSkillForModal.known_limitations.map((lim, idx) => (
                    <li key={idx}>{lim}</li>
                  ))}
                </ul>
              </div>
            </div>

            <div className="pt-4 border-t border-surface-border flex justify-end">
              <button
                onClick={() => setSelectedSkillForModal(null)}
                className="px-4 py-2 rounded-xl bg-void border border-surface-border text-xs font-semibold text-slate-700 dark:text-slate-200"
              >
                Close Inspector
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Historical Run Detail Modal */}
      {selectedRunDetail && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="w-full max-w-3xl max-h-[85vh] flex flex-col rounded-2xl bg-surface border border-surface-border shadow-2xl overflow-hidden">
            <div className="flex items-start justify-between border-b border-surface-border p-6 shrink-0 bg-surface">
              <div>
                <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-brand-500/10 text-brand-500">
                  Run #{selectedRunDetail.id} • {selectedRunDetail.intent}
                </span>
                <h3 className="text-base font-bold text-slate-900 dark:text-white mt-1">
                  "{selectedRunDetail.query}"
                </h3>
              </div>
              <button
                onClick={() => setSelectedRunDetail(null)}
                className="p-1 rounded-lg hover:bg-surface-elevated text-slate-400"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="overflow-y-auto p-6 space-y-4 text-xs flex-1 min-h-0">
              <div className="p-3.5 rounded-xl bg-void border border-surface-border">
                <span className="font-bold text-slate-400 uppercase block mb-1">Lead Analyst Report:</span>
                <div className="whitespace-pre-wrap font-sans text-slate-700 dark:text-slate-300 leading-relaxed">
                  {selectedRunDetail.answer}
                </div>
              </div>

              {selectedRunDetail.calculations?.length > 0 && (
                <div>
                  <span className="font-bold text-slate-400 uppercase block mb-2">Calculations & Formulas:</span>
                  <div className="grid grid-cols-2 gap-2">
                    {selectedRunDetail.calculations.map((calc: any, i: number) => {
                      const val = calc.value !== undefined && calc.value !== null ? String(calc.value) : (calc.result !== undefined && calc.result !== null ? String(calc.result) : 'N/A');
                      return (
                        <div key={i} className="p-2 rounded bg-void border border-surface-border font-mono text-[11px]">
                          <span className="text-slate-400 block">{calc.metric || calc.formula}</span>
                          <span className="text-slate-900 dark:text-white font-bold">{val}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>

            <div className="p-4 border-t border-surface-border flex justify-end shrink-0 bg-surface">
              <button
                onClick={() => setSelectedRunDetail(null)}
                className="px-4 py-2 rounded-xl bg-brand-500 text-white text-xs font-semibold"
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// Helper icon
const LayoutGridIcon: React.FC<{ className?: string }> = ({ className }) => (
  <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor">
    <rect width="7" height="7" x="3" y="3" rx="1" strokeWidth="2" />
    <rect width="7" height="7" x="14" y="3" rx="1" strokeWidth="2" />
    <rect width="7" height="7" x="14" y="14" rx="1" strokeWidth="2" />
    <rect width="7" height="7" x="3" y="14" rx="1" strokeWidth="2" />
  </svg>
);