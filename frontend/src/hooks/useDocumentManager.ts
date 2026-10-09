import { useState, useCallback } from 'react';
import type { Document, SearchResult } from '../types';
import { searchService, type DocumentResult as ApiDocumentResult } from '../services/searchService';
import { documentService } from '../services/documentService';

type ApiDocumentDetail = NonNullable<Awaited<ReturnType<typeof documentService.getDocumentById>>>;

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};

const asString = (value: unknown): string | undefined =>
  typeof value === 'string' ? value : undefined;

const asStringArray = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];

const asBoundingBox = (value: unknown): [number, number, number, number] | undefined =>
  Array.isArray(value) &&
  value.length === 4 &&
  value.every((item) => typeof item === 'number')
    ? [value[0], value[1], value[2], value[3]]
    : undefined;

export const toSpatialMetadata = (value: unknown): Document['spatial_metadata'] => {
  const spatial = asRecord(value);
  if (Object.keys(spatial).length === 0) return undefined;
  return {
    geometry: asRecord(spatial.geometry),
    bounding_box: asBoundingBox(spatial.bounding_box),
    address: asString(spatial.address),
    city: asString(spatial.city),
    province: asString(spatial.province),
    country: asString(spatial.country),
    coordinate_system: 'EPSG:4326',
  };
};

export const metadataToDocumentMetadata = (
  title: string,
  description: string,
  metadataValue: unknown
): Document['metadata'] => {
  const metadata = asRecord(metadataValue);
  return {
    title,
    author: asString(metadata.author),
    description,
    keywords: asStringArray(metadata.keywords),
    publish_date: asString(metadata.publish_date),
    source: asString(metadata.source),
    language: 'zh',
    category: asString(metadata.category),
    tags: asStringArray(metadata.tags),
    custom_fields: asRecord(metadata.custom_fields),
  };
};

export const normalizeIndexingStatus = (
  value: unknown,
  fallback: Document['indexing_status'] = 'completed'
): Document['indexing_status'] => {
  const status = asString(value);
  const supported: Document['indexing_status'][] = [
    'pending',
    'processing',
    'completed',
    'queued',
    'parsing',
    'chunking',
    'embedding',
    'indexed',
    'failed',
    'deleted',
  ];
  return supported.includes(status as Document['indexing_status'])
    ? (status as Document['indexing_status'])
    : fallback;
};

export const isIndexedStatus = (status: Document['indexing_status']): boolean =>
  status === 'completed' || status === 'indexed';

export const indexingStatusLabel = (status: Document['indexing_status']): string => {
  const labels: Record<Document['indexing_status'], string> = {
    pending: '待处理',
    processing: '处理中',
    completed: '已完成',
    queued: '排队中',
    parsing: '解析中',
    chunking: '切分中',
    embedding: '向量化',
    indexed: '已完成',
    failed: '失败',
    deleted: '已删除',
  };
  return labels[status] ?? '待处理';
};

export const toFrontendDocumentFromResult = (doc: ApiDocumentResult): Document => ({
  id: doc.id,
  filename: doc.title,
  file_type: doc.file_type,
  file_size: doc.file_size,
  content_hash: '',
  upload_time: doc.upload_time,
  last_modified: doc.upload_time,
  metadata: metadataToDocumentMetadata(doc.title, doc.content, doc.metadata),
  spatial_metadata: toSpatialMetadata(doc.spatial_info),
  vector_embedding: undefined,
  is_indexed: true,
  indexing_status: 'completed',
  storage_path: '',
  access_url: doc.source_url,
  download_available: doc.download_available,
  download_url: doc.download_url,
  version: 1,
});

