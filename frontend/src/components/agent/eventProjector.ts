import { AgentEventMessage, AgentProcessItem, AgentPublicationItem, AgentToolItem, AgentTurnViewModel } from './types';

const terminalTool = (status: AgentToolItem['status']) =>
  status === 'succeeded' || status === 'failed' || status === 'cancelled';

const errorMessage = (error: unknown): string | undefined => {
  if (typeof error === 'string') return error;
  if (error && typeof error === 'object') {
    const value = error as { message?: unknown; code?: unknown };
    if (typeof value.message === 'string') return value.code ? `${String(value.code)}: ${value.message}` : value.message;
    return JSON.stringify(error);
  }
  return undefined;
};

export class AgentEventProjector {
  private turn: AgentTurnViewModel;
  private seenEvents = new Set<string>();
  private toolsByCallId = new Map<string, AgentToolItem>();
  private itemSequences = new WeakMap<object, number>();
  private itemOrders = new WeakMap<object, number>();
  private nextItemOrder = 0;
  private hasEvents = false;
  private publicationItem?: AgentPublicationItem;

  constructor(sessionId = '', turnId = '') {
    this.turn = { sessionId, turnId, status: 'running', items: [], startedAt: new Date().toISOString() };
  }

  getViewModel(): AgentTurnViewModel {
    return structuredClone(this.turn);
  }

  snapshot(): AgentTurnViewModel { return this.getViewModel(); }
  applyEvent(event: AgentEventMessage): AgentTurnViewModel { return this.ingest(event); }

  reset(sessionId = '', turnId = ''): void {
    this.seenEvents.clear();
    this.toolsByCallId.clear();
    this.itemSequences = new WeakMap();
    this.itemOrders = new WeakMap();
    this.nextItemOrder = 0;
    this.hasEvents = false;
    this.publicationItem = undefined;
    this.turn = { sessionId, turnId, status: 'running', items: [], startedAt: new Date().toISOString() };
  }

  private getTool(callId: string, name = 'tool', timestamp?: string): AgentToolItem {
    let tool = this.toolsByCallId.get(callId);
    if (!tool) {
      tool = { kind: 'tool', callId, toolName: name, status: 'running', executionSite: 'backend', startedAt: timestamp };
      this.toolsByCallId.set(callId, tool);
      this.append(tool);
    } else if (tool.toolName === 'tool' || tool.toolName === 'unknown_tool') tool.toolName = name;
    return tool;
  }

  private append(item: AgentProcessItem, sequence?: number): void {
    this.turn.items.push(item);
    this.itemOrders.set(item, this.nextItemOrder++);
    this.setSequence(item, sequence);
  }

  private setSequence(item: AgentProcessItem, sequence?: number): void {
    if (sequence === undefined) return;
    const previous = this.itemSequences.get(item);
    if (previous === undefined || sequence < previous) this.itemSequences.set(item, sequence);
    this.turn.items.sort((a, b) => {
      const aSeq = this.itemSequences.get(a);
      const bSeq = this.itemSequences.get(b);
      if (aSeq !== undefined && bSeq !== undefined) return aSeq - bSeq || (this.itemOrders.get(a) || 0) - (this.itemOrders.get(b) || 0);
      if (aSeq !== undefined) return -1;
      if (bSeq !== undefined) return 1;
      return (this.itemOrders.get(a) || 0) - (this.itemOrders.get(b) || 0);
    });
  }

