import { apiClient } from '../lib/api/config';
import type { DocumentDetail } from '../types/api';

export interface DownloadedDocument {
  blob: Blob;
  filename: string;
  contentType: string | null;
}

const extractFilename = (contentDisposition?: string): string => {
  if (!contentDisposition) return 'document';

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }

  const simpleMatch = contentDisposition.match(/filename="([^"]+)"/i);
  if (simpleMatch?.[1]) {
    return simpleMatch[1];
  }

  return 'document';
};

export const documentService = {
  async getDocumentById(id: string): Promise<DocumentDetail | null> {
    try {
      const response = await apiClient.get<DocumentDetail>(`/documents/${id}`);
      return response.data;
    } catch (error) {
      console.error(`Failed to fetch document detail (ID: ${id}):`, error);
      return null;
    }
  },

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
      console.error('Failed to fetch document list:', error);
      return { documents: [], total: 0 };
    }
  },

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
      console.error('Failed to upload document:', error);
      throw error;
    }
  },

  async deleteDocument(id: string): Promise<void> {
    try {
      await apiClient.delete(`/documents/${id}`);
    } catch (error) {
      console.error(`Failed to delete document (ID: ${id}):`, error);
      throw error;
    }
  },

  async updateDocumentMetadata(id: string, metadata: Record<string, any>): Promise<void> {
    try {
      await apiClient.patch(`/documents/${id}`, { metadata });
    } catch (error) {
      console.error(`Failed to update document metadata (ID: ${id}):`, error);
      throw error;
    }
  },

  async downloadDocument(id: string): Promise<DownloadedDocument> {
    try {
      const response = await apiClient.get<Blob>(`/documents/${id}/download`, {
        responseType: 'blob',
      });
      const filename = extractFilename(response.headers['content-disposition']);
      return {
        blob: response.data,
        filename,
        contentType: response.headers['content-type'] || null,
      };
    } catch (error) {
      console.error(`Failed to download document (ID: ${id}):`, error);
      throw error;
    }
  },

  async batchOperation(operation: string, documentIds: string[]): Promise<void> {
    try {
      await apiClient.post('/documents/batch', {
        operation,
        document_ids: documentIds,
      });
    } catch (error) {
      console.error(`Failed to run batch operation (${operation}):`, error);
      throw error;
    }
  },
};

