import { apiClient } from '../lib/api/config';
import type {
  ChatMessage,
  ChatRequest,
  ChatResponse,
  DocumentResult,
  FollowUpContext,
} from '../types/api';

export const chatService = {
  async sendMessage(
    message: string,
    conversationId?: string,
    history: Array<{ role: string; content: string }> = [],
    signal?: AbortSignal,
    followUpContext?: FollowUpContext
  ): Promise<ChatResponse> {
    try {
      const request: ChatRequest = {
        message,
        conversation_id: conversationId,
        history,
        follow_up_context: followUpContext,
        top_k: 5,
      };

      const response = await apiClient.post<ChatResponse>('/chat/query', request, {
        signal,
      });

      return response.data;
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

  async getConversationHistory(conversationId: string): Promise<ChatMessage[]> {
    try {
      return [];
    } catch (error) {
      console.error(`获取对话历史失败 (ID: ${conversationId}):`, error);
      return [];
    }
  },

  async createConversation(): Promise<string> {
    return `conv_${Date.now()}_${Math.random().toString(36).slice(2, 11)}`;
  },

  async deleteConversation(conversationId: string): Promise<void> {
    try {
      console.log(`删除对话: ${conversationId}`);
    } catch (error) {
      console.error(`删除对话失败 (ID: ${conversationId}):`, error);
    }
  },

  async sendMessageStream(
    message: string,
    conversationId?: string,
    onChunk?: (chunk: string) => void,
    history: Array<{ role: string; content: string }> = [],
    followUpContext?: FollowUpContext
  ): Promise<ChatResponse> {
    try {
      void onChunk;
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

  async quickChat(message: string): Promise<{ answer: string; references: DocumentResult[] }> {
    const response = await this.sendMessage(message, undefined, [], undefined, undefined);
    return {
      answer: response.message,
      references: response.references || [],
    };
  },
};