  ingest(event: AgentEventMessage): AgentTurnViewModel {
    if (this.turn.sessionId && event.session_id !== this.turn.sessionId) return this.getViewModel();
    if (this.turn.turnId && event.turn_id !== this.turn.turnId) return this.getViewModel();
    if (!this.turn.sessionId && event.session_id) this.turn.sessionId = event.session_id;
    if (!this.turn.turnId && event.turn_id) this.turn.turnId = event.turn_id;

    const key = event.event_id ? `id:${event.event_id}` : event.sequence !== undefined ? `seq:${event.sequence}` : undefined;
    if (key && this.seenEvents.has(key)) return this.getViewModel();
    if (key) this.seenEvents.add(key);

    const payload = event.payload || {};
    const timestamp = event.created_at || new Date().toISOString();
    if (!this.hasEvents) { this.turn.startedAt = timestamp; this.hasEvents = true; }
    if (event.trace_id) this.turn.traceId = event.trace_id;

    switch (event.event_type) {
      case 'controller_decision': {
        const toolName = String(payload.tool_name || payload.tool || payload.action || '');
        const summary = payload.decision_summary || (toolName === 'compose_answer'
          ? '下一步：生成回答'
          : toolName === 'direct_answer' ? '决策：直接回答对话或交互指令'
          : toolName === 'clarify' ? '决策：实体或范围存在歧义，请求澄清'
          : `决策：规划执行工具 · ${toolName}`);
        this.append({ kind: 'decision', toolName, action: String(payload.action || ''), summary: String(summary), timestamp }, event.sequence);
        break;
      }
      case 'tool_started': {
        const callId = String(payload.tool_call_id || `unidentified-${timestamp}`);
        const tool = this.getTool(callId, String(payload.tool_name || 'unknown_tool'), timestamp);
        this.setSequence(tool, event.sequence);
        tool.arguments = payload.arguments as Record<string, unknown> | undefined;
        tool.startedAt ||= timestamp;
        if (!terminalTool(tool.status)) {
          tool.status = 'running';
        }
        break;
      }
      case 'tool_completed': {
        const callId = String(payload.tool_call_id || `unidentified-${timestamp}`);
        const tool = this.getTool(callId, String(payload.tool_name || 'tool'), timestamp);
        this.setSequence(tool, event.sequence);
        const status = String(payload.status || '').toLowerCase();
        // Browser dispatch is a handoff; its browser completion owns the terminal result.
        if (status === 'browser_execution_required' || status === 'waiting_browser') {
          tool.arguments ||= payload.arguments as Record<string, unknown> | undefined;
          if (payload.result_summary && !tool.output) tool.output = payload.result_summary as Record<string, unknown>;
          if (!terminalTool(tool.status)) { tool.status = 'waiting_browser'; tool.executionSite = 'browser'; }
        } else if (!terminalTool(tool.status)) {
          tool.status = ['ok', 'succeeded', 'partial'].includes(status) ? 'succeeded' : status === 'cancelled' ? 'cancelled' : 'failed';
          tool.output = (payload.result_summary || payload) as Record<string, unknown>;
          tool.error = errorMessage(payload.error);
          tool.completedAt = timestamp;
        }
        break;
      }
      case 'browser_tool_requested': {
        const callId = String(payload.tool_call_id || `unidentified-${timestamp}`);
        const tool = this.getTool(callId, String(payload.tool_name || 'browser_gis_tool'), timestamp);
        this.setSequence(tool, event.sequence);
        if (!terminalTool(tool.status)) {
          tool.status = 'waiting_browser'; tool.executionSite = 'browser';
          tool.arguments = payload.arguments as Record<string, unknown> | undefined;
          tool.startedAt ||= timestamp;
        }
        break;
      }
      case 'browser_tool_completed': {
        const callId = String(payload.tool_call_id || `unidentified-${timestamp}`);
        const tool = this.getTool(callId, String(payload.tool_name || 'browser_gis_tool'), timestamp);
        this.setSequence(tool, event.sequence);
        if (!terminalTool(tool.status)) {
          const receipt = (payload.receipt || {}) as Record<string, unknown>;
          const executionStatus = String(payload.status || receipt.status || '').toLowerCase();
          const ok = ['succeeded', 'success', 'ok'].includes(executionStatus);
          tool.status = ok ? 'succeeded' : 'failed';
          tool.executionSite = 'browser';
          tool.output = payload.result_summary as Record<string, unknown> | undefined;
          tool.error = errorMessage(payload.error) || (ok ? undefined : errorMessage(payload.reason));
          tool.browserReceipt = {
            status: String(payload.status || receipt.status || 'unknown'),
            effectStatus: typeof receipt.effect_status === 'string' ? receipt.effect_status : undefined,
            runtimeDimension: (receipt.map_dimension || receipt.runtime_dimension) as '2d' | '3d' | undefined,
            stateRevision: typeof receipt.state_revision === 'number' ? receipt.state_revision : undefined,
          };
          tool.completedAt = timestamp;
        }
        break;
      }
      case 'browser_tool_cancelled': {
        const callId = String(payload.tool_call_id || `unidentified-${timestamp}`);
        const tool = this.getTool(callId, String(payload.tool_name || 'browser_gis_tool'), timestamp);
        if (!terminalTool(tool.status)) {
          tool.status = 'cancelled'; tool.executionSite = 'browser'; tool.completedAt = timestamp;
          tool.error = errorMessage(payload.reason);
        }
        break;
      }
      case 'run_cancelled': {
        if (!this.publicationItem) { this.turn.status = 'cancelled'; this.turn.completedAt = timestamp; }
        for (const tool of this.toolsByCallId.values()) if (!terminalTool(tool.status)) { tool.status = 'cancelled'; tool.completedAt = timestamp; }
        this.append({ kind: 'stage', stageName: 'cancellation', summary: '生成已停止', status: 'failed', timestamp }, event.sequence);
        break;
      }
      case 'evidence_frozen': {
        const ids = Array.isArray(payload.evidence_ids) ? payload.evidence_ids.map(String) : [];
        this.append({ kind: 'evidence_frozen', snapshotId: String(payload.snapshot_id || ''), evidenceCount: ids.length, evidenceIds: ids, timestamp }, event.sequence);
        break;
      }
      case 'answer_generated':
        this.append({ kind: 'stage', stageName: 'answer_generator', summary: `已基于冻结证据草拟规划回答（${(payload.citations as unknown[])?.length || 0} 条证据引用）`, status: 'completed', timestamp }, event.sequence);
        break;
      case 'review_started': {
        const id = String(payload.review_id || '');
        const prior = this.turn.items.find((item) => item.kind === 'review' && item.reviewId === id);
        if (!prior) this.append({ kind: 'review', reviewId: id || undefined, attempt: Number(payload.attempt) || undefined, status: 'running', summary: '证据审查进行中', timestamp }, event.sequence);
        break;
      }
      case 'review_completed': {
        const verdict = payload.verdict == null || String(payload.verdict).trim() === '' ? undefined : String(payload.verdict).toUpperCase();
        const id = String(payload.review_id || '');
        const review = [...this.turn.items].reverse().find((item) => item.kind === 'review' && (id ? item.reviewId === id : item.status === 'running'));
        const status = payload.status === 'failed' || !verdict ? 'failed' : 'completed';
        const summary = verdict ? `审查结论：${verdict}` : (errorMessage(payload.error) || '证据审查未返回结论');
        if (review?.kind === 'review') Object.assign(review, { verdict, status, summary, attempt: Number(payload.attempt) || review.attempt, findingCount: typeof payload.finding_count === 'number' ? payload.finding_count : undefined, timestamp });
        else this.append({ kind: 'review', verdict, status, reviewId: id || undefined, attempt: Number(payload.attempt) || undefined, findingCount: typeof payload.finding_count === 'number' ? payload.finding_count : undefined, summary, timestamp }, event.sequence);
        break;
      }
      case 'publication_completed': {
        const rawState = payload.state ?? payload.publication_state;
        const state = rawState == null || String(rawState).trim() === '' ? '' : String(rawState).toLowerCase();
        if (!state || state === 'running' || state === 'pending') break;
        if (this.publicationItem) break;
        this.turn.status = state === 'published' ? 'published' : state === 'clarification' ? 'clarification' : state === 'limitation' ? 'limited' : 'failed';
        this.turn.completedAt = timestamp;
        this.publicationItem = { kind: 'publication', state, summary: state === 'published' ? '最终结论已正式发布' : state === 'clarification' ? '已发起澄清追问' : state === 'limitation' ? '触发知识边界安全限制说明' : `发布拦截：${state}`, timestamp };
        this.append(this.publicationItem, event.sequence);
        break;
      }
    }
    return this.getViewModel();
  }
}
