import React, { useState, useRef, useEffect, useCallback } from 'react';
import { motion } from 'motion/react';
import { Bot, Sparkles, Send, Mic, History, X, Download, FileText, Paperclip, ShieldCheck } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '../lib/utils';
import { glassLightStyle } from '../lib/glass';
import { ChatMessage as ChatMessageType, Citation, Document } from '../types';
import LoadingIndicator from './LoadingIndicator';
import { useAutoScroll } from '../hooks/useAutoScroll';
import { AgentProcess } from './agent/AgentProcess';
import { AgentTurnViewModel } from './agent/types';

export interface ChatProps {
  messages: ChatMessageType[];
  onSendMessage: (content: string) => Promise<void>;
  isLoading: boolean;
  activeTurn?: AgentTurnViewModel | null;
  onStopGeneration?: () => void;
  inputValue: string;
  onInputChange: (value: string) => void;
  onCitationClick?: (documentId: string) => Promise<void>;
  onVectorFilesSelected?: (files: File[]) => Promise<string>;
  reviewerEnabled: boolean;
  onReviewerEnabledChange: (enabled: boolean) => void;
  disabled?: boolean;
  title?: string;
  status?: string;
  quickTags?: string[];
  headerAction?: React.ReactNode;
  className?: string;
}

const Chat: React.FC<ChatProps> = ({
  messages,
  onSendMessage,
  isLoading,
  activeTurn,
  onStopGeneration,
  inputValue,
  onInputChange,
  onCitationClick,
  onVectorFilesSelected,
  reviewerEnabled,
  onReviewerEnabledChange,
  disabled = false,
  title = 'Sentinel GeoAI',
  status = '模型就绪 · RAG 已同步',
  quickTags = ['#城镇开发边界', '#永久基本农田', '#生态保护红线', '#四川技术规范'],
  headerAction,
  className,
}) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const vectorFileInputRef = useRef<HTMLInputElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);
  const processDisclosureRef = useRef(new Map<string, boolean>());
  const processKey = (turn: AgentTurnViewModel) => `${turn.sessionId}:${turn.turnId}`;

  const { scrollToBottom, lockAutoScroll, unlockAutoScroll, isAutoScrollLocked } =
    useAutoScroll(chatContainerRef, { threshold: 50 });

  useEffect(() => {
    if (!isAutoScrollLocked) scrollToBottom({ behavior: 'smooth' });
  }, [messages, isAutoScrollLocked, scrollToBottom]);

  useEffect(() => {
    if (isLoading && !isAutoScrollLocked) scrollToBottom({ behavior: 'smooth' });
  }, [isLoading, activeTurn, isAutoScrollLocked, scrollToBottom]);

  const displayQuickTags = [
    '#土地整治与利用',
    '#地裂缝监测预警',
    '#应急避险与处置',
  ];

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || isLoading || disabled) return;
    onInputChange('');
    const messageToSend = inputValue;
    requestAnimationFrame(() => {
      inputRef.current?.focus();
    });
    await onSendMessage(messageToSend);
  }, [inputValue, isLoading, disabled, onSendMessage, onInputChange]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); }
  }, [handleSend]);

  const handleScroll = useCallback(() => {
    if (!chatContainerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = chatContainerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;
    if (isAtBottom) unlockAutoScroll();
    else if (!isAutoScrollLocked) lockAutoScroll();
  }, [lockAutoScroll, unlockAutoScroll, isAutoScrollLocked]);

  const handleCitationClick = useCallback(async (citation: Citation) => {
    if (onCitationClick) await onCitationClick(citation.document_id);
  }, [onCitationClick]);

  const handleVectorFiles = useCallback(async (event: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.target.files ?? []);
    event.target.value = '';
    if (!files.length || !onVectorFilesSelected) return;
    const datasetName = await onVectorFilesSelected(files);
    onInputChange(`导入数据集 ${datasetName}`);
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [onInputChange, onVectorFilesSelected]);

  return (
    <div
      className={cn('flex flex-col h-full min-h-0 overflow-hidden', className)}
      style={{ background: 'transparent' }}
    >
      {/* ── Header ── */}
      <div
        className="px-5 py-3.5 flex items-center justify-between shrink-0 glass-light"
        style={{ ...glassLightStyle, borderBottom: '0.5px solid var(--color-outline)' }}
      >
        <div className="flex items-center gap-3">
          {/* AI Avatar */}
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: 'rgba(240,112,64,0.12)', border: '0.5px solid rgba(240,112,64,0.28)', boxShadow: '0 0 12px rgba(240,112,64,0.15)' }}
          >
            <Bot className="w-4 h-4" style={{ color: '#f07040' }} />
          </div>
          <div>
            <h2 className="text-[15px] font-semibold tracking-wide font-headline text-on-background">{title}</h2>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-soft" style={{ boxShadow: '0 0 5px rgba(16,185,129,0.7)' }} />
              <p className="text-[11.5px] font-medium text-emerald-500/80">{status}</p>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {headerAction}
          <button
            className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-surface-variant/40 hover:bg-surface-variant/70 border border-outline"
          >
            <History className="w-3.5 h-3.5 opacity-60 text-on-background" />
          </button>
        </div>
      </div>

      {/* ── Messages ── */}
      <div
        ref={chatContainerRef}
        onScroll={handleScroll}
        className="flex-1 min-h-0 overflow-y-auto no-scrollbar"
        style={{ padding: '20px 16px', display: 'flex', flexDirection: 'column', gap: '20px' }}
      >
        {messages.map(msg => (
          <ChatMessage key={msg.id} message={msg} onCitationClick={handleCitationClick}
            processExpanded={msg.metadata?.agent_turn ? processDisclosureRef.current.get(processKey(msg.metadata.agent_turn)) : undefined}
            onProcessExpandedChange={msg.metadata?.agent_turn ? (expanded) => processDisclosureRef.current.set(processKey(msg.metadata!.agent_turn!), expanded) : undefined}
          />
        ))}

        {isLoading && (
          <div className="flex gap-3 items-start" style={{ marginRight: '32px' }}>
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
              style={{ background: 'rgba(240,112,64,0.10)', border: '0.5px solid rgba(240,112,64,0.25)', boxShadow: '0 0 10px rgba(240,112,64,0.12)' }}
            >
              <Sparkles className="w-3.5 h-3.5 animate-pulse-soft" style={{ color: '#f07040' }} />
            </div>
            <div className="flex-1 space-y-3">
              {activeTurn && <AgentProcess turn={activeTurn}
                defaultExpanded={processDisclosureRef.current.get(processKey(activeTurn))}
                onExpandedChange={(expanded) => processDisclosureRef.current.set(processKey(activeTurn), expanded)}
              />}
              <div
                className="rounded-2xl rounded-tl-xs p-4 text-sm bg-surface-container-low/80 backdrop-blur-md border border-outline border-l-2 border-l-primary-container shadow-xs"
              >
                <LoadingIndicator text="GeoAI 正在检索空间规划标准..." />
              </div>
              {onStopGeneration && (
                <button
                  onClick={onStopGeneration}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[12.5px] font-medium transition-all bg-red-500/10 hover:bg-red-500/15 text-red-600 dark:text-red-400 border border-red-500/25 cursor-pointer"
                >
                  <X className="w-3 h-3" /> 停止生成
                </button>
              )}
            </div>
          </div>
        )}
      </div>

      {/* ── Input Area ── */}
      <div
        className="shrink-0 px-4 pb-4 pt-3 glass-light"
        style={{ ...glassLightStyle, borderTop: '0.5px solid var(--color-outline)' }}
      >
        {/* Input */}
        <div className="relative">
          <input
            ref={vectorFileInputRef}
            type="file"
            accept=".geojson,.json,.zip,.shp,.dbf,.shx,.prj"
            multiple
            className="hidden"
            onChange={handleVectorFiles}
          />
          <input
            ref={inputRef}
            value={inputValue}
            onChange={e => onInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            className="w-full rounded-xl py-3 pl-11 pr-20 text-[15px] transition-all outline-none bg-surface-variant/40 border border-outline text-on-background"
            style={{
              caretColor: '#f07040',
            }}
            onFocus={e => { e.currentTarget.style.border = '0.5px solid rgba(240,112,64,0.35)'; e.currentTarget.style.boxShadow = '0 0 0 3px rgba(240,112,64,0.07)'; }}
            onBlur={e => { e.currentTarget.style.border = 'var(--color-outline)'; e.currentTarget.style.boxShadow = 'none'; }}
            placeholder="输入规划指令或搜索关键词..."
            type="text"
            disabled={disabled}
          />
          {onVectorFilesSelected && (
            <button
              type="button"
              onClick={() => vectorFileInputRef.current?.click()}
              disabled={disabled || isLoading}
              className="absolute left-2 top-1/2 -translate-y-1/2 w-7 h-7 flex items-center justify-center rounded-lg transition-all text-on-background/40 hover:text-primary-container disabled:opacity-40"
              title="登记 SHP / GeoJSON 到浏览器地图运行时"
            >
              <Paperclip className="w-3.5 h-3.5" />
            </button>
          )}
          <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1.5">
            <button className="w-6 h-6 flex items-center justify-center rounded-lg transition-all" style={{ color: 'rgba(255,255,255,0.25)' }} onMouseEnter={e => { e.currentTarget.style.color = 'rgba(240,112,64,0.7)'; }} onMouseLeave={e => { e.currentTarget.style.color = 'rgba(255,255,255,0.25)'; }}>
              <Mic className="w-3.5 h-3.5" />
            </button>
            <motion.button
              onClick={handleSend}
              disabled={disabled || isLoading || !inputValue.trim()}
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.93 }}
              className="w-7 h-7 rounded-lg flex items-center justify-center transition-all"
              style={{ background: inputValue.trim() ? '#f07040' : 'rgba(240,112,64,0.12)', boxShadow: inputValue.trim() ? '0 0 12px rgba(240,112,64,0.4)' : 'none' }}
            >
              <Send className="w-3.5 h-3.5" style={{ color: inputValue.trim() ? '#1a0a00' : 'rgba(240,112,64,0.4)' }} />
            </motion.button>
          </div>
        </div>

        <div className="mt-2.5 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2 min-w-0">
            <ShieldCheck className="w-3.5 h-3.5 text-on-background/45" />
            <span className="text-[12px] text-on-background/55">证据审查 Reviewer</span>
            <span className="text-[10.5px] text-on-background/35">仅审查知识答案</span>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={reviewerEnabled}
            aria-label="证据审查 Reviewer"
            onClick={() => onReviewerEnabledChange(!reviewerEnabled)}
            disabled={disabled || isLoading}
            className="relative h-5 w-9 shrink-0 rounded-full border border-outline transition-all disabled:opacity-40"
            style={{ background: reviewerEnabled ? 'rgba(240,112,64,0.32)' : 'rgba(255,255,255,0.06)' }}
          >
            <span
              className="absolute top-0.5 h-3.5 w-3.5 rounded-full transition-all"
              style={{
                left: reviewerEnabled ? '18px' : '2px',
                background: reviewerEnabled ? '#f07040' : 'rgba(255,255,255,0.45)',
              }}
            />
          </button>
        </div>

        {/* Quick Tags */}
        <div className="mt-3 flex gap-2 overflow-x-auto no-scrollbar">
          {displayQuickTags.map(tag => (
            <button
              key={tag}
              onClick={() => onInputChange(tag.replace(/^#/, ''))}
              className="shrink-0 px-2.5 py-1 rounded-full text-[12.5px] font-medium transition-all whitespace-nowrap bg-primary-container/[0.07] border border-primary-container/[0.18] text-primary-container/80 hover:bg-primary-container/[0.14] hover:text-primary-container"
            >{tag}</button>
          ))}
        </div>
      </div>
    </div>
  );
};

// ── ChatMessage sub-component ──
interface ChatMessageProps {
  message: ChatMessageType;
  onCitationClick?: (citation: Citation) => void;
  processExpanded?: boolean;
  onProcessExpandedChange?: (expanded: boolean) => void;
}

const ChatMessage: React.FC<ChatMessageProps> = ({ message, onCitationClick, processExpanded, onProcessExpandedChange }) => {
  const isUser = message.role === 'user';
  return (
    <div
      className={cn(
        'flex min-w-0 max-w-full transition-opacity duration-200',
        isUser ? 'justify-end' : 'gap-3 items-start'
      )}
      style={isUser ? { marginLeft: '36px' } : { marginRight: '24px' }}
    >
      {/* AI avatar */}
      {!isUser && (
        <div
          className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
          style={{
            background: 'rgba(240,112,64,0.10)',
            border: '0.5px solid rgba(240,112,64,0.25)',
            boxShadow: '0 0 10px rgba(240,112,64,0.12)',
          }}
        >
          <Sparkles className="w-3.5 h-3.5" style={{ color: '#f07040' }} />
        </div>
      )}

      <div className="min-w-0 flex-1 space-y-3">
        {/* Agent Process Timeline */}
        {!isUser && message.metadata?.agent_turn && (
          <AgentProcess
            turn={message.metadata.agent_turn}
            defaultExpanded={processExpanded}
            onExpandedChange={onProcessExpandedChange}
          />
        )}

        {/* Bubble */}
        <div
          className={cn(
            "max-w-full overflow-hidden text-[15px] leading-[1.75] p-4 border break-words transition-all duration-200",
            isUser
              ? "rounded-2xl rounded-tr-xs bg-primary-container/[0.12] dark:bg-primary-container/[0.10] border-primary-container/25 text-on-background shadow-xs"
              : "rounded-2xl rounded-tl-xs bg-surface-container-low/80 backdrop-blur-md border-outline border-l-2 border-l-primary-container text-on-background/90 shadow-xs"
          )}
          style={{
            boxShadow: isUser
              ? '0 2px 10px rgba(240,112,64,0.06)'
              : '0 2px 12px rgba(0,0,0,0.04)',
          }}
        >
          {!isUser ? (
            <div className="prose max-w-full">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
          ) : (
            message.content
          )}
        </div>

        {/* Timestamp */}
        <p
          className="text-[11.5px] font-mono mt-1 opacity-45 px-1"
          style={{
            color: 'var(--color-on-background)',
            textAlign: isUser ? 'right' : 'left',
            letterSpacing: '0.04em',
          }}
        >
          {new Date(message.timestamp).toLocaleTimeString('zh-CN', {
            hour: '2-digit',
            minute: '2-digit',
          })}
        </p>

        {/* Citations */}
        {message.metadata?.citations && message.metadata.citations.length > 0 && (
          <div className="space-y-2 mt-2 pt-1">
            <div className="flex items-center gap-1.5 px-0.5 text-[11px] font-semibold text-on-background/45 uppercase tracking-wider">
              <FileText className="w-3.5 h-3.5 text-primary-container" />
              <span>参考资料与溯源</span>
            </div>
            {message.metadata.citations.map((citation, idx) => (
              <motion.div
                key={idx}
                whileHover={{ x: 3 }}
                onClick={() => onCitationClick?.(citation)}
                className="group rounded-xl p-3.5 cursor-pointer transition-all duration-200 bg-surface-container-low/75 hover:bg-surface-container/90 border border-outline hover:border-primary-container/40 shadow-xs hover:shadow-sm"
              >
                <div className="flex justify-between items-center mb-1.5">
                  <span className="text-[11px] font-semibold px-2 py-0.5 rounded-md font-mono bg-primary-container/10 border border-primary-container/20 text-primary-container">
                    {citation.document_id}
                  </span>
                  <span className="text-[11px] font-mono text-emerald-600 dark:text-emerald-400 font-medium flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-soft" />
                    {(citation.confidence * 100).toFixed(1)}% 匹配
                  </span>
                </div>
                <h4 className="text-[13.5px] font-semibold mb-1 text-on-background/85 group-hover:text-primary-container transition-colors leading-snug">
                  {citation.title}
                </h4>
                <p className="text-[12px] line-clamp-2 text-on-background/55 leading-relaxed">
                  {citation.excerpt}
                </p>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default Chat;
