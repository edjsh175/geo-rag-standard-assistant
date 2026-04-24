import { apiClient } from '../lib/api/config';
import type {
  SearchRequest,
  SearchResponse,
  DocumentResult,
  FeedbackRequest,
} from '../types/api';

/**
 * 搜索服务
 */
export const searchService = {
  /**
   * 智能检索文档
   */
  async search(request: SearchRequest): Promise<SearchResponse> {
    try {
      const response = await apiClient.post<SearchResponse>('/search/query', request);
      return response.data;
    } catch (error) {
      console.error('搜索失败:', error);
      throw error;
    }
  },

  /**
   * 混合检索（文本 + 空间）
   */
  async hybridSearch(
    textQuery: string,
    spatialQuery?: string,
    topK: number = 10
  ): Promise<SearchResponse> {
    try {
      const params = {
        query: textQuery,
        spatial_query: spatialQuery,
        top_k: topK,
      };
      const response = await apiClient.post<SearchResponse>('/search/hybrid', null, { params });
      return response.data;
    } catch (error) {
      console.error('混合检索失败:', error);
      throw error;
    }
  },

  /**
   * 获取搜索建议
   */
  async getSuggestions(prefix: string, limit: number = 5): Promise<string[]> {
    try {
      const params = { prefix, limit };
      const response = await apiClient.get<{ suggestions: string[] }>('/search/suggest', { params });
      return response.data.suggestions || [];
    } catch (error) {
      console.error('获取搜索建议失败:', error);
      return [];
    }
  },

  /**
   * 查找相似文档
   */
  async findSimilarDocuments(docId: string, topK: number = 5): Promise<DocumentResult[]> {
    try {
      const params = { top_k: topK };
      const response = await apiClient.get<{ similar_documents: DocumentResult[] }>(
        `/search/similar/${docId}`,
        { params }
      );
      return response.data.similar_documents || [];
    } catch (error) {
      console.error('查找相似文档失败:', error);
      return [];
    }
  },

  /**
   * 提交搜索反馈
   */
  async submitFeedback(feedback: FeedbackRequest): Promise<void> {
    try {
      await apiClient.post('/search/feedback', feedback);
    } catch (error) {
      console.error('提交反馈失败:', error);
      // 静默失败，不影响用户体验
    }
  },

  /**
   * 获取搜索历史
   */
  async getSearchHistory(limit: number = 20): Promise<any[]> {
    try {
      // TODO: 后端需要实现搜索历史端点
      return [];
    } catch (error) {
      console.error('获取搜索历史失败:', error);
      return [];
    }
  },

  /**
   * 简单搜索（快捷方法）
   */
  async quickSearch(query: string, topK: number = 10): Promise<DocumentResult[]> {
    try {
      const request: SearchRequest = {
        query,
        top_k: topK,
        use_generation: false,
      };
      const response = await this.search(request);
      return response.results;
    } catch (error) {
      console.error('快速搜索失败:', error);
      return [];
    }
  },
};
