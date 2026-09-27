import React, { useId, useState } from 'react';
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
            icon={<Compass className="w-3.5 h-3.5 text-amber-400" />}
            title="Controller 决策"
            summary={item.summary}
            status="info"
          />
        );

      case 'evidence_frozen':
        return (
          <DisclosureRow
            key={`evidence-${idx}`}
            icon={<FileCheck className="w-3.5 h-3.5 text-blue-400" />}
            title="证据冻结"
            summary={`锁定 ${item.evidenceCount} 条证据快照进行生成`}
            status="succeeded"
          >
            <div className="text-[11px] text-slate-300">
              Snapshot ID: {item.snapshotId}
              <div className="mt-1 flex flex-wrap gap-1">
                {item.evidenceIds.map((id) => (
                  <span
                    key={id}
                    className="px-1.5 py-0.5 rounded bg-blue-950/40 border border-blue-800/40 text-blue-300 text-[10px]"
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
            icon={<Sparkles className="w-3.5 h-3.5 text-purple-400" />}
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
            icon={<ShieldCheck className="w-3.5 h-3.5 text-teal-400" />}
            title="Grounding 审查"
            summary={item.summary}
            status={reviewStatus}
            badge={<span className="text-[10px] font-mono text-slate-400">{item.verdict || item.status || 'unknown'}</span>}
          />
        );

      case 'publication':
        return (
          <DisclosureRow
            key={`pub-${idx}`}
            icon={<Send className="w-3.5 h-3.5 text-emerald-400" />}
            title="结果发布"
            summary={item.summary}
            status={item.state === 'published' ? 'succeeded' : 'info'}
          />
        );
    }
  };

  return (
    <div
      className={`my-2 rounded-xl border border-white/10 bg-slate-900/60 backdrop-blur-md overflow-hidden text-xs ${className}`}
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
        className="w-full flex items-center justify-between px-3 py-2 bg-white/[0.03] hover:bg-white/[0.05] transition-colors cursor-pointer select-none text-left"
      >
        <div className="flex items-center gap-2">
          <span className={`w-2 h-2 rounded-full bg-primary-container ${turn.status === 'running' && !turn.interruption ? 'animate-pulse motion-reduce:animate-none' : ''}`} />
          <span className="font-semibold text-slate-200 text-xs">
            Agent 执行流程
          </span>
          <span className="text-[11px] text-slate-400">
            · {turn.items.length} 步骤
            {toolCount > 0 && ` (${toolCount} 个工具)`}
            {reviewItem && ` · 审查: ${reviewItem.verdict || reviewItem.status || 'unknown'}`}
          </span>
        </div>

        <div className="flex items-center gap-1.5 text-slate-400">
          <span className="text-[11px] font-mono uppercase">
            {turn.status}
          </span>
          {isExpanded ? (
            <ChevronUp className="w-3.5 h-3.5" />
          ) : (
            <ChevronDown className="w-3.5 h-3.5" />
          )}
        </div>
      </button>

      {isExpanded && (
        <div id={contentId} className="p-2.5 space-y-1.5 border-t border-white/5 bg-black/10">
          {turn.interruption && <div role="status" className="rounded border border-amber-700/40 bg-amber-950/30 px-2 py-1.5 text-amber-200">{turn.interruption.kind === 'stopped' ? '生成已停止' : '连接中断'}：{turn.interruption.message}</div>}
          {turn.items.map((item, idx) => renderItem(item, idx))}
        </div>
      )}
    </div>
  );
};
