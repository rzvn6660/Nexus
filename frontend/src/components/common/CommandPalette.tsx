import React, { useState, useEffect } from 'react';
import {
  Search,
  LayoutDashboard,
  BarChart3,
  SearchCode,
  TrendingUp,
  MessageSquare,
  Database,
  BookOpen,
  ArrowRight,
  X,
} from 'lucide-react';

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (route: string) => void;
  onAskQuery?: (query: string) => void;
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  onNavigate,
  onAskQuery,
}) => {
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
        e.preventDefault();
        if (isOpen) {
          onClose();
        } else {
          // Open triggered by parent or caller
        }
      } else if (e.key === 'Escape' && isOpen) {
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const pages = [
    { title: 'Overview Dashboard', route: '/', icon: LayoutDashboard, category: 'Navigation' },
    { title: 'Deterministic Analytics', route: '/analytics', icon: BarChart3, category: 'Navigation' },
    { title: 'Diagnostic Investigations', route: '/investigations', icon: SearchCode, category: 'Navigation' },
    { title: 'Predictive Forecasting', route: '/forecasts', icon: TrendingUp, category: 'Navigation' },
    { title: 'Ask NEXUS Intelligence', route: '/ask', icon: MessageSquare, category: 'Navigation' },
    { title: 'Data Health & Tables', route: '/data', icon: Database, category: 'Navigation' },
    { title: 'Business Knowledge & KPIs', route: '/knowledge', icon: BookOpen, category: 'Navigation' },
  ];

  const suggestedQuestions = [
    'How did revenue perform this month?',
    'Why did revenue decline in August?',
    'Which product categories are driving gross margin?',
    'Forecast revenue for the next 3 months',
    'What is our current inventory turnover ratio?',
    'Show repeat purchase rate trends',
  ];

  const filteredPages = pages.filter((p) =>
    p.title.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const filteredQuestions = suggestedQuestions.filter((q) =>
    q.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 px-4 bg-slate-950/80 backdrop-blur-sm animate-in fade-in duration-100">
      <div className="relative w-full max-w-xl rounded-2xl bg-slate-900 border border-slate-700 shadow-2xl overflow-hidden">
        {/* Search Input */}
        <div className="flex items-center px-4 border-b border-slate-800">
          <Search className="w-5 h-5 text-slate-400 mr-3" />
          <input
            autoFocus
            type="text"
            placeholder="Type a command or business question..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-transparent py-4 text-sm text-slate-100 placeholder-slate-500 focus:outline-none"
          />
          <button
            onClick={onClose}
            className="p-1 rounded text-slate-400 hover:text-slate-200"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Results List */}
        <div className="max-h-80 overflow-y-auto p-2 space-y-4">
          {/* Navigation Section */}
          {filteredPages.length > 0 && (
            <div>
              <div className="px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider text-slate-400">
                Navigation
              </div>
              <div className="space-y-1">
                {filteredPages.map((page) => {
                  const Icon = page.icon;
                  return (
                    <button
                      key={page.route}
                      onClick={() => {
                        onNavigate(page.route);
                        onClose();
                      }}
                      className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs text-slate-200 hover:bg-slate-800 hover:text-cyan-300 transition-all text-left"
                    >
                      <div className="flex items-center gap-2.5">
                        <Icon className="w-4 h-4 text-cyan-400" />
                        <span>{page.title}</span>
                      </div>
                      <ArrowRight className="w-3.5 h-3.5 text-slate-400" />
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Quick Business Questions Section */}
          {filteredQuestions.length > 0 && (
            <div>
              <div className="px-3 py-1.5 text-[11px] font-mono uppercase tracking-wider text-slate-400">
                Ask NEXUS Intelligence
              </div>
              <div className="space-y-1">
                {filteredQuestions.map((q) => (
                  <button
                    key={q}
                    onClick={() => {
                      if (onAskQuery) {
                        onAskQuery(q);
                      } else {
                        onNavigate('/ask');
                      }
                      onClose();
                    }}
                    className="w-full flex items-center justify-between px-3 py-2 rounded-xl text-xs text-slate-300 hover:bg-slate-800 hover:text-cyan-300 transition-all text-left"
                  >
                    <div className="flex items-center gap-2.5">
                      <MessageSquare className="w-3.5 h-3.5 text-slate-400" />
                      <span>{q}</span>
                    </div>
                    <span className="text-[10px] font-mono text-cyan-400 bg-cyan-950/80 px-2 py-0.5 rounded border border-cyan-800/80">
                      Ask
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {filteredPages.length === 0 && filteredQuestions.length === 0 && (
            <div className="p-6 text-center text-xs text-slate-400">
              No matching pages or suggested questions found for "{searchTerm}".
            </div>
          )}
        </div>

        {/* Footer shortcuts */}
        <div className="border-t border-slate-800/80 bg-slate-950 px-4 py-2 flex items-center justify-between text-[11px] text-slate-400 font-mono">
          <span>Tip: Press ESC to exit</span>
          <span>NEXUS Command Center</span>
        </div>
      </div>
    </div>
  );
};
