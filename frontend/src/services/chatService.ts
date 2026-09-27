import { AxiosError } from 'axios';
import { apiPost, apiPostSse } from '../lib/api/contractClient';
import { apiClient } from '../lib/api/config';
import type { components } from '../lib/api/generated/schema';
import { executeBrowserTool, getBrowserMapContext } from '../gis/browserBridge';
import type { BrowserMapAction, BrowserToolReceipt } from '../gis/contracts';
import type { AgentEventMessage } from '../components/agent/types';

export type ChatHistoryMessage = components['schemas']['ChatHistoryMessage'];
export type DocumentResult = components['schemas']['DocumentResult'];
export type FollowUpContext = components['schemas']['FollowUpContext'];
export type SearchResponse = components['schemas']['SearchResponse'];
export type DemoQuotaStatus = components['schemas']['DemoQuotaStatus'];
export type MapAction = components['schemas']['MapAction'];

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  references?: DocumentResult[];
  timestamp?: string;
}

export interface ChatRequest {
  message: string;
  conversation_id?: string;
  use_context?: boolean;
  max_tokens?: number;
}

export interface ChatResponse {
  message: string;
  conversation_id: string;
  references?: DocumentResult[];
  timestamp: string;
  quota?: DemoQuotaStatus;
  map_action?: MapAction;
}

export const withActiveMapContext = (
  request: components['schemas']['SearchRequest'],
): components['schemas']['SearchRequest'] => ({
  ...request,
  map_context: getBrowserMapContext() ?? undefined,
});

class BrowserContinuationError extends Error {
  constructor(
    readonly response: SearchResponse,
    readonly stage: 'gis' | 'continuation',
    message: string,
    readonly causeError?: unknown,
  ) {
    super(message);
    this.name = 'BrowserContinuationError';
  }
}

const getSearchFallbackMessage = (response: SearchResponse): string => {
  if (response.quota?.exhausted) {
    return `${response.quota.contact_text}\n\n您仍可继续查看检索结果、引用文档和地图联动内容。`;
  }
  if (response.publication_state === 'tool_execution_required') {
    return (response.results?.length ?? 0) > 0
      ? '已检索到相关标准，正在准备地图联动。'
      : '查询已进入地图联动处理阶段。';
  }
  return (response.results?.length ?? 0) > 0
    ? '已检索到相关标准，请查看下方参考文档。'
    : '未在库中检索到相关标准规定。';
};

const toChatResponse = (
  response: SearchResponse,
  conversationId?: string,
  warning?: string,
): ChatResponse => ({
  message: [response.generated_answer || getSearchFallbackMessage(response), warning]
    .filter(Boolean)
    .join('\n\n'),
  conversation_id: response.session_id || conversationId || `conv_${Date.now()}`,
  references: response.results || [],
  timestamp: new Date().toISOString(),
  quota: response.quota ?? undefined,
  map_action: warning ? undefined : response.map_action ?? undefined,
});

const getRequestFailureMessage = (error: unknown): string => {
  if (error instanceof AxiosError) {
    if (error.response?.status === 401) {
      return '登录状态已失效，请重新登录后继续。';
    }
    if (error.response) {
      return `查询服务返回错误（HTTP ${error.response.status}），请稍后重试。`;
    }
    if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
      return '查询超时，请稍后重试。';
    }
    if (error.request) {
      return '无法连接查询服务，请检查后端是否运行后重试。';
    }
  }
  return '查询处理失败，请稍后重试。';
};

/**
 * 聊天服务
 * 注意：后端可能还没有专门的聊天端点，目前使用搜索服务生成答案
 */
