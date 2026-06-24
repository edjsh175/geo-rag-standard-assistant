import { apiGet, apiPost } from '../lib/api/contractClient';
import type { components } from '../lib/api/generated/schema';

export type SearchRequest = components['schemas']['SearchRequest'];
export type SearchResponse = components['schemas']['SearchResponse'];
export type DocumentResult = components['schemas']['DocumentResult'];
export type FeedbackRequest = components['schemas']['FeedbackRequest'];

/**
 * 搜索服务
 */
export const searchService = {
  /**
   * 智能检索文档
   */
  async search(request: SearchRequest): Promise<SearchResponse> {
    try {
      return await apiPost('/api/search/query', request);
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
      return await apiPost('/api/search/hybrid', undefined, {
        params: {
          query: {
            query: textQuery,
            spatial_query: spatialQuery,
            top_k: topK,
          },
        },
      });
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
      const response = await apiGet('/api/search/suggest', {
        params: {
          query: { prefix, limit },
        },
      }) as { suggestions?: string[] };
      return response.suggestions || [];
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
      const response = await apiGet('/api/search/similar/{doc_id}', {
        params: {
          path: { doc_id: docId },
          query: { top_k: topK },
        },
      }) as { similar_documents?: DocumentResult[] };
      return response.similar_documents || [];
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
      await apiPost('/api/search/feedback', feedback);
    } catch (error) {
      console.error('提交反馈失败:', error);
      // 静默失败，不影响用户体验
    }
  },

  /**
   * 获取搜索历史
   */
  async getSearchHistory(limit: number = 20): Promise<unknown[]> {
    try {
      void limit;
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
