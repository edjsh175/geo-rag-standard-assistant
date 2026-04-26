import React, { useState, useRef, useEffect, useCallback } from 'react';
import { motion } from 'motion/react';
import { Bot, Sparkles, Send, Mic, History, X, Download, FileText } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '../lib/utils';
import { ChatMessage as ChatMessageType, Citation, Document } from '../types';
import LoadingIndicator from './LoadingIndicator';
import { useAutoScroll } from '../hooks/useAutoScroll';

export interface ChatProps {
  messages: ChatMessageType[];
  onSendMessage: (content: string) => Promise<void>;
  isLoading: boolean;
  onStopGeneration?: () => void;
  inputValue: string;
  onInputChange: (value: string) => void;
  onCitationClick?: (documentId: string) => Promise<void>;
  disabled?: boolean;
  title?: string;
  status?: string;
  quickTags?: string[];
  className?: string;
}

const Chat: React.FC<ChatProps> = ({
  messages,
  onSendMessage,
  isLoading,
  onStopGeneration,
  inputValue,
  onInputChange,
  onCitationClick,
  disabled = false,
  title = 'Sentinel GeoAI',
  status = '模型就绪 · RAG 已同步',
  quickTags = ['#城镇开发边界', '#永久基本农田', '#生态保护红线', '#四川技术规范'],
  className,
}) => {
  const inputRef = useRef<HTMLInputElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  const { scrollToBottom, lockAutoScroll, unlockAutoScroll, isAutoScrollLocked } =
    useAutoScroll(chatContainerRef, { threshold: 50 });

  useEffect(() => {
    if (!isAutoScrollLocked) scrollToBottom({ behavior: 'smooth' });
  }, [messages, isAutoScrollLocked, scrollToBottom]);

  useEffect(() => {
    if (isLoading && !isAutoScrollLocked) scrollToBottom({ behavior: 'smooth' });
  }, [isLoading, isAutoScrollLocked, scrollToBottom]);

  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || isLoading || disabled) return;
    await onSendMessage(inputValue);
    onInputChange('');
    inputRef.current?.focus();
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

  return (
    <div
      className={cn('flex flex-col h-full min-h-0 overflow-hidden', className)}
      style={{ background: 'transparent' }}
    >
      {/* ── Header ── */}
      <div
        className="px-5 py-3.5 flex items-center justify-between shrink-0 glass-light"
        style={{ borderBottom: '0.5px solid var(--color-outline)' }}
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
        <button
          className="w-7 h-7 rounded-lg flex items-center justify-center transition-all bg-surface-variant/40 hover:bg-surface-variant/70 border border-outline"
        >
          <History className="w-3.5 h-3.5 opacity-60 text-on-background" />
        </button>
      </div>

      {/* ── Messages ── */}
      <div
        ref={chatContainerRef}
        onScroll={handleScroll}
        className="flex-1 min-h-0 overflow-y-auto no-scrollbar"
        style={{ padding: '20px 16px', display: 'flex', flexDirection: 'column', gap: '20px' }}
      >
        {messages.map(msg => (
          <ChatMessage key={msg.id} message={msg} onCitationClick={handleCitationClick} />
        ))}

        {isLoading && (
          <div className="flex gap-3 items-start" style={{ marginRight: '40px' }}>
            <div
              className="w-7 h-7 rounded-full flex items-center justify-center shrink-0"
              style={{ background: 'rgba(240,112,64,0.08)', border: '0.5px solid rgba(240,112,64,0.2)' }}
            >
              <Sparkles className="w-3.5 h-3.5" style={{ color: 'rgba(240,112,64,0.7)' }} />
            </div>
            <div className="flex-1 space-y-3">
              <div
                className="rounded-xl rounded-tl-sm p-4 text-sm bg-surface-container/60 border-l-[1.5px] border-primary-container"
              >
                <LoadingIndicator text="GeoAI 正在检索空间规划标准..." />
              </div>
              {onStopGeneration && (
                <button
                  onClick={onStopGeneration}
                  className="flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[12.5px] font-medium transition-colors"
                  style={{ background: 'rgba(239,68,68,0.08)', color: 'rgba(239,68,68,0.75)', border: '0.5px solid rgba(239,68,68,0.2)' }}
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
        style={{ borderTop: '0.5px solid var(--color-outline)' }}
      >
        {/* Input */}
        <div className="relative">
          <input
            ref={inputRef}
            value={inputValue}
            onChange={e => onInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            className="w-full rounded-xl py-3 pl-4 pr-20 text-[15px] transition-all outline-none bg-surface-variant/40 border border-outline text-on-background"
            style={{
              caretColor: '#f07040',
            }}
            onFocus={e => { e.currentTarget.style.border = '0.5px solid rgba(240,112,64,0.35)'; e.currentTarget.style.boxShadow = '0 0 0 3px rgba(240,112,64,0.07)'; }}
            onBlur={e => { e.currentTarget.style.border = 'var(--color-outline)'; e.currentTarget.style.boxShadow = 'none'; }}
            placeholder="输入规划指令或搜索关键词..."
            type="text"
            disabled={disabled || isLoading}
          />
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

        {/* Quick Tags */}
        <div className="mt-3 flex gap-2 overflow-x-auto no-scrollbar">
          {quickTags.map(tag => (
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
}

const ChatMessage: React.FC<ChatMessageProps> = ({ message, onCitationClick }) => {
  const isUser = message.role === 'user';
  return (
    <div className={cn('flex min-w-0 max-w-full', isUser ? 'justify-end' : 'gap-3 items-start')} style={isUser ? { marginLeft: '40px' } : { marginRight: '32px' }}>
      {/* AI avatar */}
      {!isUser && (
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center shrink-0"
          style={{ background: 'rgba(240,112,64,0.08)', border: '0.5px solid rgba(240,112,64,0.2)' }}
        >
          <Sparkles className="w-3.5 h-3.5" style={{ color: 'rgba(240,112,64,0.65)' }} />
        </div>
      )}

      <div className="min-w-0 flex-1 space-y-3">
        {/* Bubble */}
        <div
          className={cn(
            "max-w-full overflow-hidden rounded-xl text-[15px] leading-[1.75] p-3.5 border break-words",
            isUser ? "bg-primary-container/[0.07] border-primary-container/[0.18] text-on-background/90" : "bg-surface-container/60 border-outline text-on-background/90"
          )}
          style={
            isUser
              ? { borderBottomRightRadius: '4px' }
              : { borderLeft: '1.5px solid rgba(240,112,64,0.30)', borderRadius: '0 10px 10px 10px' }
          }
        >
          {!isUser ? (
            <div className="prose max-w-full">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
          ) : message.content}
        </div>

        {/* Timestamp */}
        <p className="text-[12.5px] font-mono mt-1 opacity-40" style={{ color: 'var(--color-on-background)', textAlign: isUser ? 'right' : 'left', letterSpacing: '0.05em' }}>
          {new Date(message.timestamp).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}
        </p>

        {/* Citations */}
        {message.metadata?.citations && message.metadata.citations.length > 0 && (
          <div className="space-y-2">
            {message.metadata.citations.map((citation, idx) => (
              <motion.div
                key={idx}
                whileHover={{ x: 4 }}
                onClick={() => onCitationClick?.(citation)}
                className="rounded-xl p-3.5 cursor-pointer transition-all bg-surface-container/70 border border-outline hover:border-primary-container/30"
              >
                <div className="flex justify-between items-center mb-1.5">
                  <span
                    className="text-[11.5px] font-semibold px-1.5 py-0.5 rounded font-mono bg-primary-container/10 text-primary-container"
                  >
                    {citation.document_id}
                  </span>
                  <span className="text-[11.5px] font-mono text-emerald-500/70">
                    {(citation.confidence * 100).toFixed(1)}%
                  </span>
                </div>
                <h4 className="text-[13.5px] font-semibold mb-1 text-on-background/80">{citation.title}</h4>
                <p className="text-[12.5px] line-clamp-2 opacity-50 text-on-background">{citation.excerpt}</p>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default Chat;
