/**
 * GeoAI前端类型定义
 * 对应后端Pydantic模型
 */

// 文档元数据
export interface DocumentMetadata {
  title: string;
  author?: string;
  description?: string;
  keywords: string[];
  publish_date?: string | Date;
  source?: string;
  language: string;
  category?: string;
  tags: string[];
  custom_fields: Record<string, any>;
}

// 空间元数据
export interface SpatialMetadata {
  geometry?: Record<string, any>; // GeoJSON几何对象
  bounding_box?: [number, number, number, number]; // [min_lon, min_lat, max_lon, max_lat]
  address?: string;
  city?: string;
  province?: string;
  country?: string;
  coordinate_system: string;
}

// 文档模型
export interface Document {
  id: string;
  filename: string;
  file_type: string;
  file_size: number;
  content_hash: string;
  upload_time: string | Date;
  last_modified: string | Date;
  metadata: DocumentMetadata;
  spatial_metadata?: SpatialMetadata;
  vector_embedding?: number[];
  is_indexed: boolean;
  indexing_status: 'pending' | 'processing' | 'completed' | 'failed';
  storage_path: string;
  access_url?: string;
  version: number;
}

// 文档预览
export interface DocumentPreview {
  id: string;
  title: string;
  file_type: string;
  size: string;
  upload_time: string;
  indexing_status: string;
  preview_content?: string;
  thumbnail_url?: string;
}

// 文档统计
export interface DocumentStatistics {
  total_documents: number;
  total_size: number;
  indexed_count: number;
  failed_count: number;
  by_file_type: Record<string, number>;
  by_category: Record<string, number>;
  by_date: Record<string, number>;
}

// 搜索请求
export interface SearchRequest {
  query: string;
  search_type?: 'semantic' | 'keyword' | 'hybrid';
  filters?: {
    file_type?: string[];
    category?: string[];
    date_range?: {
      start?: string;
      end?: string;
    };
    min_score?: number;
  };
  spatial_filter?: {
    geometry: Record<string, any>; // GeoJSON几何对象
    distance?: number;
    spatial_relation?: 'intersects' | 'within' | 'contains' | 'near' | 'overlaps' | 'disjoint';
  };
  limit?: number;
  offset?: number;
  sort_by?: 'relevance' | 'date' | 'title';
  sort_order?: 'asc' | 'desc';
  include_vector?: boolean;
  include_highlight?: boolean;
}

// 搜索响应
export interface SearchResponse {
  results: SearchResult[];
  total: number;
  took: number;
  query?: string;
  filters?: Record<string, any>;
  suggestions?: string[];
}

// 搜索结果
export interface SearchResult {
  id: string;
  score: number;
  document: Document;
  highlights?: Record<string, string[]>;
  explanation?: string;
  vector_distance?: number;
}

// 聊天消息
export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string | Date;
  metadata?: {
    document_ids?: string[];
    citations?: Citation[];
    search_query?: string;
  };
}

// 聊天请求
export interface ChatRequest {
  message: string;
  conversation_id?: string;
  search_context?: boolean;
  include_documents?: boolean;
  spatial_context?: {
    location?: [number, number]; // [经度, 纬度]
    radius?: number;
  };
  model?: string;
  temperature?: number;
  max_tokens?: number;
}

// 聊天响应
export interface ChatResponse {
  message: string;
  conversation_id: string;
  response_id: string;
  timestamp: string | Date;
  citations: Citation[];
  documents: Document[];
  search_query?: string;
  metadata?: Record<string, any>;
}

// 引用
export interface Citation {
  document_id: string;
  title: string;
  excerpt: string;
  page_number?: number;
  confidence: number;
}

// 系统状态
export interface SystemStatus {
  status: 'healthy' | 'degraded' | 'unhealthy';
  version: string;
  uptime: number;
  database: {
    postgresql: boolean;
    mysql: boolean;
    redis: boolean;
  };
  services: {
    search: boolean;
    vector: boolean;
    chat: boolean;
    spatial: boolean;
  };
  metrics: {
    active_connections: number;
    memory_usage: number;
    cpu_usage: number;
  };
}

// 空间几何类型
export interface Point {
  type: 'Point';
  coordinates: [number, number]; // [经度, 纬度]
}

export interface LineString {
  type: 'LineString';
  coordinates: [number, number][]; // [[经度, 纬度], ...]
}

export interface Polygon {
  type: 'Polygon';
  coordinates: [number, number][][]; // [[[经度, 纬度], ...], ...]
}

export interface Feature {
  type: 'Feature';
  geometry: Point | LineString | Polygon;
  properties: Record<string, any>;
}

export interface FeatureCollection {
  type: 'FeatureCollection';
  features: Feature[];
}

// 边界框
export interface BoundingBox {
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
}

// 空间查询
export interface SpatialQuery {
  geometry: Record<string, any>; // GeoJSON几何对象
  distance?: number;
  spatial_relation: 'intersects' | 'within' | 'contains' | 'near' | 'overlaps' | 'disjoint';
  buffer_distance?: number;
}

// 地理编码响应
export interface GeocodeResponse {
  address: string;
  coordinates: [number, number]; // [经度, 纬度]
  formatted_address: string;
  city?: string;
  district?: string;
  country?: string;
  confidence: number;
}

// 空间分析响应
export interface SpatialAnalysisResponse {
  analysis_type: string;
  result_geometry?: Record<string, any>;
  distance?: number;
  area?: number;
  is_valid: boolean;
}

// API错误响应
export interface ApiError {
  message: string;
  code: string;
  details?: Record<string, any>;
  timestamp: string;
}

// 分页参数
export interface PaginationParams {
  page?: number;
  page_size?: number;
  limit?: number;
  offset?: number;
}

// 分页响应
export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  has_next: boolean;
  has_previous: boolean;
}