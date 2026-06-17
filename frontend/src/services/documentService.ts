import { apiDelete, apiGet, apiGetBlob, apiPatch, apiPost, apiPostForm } from '../lib/api/contractClient';
import type { components } from '../lib/api/generated/schema';

export type DocumentDetail = components['schemas']['DocumentDetailResponse'];
type UploadResponse = components['schemas']['UploadResponse'];
type DocumentBatchRequest = components['schemas']['DocumentBatchRequest'];
type DocumentListResponse = { documents?: DocumentDetail[]; total?: number };

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

const headerToString = (value: unknown): string | undefined => {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) return value.find((item): item is string => typeof item === 'string');
  return undefined;
};

export const documentService = {
  async getDocumentById(id: string): Promise<DocumentDetail | null> {
    try {
      return await apiGet('/api/documents/{doc_id}', {
        params: { path: { doc_id: id } },
      });
    } catch (error) {
      console.error(`Failed to fetch document detail (ID: ${id}):`, error);
      return null;
    }
  },

  async getDocumentList(
    page: number = 1,
    pageSize: number = 20,
    filters?: Record<string, unknown>
  ): Promise<{ documents: DocumentDetail[]; total: number }> {
    try {
      const response = await apiGet('/api/documents/list', {
        params: {
          query: { page, page_size: pageSize, ...(filters ?? {}) },
        },
      }) as DocumentListResponse;
      return {
        documents: response.documents || [],
        total: response.total || 0,
      };
    } catch (error) {
      console.error('Failed to fetch document list:', error);
      return { documents: [], total: 0 };
    }
  },

  async uploadDocument(file: File, metadata?: Record<string, unknown>): Promise<string> {
    try {
      const formData = new FormData();
      formData.append('file', file);
      if (metadata) {
        formData.append('metadata', JSON.stringify(metadata));
      }

      const response: UploadResponse = await apiPostForm('/api/documents/upload', formData);
      return response.document_id;
    } catch (error) {
      console.error('Failed to upload document:', error);
      throw error;
    }
  },

  async deleteDocument(id: string): Promise<void> {
    try {
      await apiDelete('/api/documents/{doc_id}', {
        params: { path: { doc_id: id } },
      });
    } catch (error) {
      console.error(`Failed to delete document (ID: ${id}):`, error);
      throw error;
    }
  },

  async updateDocumentMetadata(id: string, metadata: Record<string, unknown>): Promise<void> {
    try {
      await apiPatch('/api/documents/{doc_id}', { metadata }, {
        params: { path: { doc_id: id } },
      });
    } catch (error) {
      console.error(`Failed to update document metadata (ID: ${id}):`, error);
      throw error;
    }
  },

  async downloadDocument(id: string): Promise<DownloadedDocument> {
    try {
      const response = await apiGetBlob('/api/documents/{doc_id}/download', {
        params: { path: { doc_id: id } },
      });
      const filename = extractFilename(headerToString(response.headers['content-disposition']));
      const contentType = headerToString(response.headers['content-type']);
      return {
        blob: response.blob,
        filename,
        contentType: contentType || null,
      };
    } catch (error) {
      console.error(`Failed to download document (ID: ${id}):`, error);
      throw error;
    }
  },

  async batchOperation(operation: DocumentBatchRequest['operation'], documentIds: string[]): Promise<void> {
    try {
      await apiPost('/api/documents/batch', {
        operation,
        document_ids: documentIds,
      });
    } catch (error) {
      console.error(`Failed to run batch operation (${operation}):`, error);
      throw error;
    }
  },
};