export const chatService = {
  async runAgentRequest(
    searchRequest: components['schemas']['SearchRequest'],
    signal?: AbortSignal,
  ): Promise<SearchResponse> {
    let request = searchRequest;
    let latestResponse: SearchResponse | null = null;
    for (let browserStep = 0; browserStep < 8; browserStep += 1) {
      let response: SearchResponse;
      try {
        response = await apiPost('/api/search/query', request, {
          // Agent search may spend up to 60 seconds in model stages after retrieval.
          // Keep the client from aborting valid backend work at the global 30 second limit.
          config: { signal, timeout: 120_000 },
        });
      } catch (error) {
        if (latestResponse?.publication_state === 'tool_execution_required') {
          if (error instanceof AxiosError && error.response?.status === 401) {
            throw error;
          }
          throw new BrowserContinuationError(
            latestResponse,
            'continuation',
            'The browser GIS continuation request failed.',
            error,
          );
        }
        throw error;
      }
      latestResponse = response;
      if (response.publication_state !== 'tool_execution_required') return response;
      if (!response.trace_id || !response.pending_tool_call_id || !response.continuation_token || !response.map_action) {
        throw new BrowserContinuationError(
          response,
          'gis',
          'The browser tool continuation contract is incomplete.',
        );
      }
      let receipt: BrowserToolReceipt;
      try {
        receipt = await executeBrowserTool(
          response.trace_id,
          response.pending_tool_call_id,
          response.map_action as BrowserMapAction,
        );
      } catch (error) {
        throw new BrowserContinuationError(
          response,
          'gis',
          'The browser GIS tool could not be executed.',
          error,
        );
      }
      request = {
        ...searchRequest,
        session_id: response.session_id ?? searchRequest.session_id,
        history: [],
        map_context: receipt.map_context,
        continuation_token: response.continuation_token,
        browser_tool_receipt: receipt,
      };
    }
    if (latestResponse) {
      throw new BrowserContinuationError(
        latestResponse,
        'gis',
        'Browser GIS continuation exceeded the client safety limit.',
      );
    }
    throw new Error('Search request completed without a response.');
  },

  /**
   * 发送聊天消息
   */
  async sendMessage(
    message: string,
    conversationId?: string,
    history: ChatHistoryMessage[] = [],
    signal?: AbortSignal,
    followUpContext?: FollowUpContext,
    onAgentEvent?: (event: AgentEventMessage) => void
  ): Promise<ChatResponse> {
    if (onAgentEvent) {
      return this.sendMessageStream(
        message,
        conversationId,
        undefined,
        history,
        followUpContext,
        onAgentEvent,
        signal
      );
    }
    try {
      const searchRequest = withActiveMapContext({
        query: message,
        top_k: 5,
        use_generation: true,
        search_mode: 'semantic',
        session_id: conversationId,
        history,
        follow_up_context: followUpContext,
      });

      const searchResponse = await this.runAgentRequest(searchRequest, signal);
      return toChatResponse(searchResponse, conversationId);
    } catch (error) {
      console.error('发送聊天消息失败:', error);

      if (error instanceof BrowserContinuationError) {
        console.warn('检索已完成，但地图联动未完成:', error.causeError ?? error.message);
        const hasSearchResults = (error.response.results?.length ?? 0) > 0;
        const warning = error.stage === 'gis'
          ? hasSearchResults
            ? '地图联动未完成，已检索到的标准仍可查看。请确认地图已加载后重试地图操作。'
            : '地图联动未完成，请确认地图已加载后重试该查询。'
          : error.causeError instanceof AxiosError && error.causeError.response
            ? hasSearchResults
              ? `已检索到的标准仍可查看，但地图联动后的续接请求失败（HTTP ${error.causeError.response.status}）。`
              : `地图联动后的续接请求失败（HTTP ${error.causeError.response.status}）。`
            : hasSearchResults
              ? '已检索到的标准仍可查看，但地图联动后的续接请求未完成。'
              : '地图联动后的续接请求未完成。';
        return toChatResponse(
          error.response,
          conversationId,
          warning,
        );
      }

      return {
        message: getRequestFailureMessage(error),
        conversation_id: conversationId || `conv_${Date.now()}`,
        references: [],
        timestamp: new Date().toISOString(),
      };
    }
  },

  /**
   * 获取对话历史
   */
  async getConversationHistory(conversationId: string): Promise<ChatMessage[]> {
    try {
      if (!conversationId) return [];
      const res = await apiClient.get<{
        messages?: Array<{
          role: 'user' | 'assistant';
          content: string;
          timestamp?: string;
          references?: DocumentResult[];
        }>;
      }>(`/agent/sessions/${encodeURIComponent(conversationId)}`);
      if (Array.isArray(res.data?.messages)) {
        return res.data.messages.map((m) => ({
          role: m.role,
          content: m.content,
          references: m.references,
          timestamp: m.timestamp,
        }));
      }
      return [];
    } catch (error) {
      console.warn(`获取对话历史失败 (ID: ${conversationId}):`, error);
      return [];
    }
  },

  /**
   * 创建新对话
   */
  async createConversation(): Promise<string> {
    return `conv_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
  },

  /**
   * 删除对话
   */
  async deleteConversation(conversationId: string): Promise<void> {
    try {
      if (!conversationId) return;
      await apiClient.delete(`/agent/sessions/${encodeURIComponent(conversationId)}`);
    } catch (error) {
      console.error(`删除对话失败 (ID: ${conversationId}):`, error);
    }
  },

  /**
   * 流式聊天（支持 Agent 事件流与渐进式展示）
   */
  async sendMessageStream(
    message: string,
    conversationId?: string,
    onChunk?: (chunk: string) => void,
    history: ChatHistoryMessage[] = [],
    followUpContext?: FollowUpContext,
    onAgentEvent?: (event: AgentEventMessage) => void,
    signal?: AbortSignal
  ): Promise<ChatResponse> {
    try {
      let finalResponse: SearchResponse | null = null;
      await apiPostSse(
        '/api/search/query/stream',
        withActiveMapContext({
          query: message,
          search_mode: 'hybrid',
          top_k: 10,
          threshold: 0.6,
          use_rerank: true,
          use_generation: true,
          session_id: conversationId,
          history,
          follow_up_context: followUpContext,
        }),
        (eventType, data) => {
          if (eventType === 'result') {
            finalResponse = JSON.parse(data) as SearchResponse;
          } else if (eventType === 'chunk' || eventType === 'token') {
            onChunk?.(data);
          } else {
            try {
              const parsed = JSON.parse(data);
              const agentEvent: AgentEventMessage = {
                event_type: eventType,
                session_id: parsed.session_id || '',
                turn_id: parsed.turn_id || '',
                trace_id: parsed.trace_id,
                payload: parsed.payload || {},
                created_at: parsed.created_at,
              };
              onAgentEvent?.(agentEvent);
            } catch {
              onChunk?.(data);
            }
          }
        },
        { signal }
      );

      if (!finalResponse) throw new Error('stream completed without result event');

      if ((finalResponse as SearchResponse).publication_state === 'tool_execution_required') {
        const resp = finalResponse as SearchResponse;
        if (!resp.trace_id || !resp.pending_tool_call_id || !resp.continuation_token || !resp.map_action) {
          throw new BrowserContinuationError(
            resp,
            'gis',
            'The browser tool continuation contract is incomplete.'
          );
        }
        let receipt: BrowserToolReceipt;
        try {
          receipt = await executeBrowserTool(
            resp.trace_id,
            resp.pending_tool_call_id,
            resp.map_action as BrowserMapAction,
          );
        } catch (error) {
          throw new BrowserContinuationError(
            resp,
            'gis',
            'The browser GIS tool could not be executed.',
            error
          );
        }
        finalResponse = await this.runAgentRequest({
          query: message,
          search_mode: 'hybrid',
          top_k: 10,
          threshold: 0.6,
          use_rerank: true,
          use_generation: true,
          session_id: resp.session_id || conversationId,
          history: [],
          follow_up_context: followUpContext,
          map_context: receipt.map_context,
          continuation_token: resp.continuation_token,
          browser_tool_receipt: receipt,
        }, signal);
      }

      return toChatResponse(finalResponse, conversationId);
    } catch (error) {
      console.error('流式聊天失败:', error);
      if (error instanceof BrowserContinuationError) {
        return toChatResponse(error.response, conversationId, '地图联动未完成');
      }
      return {
        message: getRequestFailureMessage(error),
        conversation_id: conversationId || `conv_${Date.now()}`,
        references: [],
        timestamp: new Date().toISOString(),
      };
    }
  },

  /**
   * 简单聊天（快捷方法）
   */
  async quickChat(message: string): Promise<{ answer: string; references: DocumentResult[] }> {
    const response = await this.sendMessage(message, undefined, [], undefined, undefined);
    return {
      answer: response.message,
      references: response.references || [],
    };
  },

  /**
   * 取消指定的 Agent 运行轮次
   */
  async cancelTurn(sessionId: string, turnId: string, reason = 'user_stop'): Promise<boolean> {
    try {
      await apiPost('/api/search/query/cancel', {
        session_id: sessionId,
        turn_id: turnId,
        reason,
      });
      return true;
    } catch (error) {
      console.warn('通知后端取消失败:', error);
      return false;
    }
  },
};
