export interface AgentEventPayload {
  tool_name?: string;
  tool_call_id?: string;
  arguments?: Record<string, unknown>;
  status?: string;
  error?: string | { code?: string; message?: string; [key: string]: unknown };
  result_summary?: Record<string, unknown>;
  receipt?: Record<string, unknown>;
  snapshot_id?: string;
  evidence_ids?: string[];
  kind?: string;
  state?: string;
  verdict?: string;
  question?: string;
  text?: string;
  decision_summary?: string;
  [key: string]: unknown;
}

export interface AgentEventMessage {
  event_type: string;
  session_id: string;
  turn_id: string;
  trace_id?: string;
  event_id?: string;
  sequence?: number;
  payload: AgentEventPayload;
  created_at?: string;
}

export interface AgentToolItem {
  kind: 'tool';
  callId: string;
  toolName: string;
  status: 'running' | 'waiting_browser' | 'succeeded' | 'failed' | 'cancelled';
  arguments?: Record<string, unknown>;
  output?: Record<string, unknown>;
  error?: string;
  executionSite?: 'backend' | 'browser';
  browserReceipt?: {
    status: string;
    effectStatus?: string;
    runtimeDimension?: '2d' | '3d';
    stateRevision?: number;
  };
  startedAt?: string;
  completedAt?: string;
}

export interface AgentDecisionItem {
  kind: 'decision';
  toolName?: string;
  action?: string;
  summary: string;
  timestamp: string;
}

export interface AgentEvidenceItem {
  kind: 'evidence_frozen';
  snapshotId: string;
  evidenceCount: number;
  evidenceIds: string[];
  timestamp: string;
}

export interface AgentStageItem {
  kind: 'stage';
  stageName: string;
  summary: string;
  status: 'running' | 'completed' | 'failed';
  timestamp: string;
}

export interface AgentReviewItem {
  kind: 'review';
  verdict?: string;
  status?: 'running' | 'completed' | 'failed';
  reviewId?: string;
  attempt?: number;
  findingCount?: number;
  summary: string;
  timestamp: string;
}

export interface AgentPublicationItem {
  kind: 'publication';
  state: string;
  summary: string;
  timestamp: string;
}

export type AgentProcessItem =
  | AgentDecisionItem
  | AgentToolItem
  | AgentEvidenceItem
  | AgentStageItem
  | AgentReviewItem
  | AgentPublicationItem;

export interface AgentTurnViewModel {
  sessionId: string;
  turnId: string;
  traceId?: string;
  status: 'running' | 'published' | 'clarification' | 'limited' | 'failed' | 'cancelled';
  items: AgentProcessItem[];
  startedAt?: string;
  completedAt?: string;
  interruption?: { kind: 'stopped' | 'connection_error'; message: string };
}
