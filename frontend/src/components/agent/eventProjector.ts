import {
  AgentEventMessage,
  AgentProcessItem,
  AgentToolItem,
  AgentTurnViewModel,
} from './types';

export class AgentEventProjector {
  private turn: AgentTurnViewModel;

  constructor(sessionId: string = '', turnId: string = '') {
    this.turn = {
      sessionId,
      turnId,
      status: 'running',
      items: [],
      startedAt: new Date().toISOString(),
    };
  }

  getViewModel(): AgentTurnViewModel {
    return {
      ...this.turn,
      items: [...this.turn.items],
    };
  }

  snapshot(): AgentTurnViewModel {
    return this.getViewModel();
  }

  applyEvent(event: AgentEventMessage): AgentTurnViewModel {
    return this.ingest(event);
  }

  reset(sessionId: string = '', turnId: string = ''): void {
    this.turn = {
      sessionId,
      turnId,
      status: 'running',
      items: [],
      startedAt: new Date().toISOString(),
    };
  }

  ingest(event: AgentEventMessage): AgentTurnViewModel {
    if (!this.turn.sessionId && event.session_id) this.turn.sessionId = event.session_id;
    if (!this.turn.turnId && event.turn_id) this.turn.turnId = event.turn_id;
    if (event.trace_id) this.turn.traceId = event.trace_id;

    const payload = event.payload || {};
    const timestamp = event.created_at || new Date().toISOString();

    switch (event.event_type) {
      case 'controller_decision': {
        const toolName = payload.tool_name || payload.tool || payload.action;
        const summary =
          payload.decision_summary ||
          (toolName === 'compose_answer'
            ? '决策：证据充分，生成专业规划回答'
            : toolName === 'direct_answer'
            ? '决策：直接回答对话或交互指令'
            : toolName === 'clarify'
            ? '决策：实体或范围存在歧义，请求澄清'
            : `决策：规划执行工具 · ${toolName}`);

        this.turn.items.push({
          kind: 'decision',
          toolName: String(toolName || ''),
          action: String(payload.action || ''),
          summary: String(summary),
          timestamp,
        });
        break;
      }

      case 'tool_started': {
        const callId = String(payload.tool_call_id || `call_${Date.now()}`);
        const toolName = String(payload.tool_name || 'unknown_tool');
        const existing = this.turn.items.find(
          (item): item is AgentToolItem => item.kind === 'tool' && item.callId === callId
        );

        if (existing) {
          existing.status = 'running';
          if (payload.arguments) existing.arguments = payload.arguments;
        } else {
          this.turn.items.push({
            kind: 'tool',
            callId,
            toolName,
            status: 'running',
            arguments: payload.arguments,
            executionSite: 'backend',
            startedAt: timestamp,
          });
        }
        break;
      }

      case 'tool_completed': {
        const callId = String(payload.tool_call_id || '');
        const existing = this.turn.items.find(
          (item): item is AgentToolItem => item.kind === 'tool' && item.callId === callId
        );

        const isOk = payload.status === 'ok' || payload.status === 'succeeded';
        if (existing) {
          existing.status = isOk ? 'succeeded' : 'failed';
          existing.output = payload.result_summary || (payload as Record<string, unknown>);
          existing.error = payload.error ? String(payload.error) : undefined;
          existing.completedAt = timestamp;
        } else {
          this.turn.items.push({
            kind: 'tool',
            callId: callId || `call_${Date.now()}`,
            toolName: String(payload.tool_name || 'tool'),
            status: isOk ? 'succeeded' : 'failed',
            output: payload.result_summary || (payload as Record<string, unknown>),
            error: payload.error ? String(payload.error) : undefined,
            executionSite: 'backend',
            completedAt: timestamp,
          });
        }
        break;
      }

      case 'browser_tool_requested': {
        const callId = String(payload.tool_call_id || '');
        const existing = this.turn.items.find(
          (item): item is AgentToolItem => item.kind === 'tool' && item.callId === callId
        );
        if (existing) {
          existing.status = 'waiting_browser';
          existing.executionSite = 'browser';
        } else {
          this.turn.items.push({
            kind: 'tool',
            callId: callId || `call_${Date.now()}`,
            toolName: String(payload.tool_name || 'browser_gis_tool'),
            status: 'waiting_browser',
            executionSite: 'browser',
            arguments: payload.arguments,
            startedAt: timestamp,
          });
        }
        break;
      }

      case 'browser_tool_completed': {
        const callId = String(payload.tool_call_id || '');
        const existing = this.turn.items.find(
          (item): item is AgentToolItem => item.kind === 'tool' && item.callId === callId
        );
        const receipt = (payload.receipt || {}) as Record<string, unknown>;
        const isSuccess = payload.status === 'succeeded';
        if (existing) {
          existing.status = isSuccess ? 'succeeded' : 'failed';
          existing.browserReceipt = {
            status: String(payload.status || 'unknown'),
            runtimeDimension: receipt.map_dimension as '2d' | '3d' | undefined,
            stateRevision: typeof receipt.state_revision === 'number' ? receipt.state_revision : undefined,
          };
          existing.completedAt = timestamp;
        }
        break;
      }

      case 'evidence_frozen': {
        const evidenceIds = Array.isArray(payload.evidence_ids) ? payload.evidence_ids.map(String) : [];
        this.turn.items.push({
          kind: 'evidence_frozen',
          snapshotId: String(payload.snapshot_id || ''),
          evidenceCount: evidenceIds.length,
          evidenceIds,
          timestamp,
        });
        break;
      }

      case 'answer_generated': {
        this.turn.items.push({
          kind: 'stage',
          stageName: 'answer_generator',
          summary: `已基于冻结证据草拟规划回答（${(payload.citations as unknown[])?.length || 0} 条证据引用）`,
          status: 'completed',
          timestamp,
        });
        break;
      }

      case 'review_completed': {
        const verdict = String(payload.verdict || 'PASS').toUpperCase() as 'PASS' | 'REVISE' | 'REJECT';
        this.turn.items.push({
          kind: 'review',
          verdict,
          summary:
            verdict === 'PASS'
              ? '证据审查通过：结论与引用严谨匹配'
              : verdict === 'REVISE'
              ? '证据审查提示：需对部分推论范围收敛修复'
              : '证据审查拒绝：结论缺乏必要证据支撑',
          timestamp,
        });
        break;
      }

      case 'publication_completed': {
        const state = String(payload.state || 'published');
        this.turn.status =
          state === 'published'
            ? 'published'
            : state === 'clarification'
            ? 'clarification'
            : state === 'limitation'
            ? 'limited'
            : 'failed';
        this.turn.completedAt = timestamp;
        this.turn.items.push({
          kind: 'publication',
          state,
          summary:
            state === 'published'
              ? '最终结论已正式发布'
              : state === 'clarification'
              ? '已发起澄清追问'
              : state === 'limitation'
              ? '触发知识边界安全限制说明'
              : `发布拦截：${state}`,
          timestamp,
        });
        break;
      }
    }

    return this.getViewModel();
  }
}
