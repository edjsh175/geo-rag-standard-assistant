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
  /** 当前消息列表 */
  messages: ChatMessageType[];
  /** 发送消息回调 */
  onSendMessage: (content: string) => Promise<void>;
  /** 是否正在加载（AI响应中） */
  isLoading: boolean;
  /** 停止生成回调 */
  onStopGeneration?: () => void;
  /** 当前输入框值 */
  inputValue: string;
  /** 输入框变更回调 */
  onInputChange: (value: string) => void;
  /** 点击引用时的回调 */
  onCitationClick?: (documentId: string) => Promise<void>;
  /** 是否禁用输入（例如在搜索中） */
  disabled?: boolean;
  /** 标题 */
  title?: string;
  /** 状态描述 */
  status?: string;
  /** 快捷标签 */
  quickTags?: string[];
  /** 类名 */
  className?: string;
}

/**
 * 企业级聊天对话组件
 * 包含智能防冲突滚动、加载反馈、请求中断控制等功能
 */
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
  quickTags = ['# 城镇开发边界', '# 永久基本农田', '# 生态保护红线', '# 四川技术规范'],
  className,
}) => {
  // ==================== 所有 Hooks 声明（严格置顶） ====================
  // 1. useRef
  const inputRef = useRef<HTMLInputElement>(null);
  const chatContainerRef = useRef<HTMLDivElement>(null);

  // 2. 自定义 Hook
  const { scrollToBottom, lockAutoScroll, unlockAutoScroll, isAutoScrollLocked } =
    useAutoScroll(chatContainerRef, { threshold: 50 });

  // 3. useEffect
  useEffect(() => {
    console.log('[Chat] 消息变化触发滚动检查', {
      消息数量: messages.length,
      最后一条消息: messages[messages.length - 1]?.role,
      是否锁定: isAutoScrollLocked,
      容器存在: !!chatContainerRef.current,
    });

    if (!isAutoScrollLocked) {
      console.log('[Chat] 自动滚动触发（消息变化）');
      scrollToBottom({ behavior: 'smooth' });
    } else {
      console.log('[Chat] 自动滚动被锁定，跳过滚动');
    }
  }, [messages, isAutoScrollLocked, scrollToBottom]);

  useEffect(() => {
    console.log('[Chat] 加载状态变化', {
      正在加载: isLoading,
      是否锁定: isAutoScrollLocked,
    });

    if (isLoading && !isAutoScrollLocked) {
      console.log('[Chat] 自动滚动触发（加载状态）');
      scrollToBottom({ behavior: 'smooth' });
    } else if (isLoading && isAutoScrollLocked) {
      console.log('[Chat] 加载中但滚动被锁定，跳过滚动');
    }
  }, [isLoading, isAutoScrollLocked, scrollToBottom]);

  useEffect(() => {
    console.log('[Chat] 容器ref状态:', {
      容器存在: !!chatContainerRef.current,
      容器高度: chatContainerRef.current?.clientHeight,
      滚动高度: chatContainerRef.current?.scrollHeight,
      消息数量: messages.length,
      正在加载: isLoading,
    });
  }, [messages, isLoading]);

  // 4. useCallback
  const handleSend = useCallback(async () => {
    if (!inputValue.trim() || isLoading || disabled) return;

    await onSendMessage(inputValue);
    onInputChange('');
    inputRef.current?.focus();
  }, [inputValue, isLoading, disabled, onSendMessage, onInputChange]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  const handleScroll = useCallback(() => {
    if (!chatContainerRef.current) return;

    const { scrollTop, scrollHeight, clientHeight } = chatContainerRef.current;
    const isAtBottom = scrollHeight - scrollTop - clientHeight < 50;

    if (isAtBottom) {
      unlockAutoScroll();
    } else if (!isAutoScrollLocked) {
      lockAutoScroll();
    }
  }, [lockAutoScroll, unlockAutoScroll, isAutoScrollLocked]);

  const handleCitationClick = useCallback(async (citation: Citation) => {
    if (onCitationClick) {
      await onCitationClick(citation.document_id);
    }
  }, [onCitationClick]);

  // ==================== Hooks 声明结束，下方可放置业务逻辑 ====================

  return (
    <div className={cn('flex flex-col h-full min-h-0 overflow-hidden bg-surface-container-low', className)}>
      {/* AI状态栏 */}
      <div className="px-6 py-4 flex items-center justify-between bg-surface-dim/50 border-b border-outline-variant/5">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-primary-container flex items-center justify-center">
            <Bot className="w-5 h-5 text-on-primary-fixed" />
          </div>
          <div>
            <h2 className="text-sm font-bold text-on-background font-headline">{title}</h2>
            <p className="text-[10px] text-emerald-500 flex items-center gap-1">
              <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full animate-pulse"></span>
              {status}
            </p>
          </div>
        </div>
        <History className="w-5 h-5 text-[#50505a] hover:text-[#f0f0f0] cursor-pointer transition-colors" />
      </div>

      {/* 聊天区域 */}
      <div
        ref={chatContainerRef}
        onScroll={handleScroll}
        className="flex-1 min-h-0 overflow-y-auto p-6 space-y-8 no-scrollbar"
      >
        {messages.map((msg) => (
          <ChatMessage
            key={msg.id}
            message={msg}
            onCitationClick={handleCitationClick}
          />
        ))}

        {/* 加载指示器 */}
        {isLoading && (
          <div className="flex gap-3 items-start mr-12">
            <div className="w-8 h-8 rounded-full bg-surface-container-highest flex items-center justify-center shrink-0 border border-outline-variant/20">
              <Sparkles className="w-4 h-4 text-primary" />
            </div>
            <div className="space-y-4 flex-1">
              <div className="bg-surface-variant/40 glass rounded-bl-none border-l-2 border-primary-container p-4 rounded-xl text-sm">
                <LoadingIndicator text="GeoAI 正在检索空间规划标准..." />
              </div>
              {/* 停止生成按钮 */}
              {onStopGeneration && (
                <div className="flex justify-start">
                  <button
                    onClick={onStopGeneration}
                    className="px-3 py-1.5 text-xs font-medium bg-red-500/10 text-red-500 hover:bg-red-500/20 rounded-lg transition-colors flex items-center gap-2"
                  >
                    <X className="w-3 h-3" />
                    停止生成
                  </button>
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* 输入区域 */}
      <div className="p-6 bg-surface-dim/80 glass border-t border-outline-variant/10">
        <div className="relative group">
          <input
            ref={inputRef}
            value={inputValue}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={handleKeyDown}
            className="w-full bg-surface-container-highest border-none rounded-xl py-4 pl-6 pr-16 text-sm text-on-background placeholder:text-[#50505a] focus:ring-1 focus:ring-primary-container transition-all"
            placeholder="输入规划指令或搜索关键词..."
            type="text"
            disabled={disabled || isLoading}
          />
          <div className="absolute right-3 top-1/2 -translate-y-1/2 flex gap-2">
            <Mic className="w-5 h-5 text-[#50505a] hover:text-primary-container cursor-pointer transition-colors" />
            <button
              onClick={handleSend}
              disabled={disabled || isLoading || !inputValue.trim()}
              className="ember-gradient p-2 rounded-lg text-on-primary-fixed shadow-lg active:scale-95 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <Send className="w-5 h-5" />
            </button>
          </div>
        </div>
        <div className="mt-4 flex gap-4 text-[10px] text-[#50505a] font-medium overflow-x-auto no-scrollbar">
          {quickTags.map(tag => (
            <span
              key={tag}
              className="bg-surface-container px-2 py-1 rounded cursor-pointer hover:text-primary-container transition-colors whitespace-nowrap"
              onClick={() => onInputChange(tag)}
            >
              {tag}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
};

// 聊天消息子组件
interface ChatMessageProps {
  message: ChatMessageType;
  onCitationClick?: (citation: Citation) => void;
}

const ChatMessage: React.FC<ChatMessageProps> = ({ message, onCitationClick }) => {
  return (
    <div className={cn("flex", message.role === 'user' ? "justify-end ml-12" : "mr-12 gap-3 items-start")}>
      {message.role === 'assistant' && (
        <div className="w-8 h-8 rounded-full bg-surface-container-highest flex items-center justify-center shrink-0 border border-outline-variant/20">
          <Sparkles className="w-4 h-4 text-primary" />
        </div>
      )}
      <div className="space-y-4 flex-1">
        <div className={cn(
          "p-4 rounded-xl text-sm leading-relaxed shadow-sm",
          message.role === 'user'
            ? "bg-primary-container/5 border border-primary-container/20 rounded-br-none text-on-background"
            : "bg-surface-variant/40 glass rounded-bl-none border-l-2 border-primary-container text-[#90909a]"
        )}>
          {message.role === 'assistant' ? (
            <div className="prose prose-sm dark:prose-invert">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content}</ReactMarkdown>
            </div>
          ) : message.content}
        </div>
        {message.metadata?.citations && message.metadata.citations.length > 0 && (
          <div className="space-y-3">
            {message.metadata.citations.map((citation, idx) => (
              <motion.div
                key={idx}
                whileHover={{ x: 8 }}
                onClick={() => onCitationClick?.(citation)}
                className="group bg-surface-container p-4 rounded-xl border-r-2 border-transparent hover:border-primary-container transition-all cursor-pointer shadow-md"
              >
                <div className="flex justify-between items-start mb-2">
                  <span className="text-[10px] font-bold text-primary-container px-2 py-0.5 bg-primary-container/10 rounded">
                    {citation.document_id}
                  </span>
                  <span className="text-[10px] text-emerald-500 font-mono">
                    置信度: {(citation.confidence * 100).toFixed(1)}%
                  </span>
                </div>
                <h4 className="text-sm font-bold text-on-background mb-1">{citation.title}</h4>
                <p className="text-xs text-[#50505a] line-clamp-2">{citation.excerpt}</p>
              </motion.div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default Chat;