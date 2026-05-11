import { apiClient } from '../lib/api/config';
import type {
  ChatMessage,
  ChatRequest,
  ChatResponse,
  DocumentResult,
  FollowUpContext,
  SearchResponse,
} from '../types/api';

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
    history: Array<{ role: string; content: string }> = [],
    signal?: AbortSignal,
    followUpContext?: FollowUpContext
  ): Promise<ChatResponse> {
    try {
      // 方法1: 如果后端有专门的聊天端点
      // const request: ChatRequest = { message, conversation_id: conversationId };
      // const response = await apiClient.post<ChatResponse>('/chat/query', request);
      // return response;

      // 方法2: 使用搜索服务的生成答案功能（当前实现）
      const searchRequest = {
        query: message,
        top_k: 5,
        use_generation: true,
        search_mode: 'semantic' as const,
        history: history,
        follow_up_context: followUpContext,
      };

      const response = await apiClient.post<SearchResponse>('/search/query', searchRequest, {
        signal,
      });
      const searchResponse = response.data;

      // 转换搜索响应为聊天响应
      const fallbackMessage = (searchResponse.results?.length ?? 0) > 0
        ? '已检索到相关标准，请查看下方参考文档。'
        : '未在库中检索到相关标准规定。';

      const chatResponse: ChatResponse = {
        message: searchResponse.generated_answer || fallbackMessage,
        conversation_id: conversationId || `conv_${Date.now()}`,
        references: searchResponse.results || [],
        timestamp: new Date().toISOString(),
      };

      return chatResponse;
    } catch (error) {
      console.error('发送聊天消息失败:', error);

      // 返回错误响应
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
      // TODO: 后端需要实现对话历史端点
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
      // TODO: 后端需要实现对话删除端点
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
    history: Array<{ role: string; content: string }> = [],
    followUpContext?: FollowUpContext
  ): Promise<ChatResponse> {
    try {
      // TODO: 实现WebSocket或SSE流式响应
      // 目前使用普通请求
      return await this.sendMessage(message, conversationId, history, undefined, followUpContext);
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
