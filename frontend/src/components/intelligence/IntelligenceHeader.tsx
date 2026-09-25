import React from 'react';
import { Sparkles } from 'lucide-react';

interface IntelligenceHeaderProps {
  eyebrow?: string;
  title: string;
  subtitle: string;
  actions?: React.ReactNode;
  icon?: React.ElementType;
  className?: string;
}

export const IntelligenceHeader: React.FC<IntelligenceHeaderProps> = ({
  eyebrow = 'NEXUS INTELLIGENCE',
  title,
  subtitle,
  actions,
  icon: Icon = Sparkles,
  className = '',
}) => {
  return (
    <div
      className={`relative rounded-3xl p-6 sm:p-8 overflow-hidden bg-void-sub border border-surface-elevated shadow-xl ${className}`}
    >
      <div className="absolute top-0 right-0 -mr-20 -mt-20 w-72 h-72 rounded-full bg-cyan-500/5 blur-3xl pointer-events-none" />

      <div className="relative z-10 flex flex-col md:flex-row items-start md:items-center justify-between gap-5">
        <div className="space-y-1.5 max-w-3xl">
          {eyebrow && (
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/70 border border-cyan-800/60 text-brand-cyan text-xs font-mono font-medium">
              <Icon className="w-3.5 h-3.5 text-brand-cyan" />
              <span>{eyebrow}</span>
            </div>
          )}

          <h1 className="text-2xl sm:text-3xl font-bold text-white tracking-tight font-sans">
            {title}
          </h1>

          <p className="text-xs sm:text-sm text-slate-400 leading-relaxed font-sans">
            {subtitle}
          </p>
        </div>

        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>
    </div>
  );
};
