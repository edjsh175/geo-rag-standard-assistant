import React, { useState } from 'react';
import { History, LoaderCircle, Plus, Trash2 } from 'lucide-react';
import type { AgentSessionSummary } from '../services/agentHistory';
import { cn } from '../lib/utils';

interface SessionManagerProps {
  sessions: AgentSessionSummary[];
  activeSessionId?: string;
  disabled?: boolean;
  loading?: boolean;
  onRefresh: () => Promise<void>;
  onCreate: () => Promise<void>;
  onSelect: (sessionId: string) => Promise<void>;
  onDelete: (sessionId: string) => Promise<void>;
}

const formatUpdatedAt = (value?: string | null): string => {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export const SessionManager: React.FC<SessionManagerProps> = ({
  sessions,
  activeSessionId,
  disabled = false,
  loading = false,
  onRefresh,
  onCreate,
  onSelect,
  onDelete,
}) => {
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const run = async (id: string, action: () => Promise<void>) => {
    if (busyId || disabled) return;
    setBusyId(id);
    try {
      await action();
    } finally {
      setBusyId(null);
    }
  };

  const toggleOpen = async () => {
    const next = !open;
    setOpen(next);
    if (next && !disabled) {
      await onRefresh().catch((error) => console.warn('刷新会话列表失败:', error));
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        aria-label="管理会话"
        title="管理会话"
        aria-expanded={open}
        onClick={() => void toggleOpen()}
        disabled={disabled}
        className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-surface-variant/40 hover:bg-surface-variant/70 border border-outline disabled:opacity-40"
      >
        <History className="w-3.5 h-3.5 opacity-60 text-on-background" />
      </button>

      {open && (
        <div
          className="absolute right-0 top-9 z-[90] w-[310px] overflow-hidden rounded-xl border border-outline bg-surface-container shadow-2xl"
          role="dialog"
          aria-label="会话管理"
        >
          <div className="flex items-center justify-between gap-3 border-b border-outline px-3 py-2.5">
            <div>
              <div className="text-[13px] font-semibold text-on-background/85">会话</div>
              <div className="text-[10.5px] text-on-background/40">服务端持久化 · {sessions.length} 个</div>
            </div>
            <button
              type="button"
              disabled={disabled || Boolean(busyId)}
              onClick={() => void run('create', onCreate)}
              className="flex items-center gap-1 rounded-lg border border-outline bg-surface-variant/50 px-2 py-1 text-[11px] text-on-background/70 hover:bg-surface-variant disabled:opacity-40"
            >
              {busyId === 'create' ? <LoaderCircle className="h-3 w-3 animate-spin" /> : <Plus className="h-3 w-3" />}
              新建
            </button>
          </div>

          <div className="max-h-[320px] overflow-y-auto p-1.5">
            {loading ? (
              <div className="flex items-center justify-center gap-2 px-3 py-6 text-xs text-on-background/45">
                <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> 加载会话…
              </div>
            ) : sessions.length === 0 ? (
              <div className="px-3 py-6 text-center text-xs text-on-background/40">暂无历史会话</div>
            ) : sessions.map((session) => {
              const active = session.session_id === activeSessionId;
              const busy = busyId === session.session_id || busyId === `delete:${session.session_id}`;
              return (
                <div
                  key={session.session_id}
                  className={cn(
                    'group flex items-center gap-1 rounded-lg border px-1 py-1 transition-colors',
                    active ? 'border-primary-container/35 bg-primary-container/10' : 'border-transparent hover:bg-surface-variant/40'
                  )}
                >
                  <button
                    type="button"
                    disabled={disabled || Boolean(busyId)}
                    onClick={() => void run(session.session_id, () => onSelect(session.session_id))}
                    className="min-w-0 flex-1 rounded-md px-2 py-1.5 text-left disabled:opacity-50"
                  >
                    <div className="truncate text-[12px] font-medium text-on-background/78">{session.title || '新建对话'}</div>
                    <div className="mt-0.5 flex items-center gap-2 text-[10px] text-on-background/35">
                      <span>{session.turn_count} 轮</span>
                      {formatUpdatedAt(session.updated_at) && <span>{formatUpdatedAt(session.updated_at)}</span>}
                      {active && <span className="text-primary-container/75">当前</span>}
                    </div>
                  </button>
                  <button
                    type="button"
                    aria-label={`删除会话 ${session.title || session.session_id}`}
                    title="删除会话"
                    disabled={disabled || Boolean(busyId)}
                    onClick={() => void run(`delete:${session.session_id}`, () => onDelete(session.session_id))}
                    className="mr-1 flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-on-background/25 opacity-0 transition-all hover:bg-red-500/10 hover:text-red-400 group-hover:opacity-100 focus:opacity-100 disabled:opacity-20"
                  >
                    {busy && <LoaderCircle className="h-3 w-3 animate-spin" />}
                    {!busy && <Trash2 className="h-3 w-3" />}
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
};
