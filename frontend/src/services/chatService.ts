import { apiPost, apiPostSse } from '../lib/api/contractClient';
import type { components } from '../lib/api/generated/schema';

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

/**
 * 聊天服务
 * 注意：后端可能还没有专门的聊天端点，目前使用搜索服务生成答案
 */
export const chatService = {
  /**
   * 发送聊天消息
   */
  async sendMessage(
    message: string,
    conversationId?: string,
    history: ChatHistoryMessage[] = [],
    signal?: AbortSignal,
    followUpContext?: FollowUpContext
  ): Promise<ChatResponse> {
    try {
      const searchRequest: components['schemas']['SearchRequest'] = {
        query: message,
        top_k: 5,
        use_generation: true,
        search_mode: 'semantic',
        session_id: conversationId,
        history,
        follow_up_context: followUpContext,
      };

      const searchResponse: SearchResponse = await apiPost('/api/search/query', searchRequest, {
        config: { signal },
      });
      const quota = searchResponse.quota;

      const fallbackMessage = quota?.exhausted
        ? `${quota.contact_text}\n\n您仍可继续查看检索结果、引用文档和地图联动内容。`
        : (searchResponse.results?.length ?? 0) > 0
        ? '已检索到相关标准，请查看下方参考文档。'
        : '未在库中检索到相关标准规定。';

      return {
        message: searchResponse.generated_answer || fallbackMessage,
        conversation_id: searchResponse.session_id || conversationId || `conv_${Date.now()}`,
        references: searchResponse.results || [],
        timestamp: new Date().toISOString(),
        quota,
        map_action: searchResponse.map_action ?? undefined,
      };
    } catch (error) {
      console.error('发送聊天消息失败:', error);

      return {
        message: '抱歉，服务暂时不可用，请稍后重试。',
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
      void conversationId;
      return [];
    } catch (error) {
      console.error(`获取对话历史失败 (ID: ${conversationId}):`, error);
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
      console.log(`删除对话: ${conversationId}`);
    } catch (error) {
      console.error(`删除对话失败 (ID: ${conversationId}):`, error);
    }
  },

  /**
   * 流式聊天（如果后端支持）
   */
  async sendMessageStream(
    message: string,
    conversationId?: string,
    onChunk?: (chunk: string) => void,
    history: ChatHistoryMessage[] = [],
    followUpContext?: FollowUpContext
  ): Promise<ChatResponse> {
    try {
      let finalResponse: SearchResponse | null = null;
      await apiPostSse('/api/search/query/stream', {
          query: message,
          search_mode: 'hybrid',
          top_k: 10,
          threshold: 0.6,
          use_rerank: true,
          use_generation: true,
          session_id: conversationId,
          history,
          follow_up_context: followUpContext,
        }, (eventType, data) => {
        if (eventType === 'result') {
          finalResponse = JSON.parse(data) as SearchResponse;
        } else {
          onChunk?.(data);
        }
      });
      if (!finalResponse) throw new Error('stream completed without result event');

      const quota = finalResponse.quota;
      const fallbackMessage = quota?.exhausted
        ? `${quota.contact_text}\n\n您仍可继续查看检索结果、引用文档和地图联动内容。`
        : (finalResponse.results?.length ?? 0) > 0
          ? '已检索到相关标准，请查看下方参考文档。'
          : '未在库中检索到相关标准规定。';
      return {
        message: finalResponse.generated_answer || fallbackMessage,
        conversation_id: finalResponse.session_id || conversationId || `conv_${Date.now()}`,
        references: finalResponse.results || [],
        timestamp: new Date().toISOString(),
        quota,
        map_action: finalResponse.map_action ?? undefined,
      };
    } catch (error) {
      console.error('流式聊天失败:', error);
      return {
        message: '流式聊天功能暂不可用。',
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
};
