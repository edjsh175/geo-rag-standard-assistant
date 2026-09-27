import React, { useState, useEffect, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { motion, AnimatePresence } from 'motion/react';
import {
  History,
  Plus,
  Trash2,
  RotateCcw,
  ArrowLeft,
  X,
  Search,
  MessageSquare,
  Clock,
  LoaderCircle,
} from 'lucide-react';
import type { AgentSessionSummary } from '../services/agentHistory';
import { cn } from '../lib/utils';
import { drawerGlassStyle } from '../lib/glass';

export interface SessionManagerProps {
  sessions?: AgentSessionSummary[];
  activeSessionId?: string;
  disabled?: boolean;
  loading?: boolean;
  panelWidth?: number;
  onRefresh?: () => Promise<void>;
  onCreate?: () => Promise<void>;
  onSelect?: (sessionId: string) => Promise<void>;
  onDelete?: (sessionId: string) => Promise<void>;
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
  sessions = [],
  activeSessionId,
  disabled = false,
  loading = false,
  panelWidth,
  onRefresh = async () => {},
  onCreate = async () => {},
  onSelect = async () => {},
  onDelete = async () => {},
}) => {
  const [open, setOpen] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [filterKeyword, setFilterKeyword] = useState('');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // Keyboard shortcut: ESC closes drawer
  useEffect(() => {
    if (!open) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [open]);

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

  const filteredSessions = useMemo(() => {
    if (!filterKeyword.trim()) return sessions;
    const kw = filterKeyword.toLowerCase().trim();
    return sessions.filter((s) => (s.title || '').toLowerCase().includes(kw));
  }, [sessions, filterKeyword]);

  const drawerContent = (
    <AnimatePresence>
      {open && (
        <motion.aside
          initial={{ x: '100%' }}
          animate={{ x: 0 }}
          exit={{ x: '100%' }}
          transition={{ type: 'spring', damping: 28, stiffness: 220 }}
          role="dialog"
          aria-label="会话管理"
          className="fixed right-6 top-[80px] bottom-6 z-[60] flex flex-col overflow-hidden"
          style={{
            width: panelWidth || 420,
            maxWidth: 'calc(100vw - 48px)',
            background: 'var(--glass-bg)',
            ...drawerGlassStyle,
            border: '0.5px solid var(--color-outline)',
            borderRadius: '1.5rem',
            boxShadow: '0 24px 64px rgba(0,0,0,0.3)',
          }}
        >
          {/* Header */}
          <div
            className="px-5 py-4 flex items-center justify-between shrink-0"
            style={{ borderBottom: '0.5px solid var(--color-outline)' }}
          >
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-on-background/5 hover:bg-on-background/10 border border-on-background/5 text-on-background/50 hover:text-on-background cursor-pointer"
                title="返回对话"
                aria-label="返回对话"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
              </button>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold font-headline text-on-background/90">会话管理</h3>
                <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-surface-container border border-outline text-on-background/50">
                  {sessions.length}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                disabled={disabled || Boolean(busyId)}
                onClick={() => void run('create', onCreate)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all bg-primary-container text-on-primary-fixed shadow-xs hover:brightness-110 active:scale-95 disabled:opacity-40 cursor-pointer"
                title="新建会话"
              >
                {busyId === 'create' ? (
                  <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Plus className="h-3.5 w-3.5" />
                )}
                <span>新建</span>
              </button>

              <button
                type="button"
                disabled={disabled || loading}
                onClick={() => void onRefresh()}
                className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-on-background/5 hover:bg-on-background/10 border border-on-background/5 text-on-background/50 hover:text-on-background/80 cursor-pointer"
                title="刷新会话列表"
                aria-label="刷新会话列表"
              >
                <RotateCcw className={cn("w-3.5 h-3.5", loading && "animate-spin text-primary-container")} />
              </button>

              <button
                type="button"
                onClick={() => setOpen(false)}
                className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-on-background/5 hover:bg-on-background/10 border border-on-background/5 text-on-background/35 hover:text-on-background/70 cursor-pointer"
                title="关闭"
                aria-label="关闭"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          {/* Search Filter */}
          <div className="px-5 pt-4 pb-1 shrink-0">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-on-background/35 pointer-events-none" />
              <input
                type="text"
                value={filterKeyword}
                onChange={(e) => setFilterKeyword(e.target.value)}
                placeholder="搜索历史会话..."
                className="w-full bg-surface-container/50 border border-outline rounded-xl pl-9 pr-8 py-2 text-xs text-on-background placeholder:text-on-background/35 outline-none transition-all focus:border-primary-container/40 focus:bg-surface-container/80"
              />
              {filterKeyword && (
                <button
                  type="button"
                  onClick={() => setFilterKeyword('')}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-on-background/40 hover:text-on-background/70 p-0.5 rounded cursor-pointer"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>

          {/* Session List */}
          <div className="flex-1 overflow-y-auto p-5 space-y-2.5 no-scrollbar">
            {loading && sessions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 gap-3 text-on-background/50">
                <LoaderCircle className="w-6 h-6 animate-spin text-primary-container" />
                <p className="text-xs font-medium">正在加载历史会话…</p>
              </div>
            ) : filteredSessions.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-16 px-4 text-center">
                <div className="w-12 h-12 rounded-2xl bg-surface-container flex items-center justify-center mb-3 border border-outline">
                  <History className="w-6 h-6 text-on-background/30" />
                </div>
                <p className="text-sm font-medium text-on-background/70 mb-1">
                  {filterKeyword ? '未找到匹配的会话' : '暂无历史会话'}
                </p>
                <p className="text-xs text-on-background/40 max-w-[240px] leading-relaxed">
                  {filterKeyword ? '尝试使用不同的关键词进行检索' : '每次与 GeoAI 助手的交互都会安全持久化保存'}
                </p>
                {!filterKeyword && (
                  <button
                    type="button"
                    disabled={disabled || Boolean(busyId)}
                    onClick={() => void run('create', onCreate)}
                    className="mt-4 flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold bg-primary-container/15 hover:bg-primary-container/25 text-primary-container border border-primary-container/30 transition-all cursor-pointer"
                  >
                    <Plus className="w-3.5 h-3.5" />
                    <span>创建第一个会话</span>
                  </button>
                )}
              </div>
            ) : (
              filteredSessions.map((session) => {
                const active = session.session_id === activeSessionId;
                const busy = busyId === session.session_id || busyId === `delete:${session.session_id}`;
                return (
                  <motion.div
                    key={session.session_id}
                    whileHover={{ x: 2 }}
                    className={cn(
                      "group relative rounded-xl p-3.5 border transition-all duration-200 cursor-pointer",
                      active
                        ? "bg-primary-container/[0.09] border-primary-container/40 shadow-xs"
                        : "bg-surface-container-low/70 hover:bg-surface-container/90 border-outline hover:border-primary-container/30 shadow-xs"
                    )}
                    onClick={() => {
                      if (!busy && !disabled) {
                        void run(session.session_id, async () => {
                          await onSelect(session.session_id);
                          setOpen(false);
                        });
                      }
                    }}
                  >
                    <div className="flex items-start justify-between gap-2.5">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2 mb-1.5">
                          <span
                            className={cn(
                              "text-[13.5px] font-semibold truncate transition-colors leading-snug",
                              active
                                ? "text-primary-container"
                                : "text-on-background/85 group-hover:text-primary-container"
                            )}
                          >
                            {session.title || '新建对话'}
                          </span>
                          {active && (
                            <span className="shrink-0 text-[10px] font-mono px-1.5 py-0.5 rounded bg-primary-container/20 text-primary-container border border-primary-container/30 font-medium">
                              当前
                            </span>
                          )}
                        </div>

                        <div className="flex items-center gap-3 text-[11px] text-on-background/45 font-mono">
                          <span className="flex items-center gap-1">
                            <MessageSquare className="w-3 h-3 opacity-60" />
                            {session.turn_count} 轮
                          </span>
                          {formatUpdatedAt(session.updated_at) && (
                            <span className="flex items-center gap-1">
                              <Clock className="w-3 h-3 opacity-60" />
                              {formatUpdatedAt(session.updated_at)}
                            </span>
                          )}
                        </div>
                      </div>

                      <div className="shrink-0 flex items-center">
                        <button
                          type="button"
                          aria-label={`删除会话 ${session.title || session.session_id}`}
                          title="删除会话"
                          disabled={disabled || Boolean(busyId)}
                          onClick={(e) => {
                            e.stopPropagation();
                            void run(`delete:${session.session_id}`, () => onDelete(session.session_id));
                          }}
                          className={cn(
                            "w-7 h-7 rounded-lg flex items-center justify-center transition-all cursor-pointer",
                            busy
                              ? "opacity-100 bg-red-500/10 text-red-500"
                              : "opacity-0 group-hover:opacity-100 text-on-background/35 hover:text-red-500 hover:bg-red-500/10 border border-transparent hover:border-red-500/25"
                          )}
                        >
                          {busy ? <LoaderCircle className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
                        </button>
                      </div>
                    </div>
                  </motion.div>
                );
              })
            )}
          </div>
        </motion.aside>
      )}
    </AnimatePresence>
  );

  return (
    <div className="relative">
      <motion.button
        type="button"
        aria-label="管理会话"
        title="管理会话"
        aria-expanded={open}
        onClick={() => void toggleOpen()}
        disabled={disabled}
        whileHover={{ scale: 1.05 }}
        whileTap={{ scale: 0.94 }}
        className={cn(
          "w-7 h-7 rounded-lg flex items-center justify-center transition-all border disabled:opacity-40 cursor-pointer",
          open
            ? "bg-primary-container/20 text-primary-container border-primary-container/40 shadow-xs"
            : "bg-surface-variant/40 hover:bg-surface-variant/70 border-outline text-on-background/60 hover:text-on-background"
        )}
      >
        <History className="w-3.5 h-3.5" />
      </motion.button>

      {mounted && typeof document !== 'undefined' ? createPortal(drawerContent, document.body) : null}
    </div>
  );
};
