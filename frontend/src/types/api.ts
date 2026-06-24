import type { components } from '../lib/api/generated/schema';

export type SpatialFilter = components['schemas']['SpatialFilter'];
export type MetadataFilter = components['schemas']['MetadataFilter'];
export type DocumentResult = components['schemas']['DocumentResult'];
export type FollowUpCandidateDocument = components['schemas']['FollowUpCandidateDocument'];
export type FollowUpContext = components['schemas']['FollowUpContext'];
export type ChatHistoryMessage = components['schemas']['ChatHistoryMessage'];
export type SearchRequest = components['schemas']['SearchRequest'];
export type DemoQuotaStatus = components['schemas']['DemoQuotaStatus'];
export type SearchResponse = components['schemas']['SearchResponse'];
export type FeedbackRequest = components['schemas']['FeedbackRequest'];
export type FeedbackResponse = components['schemas']['FeedbackResponse'];
export type DocumentDetail = components['schemas']['DocumentDetailResponse'];
export type DocumentUpdateRequest = components['schemas']['DocumentUpdateRequest'];
export type DocumentBatchRequest = components['schemas']['DocumentBatchRequest'];
export type DocumentBatchResponse = components['schemas']['DocumentBatchResponse'];

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
  popular_queries: Array<Record<string, unknown>>;
  search_trends: Record<string, number>;
}

export interface ChatMessage {
  role: 'user' | 'assistant';
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
  quota?: DemoQuotaStatus;
}
