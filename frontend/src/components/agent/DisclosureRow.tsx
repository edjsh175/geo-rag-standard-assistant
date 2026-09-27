import React, { useId, useState } from 'react';
import { ChevronRight } from 'lucide-react';

import { cn } from '../../lib/utils';

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
  const contentId = useId();
  const hasContent = Boolean(children);

  const getStatusColor = () => {
    switch (status) {
      case 'running':
        return 'text-amber-600 dark:text-amber-400 border-amber-500/35 bg-amber-500/10';
      case 'succeeded':
        return 'text-emerald-600 dark:text-emerald-400 border-emerald-500/35 bg-emerald-500/10';
      case 'failed':
        return 'text-rose-600 dark:text-rose-400 border-rose-500/35 bg-rose-500/10';
      case 'waiting':
        return 'text-sky-600 dark:text-sky-400 border-sky-500/35 bg-sky-500/10';
      default:
        return 'text-on-background/60 border-outline bg-surface-container/40';
    }
  };

  return (
    <div className="w-full rounded-lg border border-outline/50 bg-surface-container/30 text-xs transition-all overflow-hidden">
      <button
        type="button"
        disabled={!hasContent}
        aria-expanded={hasContent ? isExpanded : undefined}
        aria-controls={hasContent ? contentId : undefined}
        onClick={() => setIsExpanded((prev) => !prev)}
        className={cn(
          "w-full flex items-center gap-2 px-3 py-2 text-left select-none transition-colors",
          hasContent ? "hover:bg-surface-container-high/40 cursor-pointer" : "cursor-default"
        )}
      >
        {hasContent && (
          <span
            className={cn(
              "transition-transform duration-150 motion-reduce:transition-none text-on-background/40",
              isExpanded && "rotate-90"
            )}
          >
            <ChevronRight className="w-3.5 h-3.5" />
          </span>
        )}

        {icon && <span className="shrink-0">{icon}</span>}

        <span className="font-medium text-on-background/90 shrink-0">{title}</span>

        {summary && (
          <span className="truncate text-on-background/50 font-normal ml-1 flex-1">
            {summary}
          </span>
        )}

        {badge && <span className="ml-auto shrink-0">{badge}</span>}

        {!badge && status && (
          <span
            className={cn(
              "ml-auto px-1.5 py-0.5 rounded text-[10px] font-mono border uppercase tracking-wider shrink-0",
              getStatusColor()
            )}
          >
            {status}
          </span>
        )}
      </button>

      {hasContent && isExpanded && (
        <div id={contentId} className="border-t border-outline/40 bg-surface-lowest/50 p-2.5 text-on-background/80 font-mono text-[11px] whitespace-pre-wrap break-all leading-relaxed">
          {children}
        </div>
      )}
    </div>
  );
};