export const toFrontendDocumentFromDetail = (documentDetail: ApiDocumentDetail): Document => ({
  id: documentDetail.id,
  filename: documentDetail.title,
  file_type: documentDetail.file_info.type,
  file_size: documentDetail.file_info.size,
  content_hash: '',
  upload_time: documentDetail.file_info.upload_time,
  last_modified: documentDetail.file_info.upload_time,
  metadata: metadataToDocumentMetadata(documentDetail.title, documentDetail.content, documentDetail.metadata),
  spatial_metadata: toSpatialMetadata(documentDetail.spatial_info),
  vector_embedding: undefined,
  is_indexed: isIndexedStatus(
    normalizeIndexingStatus(asRecord(asRecord(documentDetail.metadata).custom_fields).index_status)
  ),
  indexing_status: normalizeIndexingStatus(asRecord(asRecord(documentDetail.metadata).custom_fields).index_status),
  storage_path: '',
  access_url: documentDetail.download_url,
  download_available: documentDetail.download_available,
  download_url: documentDetail.download_url,
  version: 1,
});

export function useDocumentManager() {
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const [selectedDocument, setSelectedDocument] = useState<Document | null>(null);
  const [isLoadingDocument, setIsLoadingDocument] = useState(false);
  const [isDownloadingDocument, setIsDownloadingDocument] = useState(false);
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  const [selectedStandard, setSelectedStandard] = useState<any>(null);

  const handleReferenceClick = useCallback((doc: Document) => {
    setSelectedDocument(doc);
    setIsDrawerOpen(true);
  }, []);

  const fetchDocumentDetails = useCallback(async (documentId: string): Promise<Document | null> => {
    if (!documentId) return null;
    setIsLoadingDocument(true);
    try {
      const documentDetail = await documentService.getDocumentById(documentId);
      if (!documentDetail) return null;
      return toFrontendDocumentFromDetail(documentDetail);
    } catch (error) {
      console.error('获取文档详情失败:', error);
      return null;
    } finally {
      setIsLoadingDocument(false);
    }
  }, []);

  const handleCitationClick = useCallback(async (documentId: string) => {
    const doc = await fetchDocumentDetails(documentId);
    if (doc) {
      handleReferenceClick(doc);
    }
  }, [fetchDocumentDetails, handleReferenceClick]);

  const handleDocumentDownload = useCallback(async () => {
    if (!selectedDocument?.id || !selectedDocument.download_available || isDownloadingDocument) {
      return;
    }

    setIsDownloadingDocument(true);
    try {
      const { blob, filename } = await documentService.downloadDocument(selectedDocument.id);
      const objectUrl = window.URL.createObjectURL(blob);
      const link = window.document.createElement('a');
      link.href = objectUrl;
      link.download =
        filename ||
        selectedDocument.filename ||
        `${selectedDocument.id}.${selectedDocument.file_type || 'pdf'}`;
      window.document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(objectUrl);
    } catch (error) {
      console.error('文档下载失败:', error);
    } finally {
      setIsDownloadingDocument(false);
    }
  }, [selectedDocument, isDownloadingDocument]);

  const handleSearch = useCallback(async (query: string): Promise<SearchResult[]> => {
    if (!query.trim()) return [];
    setIsSearching(true);
    try {
      const documentResults = await searchService.quickSearch(query);
      const results: SearchResult[] = documentResults.map((doc) => ({
        id: doc.id,
        score: doc.similarity,
        document: toFrontendDocumentFromResult(doc),
        highlights: {},
        explanation: `相似度: ${(doc.similarity * 100).toFixed(1)}%`,
        vector_distance: 1 - doc.similarity,
      }));
      setSearchResults(results);
      return results;
    } catch (error) {
      console.error('搜索失败:', error);
      return [];
    } finally {
      setIsSearching(false);
    }
  }, []);

  return {
    searchQuery,
    setSearchQuery,
    searchResults,
    setSearchResults,
    isSearching,
    selectedDocument,
    setSelectedDocument,
    isLoadingDocument,
    isDownloadingDocument,
    isDrawerOpen,
    setIsDrawerOpen,
    selectedStandard,
    setSelectedStandard,
    handleReferenceClick,
    fetchDocumentDetails,
    handleCitationClick,
    handleDocumentDownload,
    handleSearch,
  };
}
