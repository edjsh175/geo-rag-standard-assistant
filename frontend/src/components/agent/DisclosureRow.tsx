import React, { useState } from 'react';
import { ChevronRight } from 'lucide-react';

export interface DisclosureRowProps {
  icon?: React.ReactNode;
  title: string;
  badge?: React.ReactNode;
  summary?: string;
  status?: 'running' | 'succeeded' | 'failed' | 'waiting' | 'info';
  children?: React.ReactNode;
  defaultExpanded?: boolean;
}

export const DisclosureRow: React.FC<DisclosureRowProps> = ({
  icon,
  title,
  badge,
  summary,
  status = 'info',
  children,
  defaultExpanded = false,
}) => {
  const [isExpanded, setIsExpanded] = useState(defaultExpanded);
  const hasContent = Boolean(children);

  const getStatusColor = () => {
    switch (status) {
      case 'running':
        return 'text-amber-500 border-amber-500/30 bg-amber-500/10';
      case 'succeeded':
        return 'text-emerald-500 border-emerald-500/30 bg-emerald-500/10';
      case 'failed':
        return 'text-rose-500 border-rose-500/30 bg-rose-500/10';
      case 'waiting':
        return 'text-sky-500 border-sky-500/30 bg-sky-500/10';
      default:
        return 'text-slate-400 border-slate-500/20 bg-slate-500/5';
    }
  };

  return (
    <div className="w-full rounded-lg border border-white/5 bg-white/[0.02] text-xs transition-colors overflow-hidden">
      <button
        type="button"
        disabled={!hasContent}
        onClick={() => setIsExpanded((prev) => !prev)}
        className={`w-full flex items-center gap-2 px-3 py-2 text-left select-none transition-colors ${
          hasContent ? 'hover:bg-white/[0.04] cursor-pointer' : 'cursor-default'
        }`}
      >
        {hasContent && (
          <span
            className={`transition-transform duration-150 text-slate-400 ${
              isExpanded ? 'rotate-90' : 'rotate-0'
            }`}
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </span>
        )}

        {icon && <span className="shrink-0">{icon}</span>}

        <span className="font-medium text-slate-200 shrink-0">{title}</span>

        {summary && (
          <span className="truncate text-slate-400 font-normal ml-1 flex-1">
            {summary}
          </span>
        )}

        {badge && <span className="ml-auto shrink-0">{badge}</span>}

        {!badge && status && (
          <span
            className={`ml-auto px-1.5 py-0.5 rounded text-[10px] font-mono border uppercase shrink-0 ${getStatusColor()}`}
          >
            {status}
          </span>
        )}
      </button>

      {hasContent && isExpanded && (
        <div className="border-t border-white/5 bg-black/20 p-2.5 text-slate-300 font-mono text-[11px] whitespace-pre-wrap break-all">
          {children}
        </div>
      )}
    </div>
  );
};
