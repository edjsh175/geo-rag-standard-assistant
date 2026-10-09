import React, { useEffect, useId, useState } from 'react';
import {
  Compass,
  FileCheck,
  Sparkles,
  ShieldCheck,
  Send,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import { ToolRow } from './ToolRow';
import { DisclosureRow } from './DisclosureRow';
import { AgentProcessItem, AgentTurnViewModel } from './types';

export interface AgentProcessProps {
  turn: AgentTurnViewModel;
  className?: string;
  defaultExpanded?: boolean;
  onExpandedChange?: (expanded: boolean) => void;
}

export const AgentProcess: React.FC<AgentProcessProps> = ({
  turn,
  className = '',
  defaultExpanded,
  onExpandedChange,
}) => {
  const [manualExpanded, setManualExpanded] = useState<boolean | undefined>(defaultExpanded);
  useEffect(() => {
    if (defaultExpanded !== undefined) {
      setManualExpanded(defaultExpanded);
    }
  }, [defaultExpanded]);
  const isExpanded = manualExpanded ?? (turn.status === 'running' || turn.status === 'failed' || turn.status === 'cancelled' || Boolean(turn.interruption));
  const contentId = useId();

  if (turn.items.length === 0) {
    return null;
  }

  const toolCount = turn.items.filter((item) => item.kind === 'tool').length;
  const reviews = turn.items.filter((item) => item.kind === 'review');
  const reviewItem = reviews[reviews.length - 1];

  const renderItem = (item: AgentProcessItem, idx: number) => {
    switch (item.kind) {
      case 'tool':
        return <ToolRow key={`tool-${item.callId || idx}`} tool={item} paused={Boolean(turn.interruption)} />;

      case 'decision':
        return (
          <DisclosureRow
            key={`decision-${idx}`}
            icon={<Compass className="w-3.5 h-3.5 text-amber-500" />}
            title="Controller 决策"
            summary={item.summary}
            status="info"
          />
        );

      case 'evidence_frozen':
        return (
          <DisclosureRow
            key={`evidence-${idx}`}
            icon={<FileCheck className="w-3.5 h-3.5 text-blue-500" />}
            title="证据冻结"
            summary={`锁定 ${item.evidenceCount} 条证据快照进行生成`}
            status="succeeded"
          >
            <div className="text-[11px] text-on-background/70 font-sans">
              <span className="font-mono text-on-background/50">Snapshot ID: {item.snapshotId}</span>
              <div className="mt-1.5 flex flex-wrap gap-1 font-mono">
                {item.evidenceIds.map((id) => (
                  <span
                    key={id}
                    className="px-2 py-0.5 rounded-md bg-blue-500/10 border border-blue-500/25 text-blue-600 dark:text-blue-300 text-[10px] font-medium"
                  >
                    {id}
                  </span>
                ))}
              </div>
            </div>
          </DisclosureRow>
        );

      case 'stage':
        return (
          <DisclosureRow
            key={`stage-${idx}`}
            icon={<Sparkles className="w-3.5 h-3.5 text-purple-500" />}
            title={item.stageName === 'cancellation' ? '执行停止' : '生成规划回答'}
            summary={item.summary}
            status={item.status === 'failed' ? 'failed' : item.status === 'running' ? 'running' : 'succeeded'}
          />
        );

      case 'review':
        const reviewStatus = item.status === 'running'
          ? 'running'
          : ['PASS', 'PASSED', 'SUPPORTED'].includes(item.verdict || '')
            ? 'succeeded'
            : item.verdict === 'REVISE'
              ? 'info'
              : 'failed';
        return (
          <DisclosureRow
            key={`review-${idx}`}
            icon={<ShieldCheck className="w-3.5 h-3.5 text-teal-500" />}
            title="Grounding 审查"
            summary={item.summary}
            status={reviewStatus}
            badge={<span className="text-[10px] font-mono text-on-background/50">{item.verdict || item.status || 'unknown'}</span>}
          />
        );

      case 'publication':
        return (
          <DisclosureRow
            key={`pub-${idx}`}
            icon={<Send className="w-3.5 h-3.5 text-emerald-500" />}
            title="结果发布"
            summary={item.summary}
            status={item.state === 'published' ? 'succeeded' : 'info'}
          />
        );
    }
  };

  return (
    <div
      className={`my-2.5 rounded-xl border border-outline bg-surface-container-low/75 backdrop-blur-md overflow-hidden text-xs shadow-xs transition-all duration-200 ${className}`}
    >
      <button
        type="button"
        onClick={() => {
          const next = !(manualExpanded ?? isExpanded);
          setManualExpanded(next);
          onExpandedChange?.(next);
        }}
        aria-expanded={isExpanded}
        aria-controls={contentId}
        className="w-full flex items-center justify-between gap-2.5 px-3.5 py-2.5 bg-surface-container/35 hover:bg-surface-container/65 transition-colors cursor-pointer select-none text-left min-w-0"
      >
        <div className="flex items-center gap-2 min-w-0 flex-1 mr-2">
          <span className={`w-2 h-2 rounded-full bg-primary-container shrink-0 ${turn.status === 'running' && !turn.interruption ? 'animate-pulse motion-reduce:animate-none' : ''}`} style={turn.status === 'running' && !turn.interruption ? { boxShadow: '0 0 8px rgba(240,112,64,0.6)' } : {}} />
          <span className="font-semibold text-on-background text-xs tracking-wide shrink-0">
            Agent 执行流程
          </span>
          <span className="text-[11px] text-on-background/55 truncate min-w-0">
            · {turn.items.length} 步骤
            {toolCount > 0 && ` (${toolCount} 个工具)`}
            {reviewItem && ` · 审查: ${reviewItem.verdict || reviewItem.status || 'unknown'}`}
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-on-background/50 shrink-0 ml-auto">
          <span className="text-[10.5px] font-mono uppercase tracking-wider whitespace-nowrap">
            {turn.status}
          </span>
          {isExpanded ? (
            <ChevronUp className="w-3.5 h-3.5 shrink-0" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5 shrink-0" />
          )}
        </div>
      </button>

      {isExpanded && (
        <div id={contentId} className="p-2.5 space-y-1.5 border-t border-outline/50 bg-surface-lowest/40 backdrop-blur-sm">
          {turn.interruption && <div role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-amber-700 dark:text-amber-300 text-[11.5px] leading-relaxed">{turn.interruption.kind === 'stopped' ? '生成已停止' : '连接中断'}：{turn.interruption.message}</div>}
          {turn.items.map((item, idx) => renderItem(item, idx))}
        </div>
      )}
    </div>
  );
};
