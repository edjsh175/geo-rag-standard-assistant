import { apiClient } from '../lib/api/config';
import type { DocumentDetail } from '../types/api';

/**
 * 文档服务
 */
export const documentService = {
  /**
   * 获取文档详情
   */
  async getDocumentById(id: string): Promise<DocumentDetail | null> {
    try {
      const response = await apiClient.get<DocumentDetail>(`/documents/${id}`);
      return response.data;
    } catch (error) {
      console.error(`获取文档详情失败 (ID: ${id}):`, error);
      return null;
    }
  },

  /**
   * 获取文档列表
   */
  async getDocumentList(
    page: number = 1,
    pageSize: number = 20,
    filters?: Record<string, any>
  ): Promise<{ documents: DocumentDetail[]; total: number }> {
    try {
      const params = { page, page_size: pageSize, ...filters };
      const response = await apiClient.get<{ documents: DocumentDetail[]; total: number }>(
        '/documents/list',
        { params }
      );
      return response.data;
    } catch (error) {
      console.error('获取文档列表失败:', error);
      return { documents: [], total: 0 };
    }
  },

  /**
   * 上传文档
   */
  async uploadDocument(file: File, metadata?: Record<string, any>): Promise<string> {
    try {
      const formData = new FormData();
      formData.append('file', file);
      if (metadata) {
        formData.append('metadata', JSON.stringify(metadata));
      }

      const response = await apiClient.post<{ document_id: string }>(
        '/documents/upload',
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data',
          },
        }
      );
      return response.data.document_id;
    } catch (error) {
      console.error('上传文档失败:', error);
      throw error;
    }
  },

  /**
   * 删除文档
   */
  async deleteDocument(id: string): Promise<void> {
    try {
      await apiClient.delete(`/documents/${id}`);
    } catch (error) {
      console.error(`删除文档失败 (ID: ${id}):`, error);
      throw error;
    }
  },

  /**
   * 更新文档元数据
   */
  async updateDocumentMetadata(id: string, metadata: Record<string, any>): Promise<void> {
    try {
      await apiClient.patch(`/documents/${id}`, { metadata });
    } catch (error) {
      console.error(`更新文档元数据失败 (ID: ${id}):`, error);
      throw error;
    }
  },

  /**
   * 下载文档
   */
  async downloadDocument(id: string): Promise<Blob> {
    try {
      const response = await apiClient.get<Blob>(`/documents/${id}/download`, {
        responseType: 'blob',
      });
      return response.data;
    } catch (error) {
      console.error(`下载文档失败 (ID: ${id}):`, error);
      throw error;
    }
  },

  /**
   * 批量操作
   */
  async batchOperation(operation: string, documentIds: string[]): Promise<void> {
    try {
      await apiClient.post('/documents/batch', {
        operation,
        document_ids: documentIds,
      });
    } catch (error) {
      console.error(`批量操作失败 (${operation}):`, error);
      throw error;
    }
  },
};
