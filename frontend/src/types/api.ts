// GeoAI API 类型定义
// 基于后端 Pydantic 模型生成

// 空间过滤器
export interface SpatialFilter {
  geometry?: Record<string, any>; // GeoJSON 几何对象
  distance?: number; // 距离（米）
  spatial_relation: 'within' | 'intersects' | 'near'; // 空间关系
}

// 元数据过滤器
export interface MetadataFilter {
  document_type?: string;
  source?: string;
  year?: number;
  region?: string;
  keywords?: string[];
  custom_filters?: Record<string, any>;
}

// 文档检索结果
export interface DocumentResult {
  id: string; // 文档ID
  title: string; // 文档标题
  content: string; // 文档内容摘要
  similarity: number; // 相似度分数 (0-1)
  metadata: Record<string, any>; // 文档元数据
  spatial_info?: Record<string, any>; // 空间信息
  file_type: string; // 文件类型
  file_size: number; // 文件大小（字节）
  upload_time: string; // 上传时间 (ISO字符串)
  source_url?: string; // 源URL
}

// 检索请求
export interface SearchRequest {
  query: string; // 检索查询语句
  top_k?: number; // 返回结果数量
  threshold?: number; // 相似度阈值
  spatial_filter?: SpatialFilter; // 空间过滤器
  metadata_filter?: MetadataFilter; // 元数据过滤器
  use_rerank?: boolean; // 是否使用重排序
  search_mode?: 'semantic' | 'keyword' | 'hybrid'; // 检索模式
  use_generation?: boolean; // 是否使用大模型生成答案
  history?: Array<{ role: string; content: string }>; // 历史对话记录
}

// 检索响应
export interface SearchResponse {
  query: string; // 原始查询
  results: DocumentResult[]; // 检索结果
  total_count: number; // 总结果数量
  search_time: number; // 检索耗时（秒）
  search_mode: string; // 使用的检索模式
  suggestions?: string[]; // 搜索建议
  generated_answer?: string; // 大模型生成的答案
  generation_time?: number; // 生成耗时（秒）
}

// 搜索历史记录
export interface SearchHistory {
  id: string; // 记录ID
  query: string; // 查询语句
  results_count: number; // 结果数量
  search_time: string; // 搜索时间 (ISO字符串)
  user_id?: string; // 用户ID
  session_id?: string; // 会话ID
}

// 搜索统计
export interface SearchStatistic {
  total_searches: number; // 总搜索次数
  average_results: number; // 平均结果数量
  popular_queries: Array<Record<string, any>>; // 热门查询
  search_trends: Record<string, number>; // 搜索趋势
}

// 搜索反馈请求
export interface FeedbackRequest {
  query: string; // 查询语句
  result_id: string; // 结果ID
  feedback_type: 'relevant' | 'irrelevant' | 'helpful' | 'not_helpful'; // 反馈类型
  comment?: string; // 反馈评论
  rating?: number; // 评分（1-5）
}

// 聊天消息
export interface ChatMessage {
  role: 'user' | 'assistant' | 'system';
  content: string;
  references?: DocumentResult[]; // 引用的文档
  timestamp?: string;
}

// 聊天请求
export interface ChatRequest {
  message: string;
  conversation_id?: string;
  use_context?: boolean;
  max_tokens?: number;
}

// 聊天响应
export interface ChatResponse {
  message: string;
  conversation_id: string;
  references?: DocumentResult[];
  timestamp: string;
}

// 文档详情
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
  };
  standard_info?: {
    code: string;
    release_date?: string;
    implement_date?: string;
    draft_unit?: string;
    keyword?: string;
    status?: string;
  };
}