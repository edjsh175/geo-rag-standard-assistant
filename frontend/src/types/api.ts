export interface SpatialFilter {
  geometry?: Record<string, any>;
  distance?: number;
  spatial_relation?: 'within' | 'intersects' | 'near';
}

export interface MetadataFilter {
  document_type?: string;
  source?: string;
  year?: number;
  region?: string;
  keywords?: string[];
  custom_filters?: Record<string, any>;
}

export interface DocumentResult {
  id: string;
  title: string;
  content: string;
  similarity: number;
  metadata: Record<string, any>;
  spatial_info?: Record<string, any>;
  file_type: string;
  file_size: number;
  upload_time: string;
  source_url?: string;
  download_available?: boolean;
  download_url?: string;
}

export interface FollowUpCandidateDocument {
  id: string;
  title: string;
  rank: number;
}

export interface FollowUpContext {
  target_document_id?: string;
  candidate_documents?: FollowUpCandidateDocument[];
  resolution_source?: 'explicit_text' | 'ordinal' | 'selected_document';
}

export interface SearchRequest {
  query: string;
  top_k?: number;
  threshold?: number;
  spatial_filter?: SpatialFilter;
  metadata_filter?: MetadataFilter;
  use_rerank?: boolean;
  search_mode?: 'semantic' | 'keyword' | 'hybrid';
  use_generation?: boolean;
  history?: Array<{ role: string; content: string }>;
  follow_up_context?: FollowUpContext;
}

export interface SearchResponse {
  query: string;
  results: DocumentResult[];
  total_count: number;
  search_time: number;
  search_mode: string;
  suggestions?: string[];
  generated_answer?: string;
  generation_time?: number;
}

export interface SearchHistory {
  id: string;
  query: string;
  results_count: number;
  search_time: string;
  user_id?: string;
  session_id?: string;
}

export interface SearchStatistic {
  total_searches: number;
  average_results: number;
  popular_queries: Array<Record<string, any>>;
  search_trends: Record<string, number>;
}

export interface FeedbackRequest {
  query: string;
  result_id: string;
  feedback_type: 'relevant' | 'irrelevant' | 'helpful' | 'not_helpful';
  comment?: string;
  rating?: number;
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
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
}

export interface DocumentDetail {
  id: string;
  title: string;
  content: string;
  metadata: Record<string, any>;
  spatial_info?: Record<string, any>;
  file_info: {
    type: string;
    size: number;
    upload_time: string;
    filename?: string;
    mime_type?: string;
  };
  standard_info?: {
    code: string;
    release_date?: string;
    implement_date?: string;
    draft_unit?: string;
    keyword?: string;
    status?: string;
  };
  download_available?: boolean;
  download_url?: string;
}
