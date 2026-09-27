import { AxiosError } from 'axios';
import { apiDelete, apiGet, apiPost } from '../lib/api/contractClient';
import type { AuthUser } from './authService';
import type { ChatMessage as AppChatMessage, Citation } from '../types';
import { AgentEventProjector } from '../components/agent/eventProjector';
import type { AgentEventMessage, AgentTurnViewModel } from '../components/agent/types';
import type { DocumentResult } from './chatService';

type Identity = Pick<AuthUser, 'role' | 'username' | 'visitor_id'>;
type RawRecord = Record<string, unknown>;

export interface AgentSessionDetail {
  session_id?: string;
  messages?: RawRecord[];
  turns?: Array<RawRecord & { turn_id?: string; trace_id?: string; events?: RawRecord[] }>;
}

export interface AgentSessionSummary {
  session_id: string;
  title: string;
  status: string;
  turn_count: number;
  updated_at?: string | null;
}

const asRecord = (value: unknown): RawRecord =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as RawRecord : {};

const asString = (value: unknown): string => typeof value === 'string' ? value : '';

export const getAgentSessionStorageKey = (user: Identity): string | null => {
  if (user.role === 'visitor' && !user.visitor_id) return null;
  const principal = user.role === 'visitor' ? `visitor:${user.visitor_id}` : `admin:${user.username}`;
  return `geoai.agent.session.v1:${principal}`;
};

export const readAgentSessionId = (user: Identity): string | undefined => {
  try {
    const key = getAgentSessionStorageKey(user);
    if (!key) return undefined;
    const value = window.localStorage.getItem(key);
    return value || undefined;
  } catch {
    return undefined;
  }
};

export const saveAgentSessionId = (user: Identity, sessionId: string): void => {
  try {
    const key = getAgentSessionStorageKey(user);
    if (!key) return;
    window.localStorage.setItem(key, sessionId);
  } catch {
    // Private browsing and disabled storage must not block chat.
  }
};

export const clearAgentSessionId = (user: Identity): void => {
  try {
    const key = getAgentSessionStorageKey(user);
    if (!key) return;
    window.localStorage.removeItem(key);
  } catch {
    // Storage cleanup is best effort.
  }
};

const normalizeEvents = (
  sessionId: string,
  turnId: string,
  source: unknown,
): AgentEventMessage[] => {
  const envelope = asRecord(source);
  const candidates = Array.isArray(source)
    ? source
    : Array.isArray(envelope.ordered_events)
      ? envelope.ordered_events
      : Array.isArray(envelope.events)
        ? envelope.events
        : [];
  return candidates.map((candidate) => {
    const event = asRecord(candidate);
    return {
      event_type: asString(event.event_type),
      session_id: asString(event.session_id) || asString(envelope.session_id) || sessionId,
      turn_id: asString(event.turn_id) || asString(envelope.turn_id) || turnId,
      trace_id: asString(event.trace_id) || asString(envelope.trace_id) || undefined,
      event_id: asString(event.event_id) || undefined,
      sequence: typeof event.sequence === 'number' ? event.sequence : undefined,
      payload: asRecord(event.payload),
      created_at: asString(event.created_at) || undefined,
    };
  }).filter((event) => Boolean(event.event_type));
};

export const projectHistoricalTurn = (
  sessionId: string,
  turnId: string,
  events: AgentEventMessage[],
): AgentTurnViewModel => {
  const scoped = events
    .filter((event) => event.session_id === sessionId && event.turn_id === turnId)
    .sort((a, b) => (a.sequence ?? Number.MAX_SAFE_INTEGER) - (b.sequence ?? Number.MAX_SAFE_INTEGER));
  const seen = new Set<string>();
  const projector = new AgentEventProjector(sessionId, turnId);
  for (const event of scoped) {
    if (event.event_id) {
      if (seen.has(event.event_id)) continue;
      seen.add(event.event_id);
    }
    projector.applyEvent(event);
  }
  return projector.snapshot();
};

const citationsFromReferences = (references: unknown): Citation[] => {
  if (!Array.isArray(references)) return [];
  return references.flatMap((value) => {
    const reference = asRecord(value);
    const id = asString(reference.document_id) || asString(reference.id);
    if (!id) return [];
    return [{
      document_id: id,
      title: asString(reference.title),
      excerpt: asString(reference.content) || asString(reference.excerpt),
      confidence: typeof reference.similarity === 'number'
        ? reference.similarity
        : typeof reference.confidence === 'number' ? reference.confidence : 0,
    }];
  });
};

export const buildRestoredConversation = (
  detail: AgentSessionDetail,
  identity: Pick<Identity, 'role'>,
  eventOverrides: Map<string, AgentEventMessage[]> = new Map(),
): { messages: AppChatMessage[]; sessionId: string } => {
  const sessionId = asString(detail.session_id);
  const turns = detail.turns ?? [];
  const turnsById = new Map<string, AgentTurnViewModel>();
  const hasServerMessage = new Set<string>();

  for (const rawTurn of turns) {
    const turnId = asString(rawTurn.turn_id);
    if (!turnId) continue;
    const detailEvents = normalizeEvents(sessionId, turnId, rawTurn.events);
    const events = eventOverrides.get(turnId) ?? detailEvents;
    turnsById.set(turnId, projectHistoricalTurn(sessionId, turnId, events));
  }

  const sourceMessages = detail.messages ?? [];
  const messages: AppChatMessage[] = sourceMessages.map((rawMessage, index) => {
    const role = rawMessage.role === 'user' ? 'user' : 'assistant';
    const turnId = asString(rawMessage.turn_id);
    if (turnId && role === 'assistant') hasServerMessage.add(turnId);
    const references = rawMessage.references as DocumentResult[] | undefined;
    const citations = citationsFromReferences(references);
    const turn = turnsById.get(turnId);
    return {
      id: asString(rawMessage.id) || `restored-${index}`,
      role,
      content: asString(rawMessage.content),
      timestamp: asString(rawMessage.timestamp) || new Date(0).toISOString(),
      metadata: {
        document_ids: citations.map((citation) => citation.document_id),
        citations,
        original_query: role === 'user' ? asString(rawMessage.content) : undefined,
        agent_turn: role === 'assistant' && turn && turn.items.length ? turn : undefined,
      },
    };
  });

  // Process-only turns remain visible as a process card without inventing an answer.
  for (const rawTurn of turns) {
    const turnId = asString(rawTurn.turn_id);
    const turn = turnsById.get(turnId);
    if (!turnId || !turn || !turn.items.length || hasServerMessage.has(turnId)) continue;
    const carrier: AppChatMessage = {
      id: `process-${turnId}`,
      role: 'assistant',
      content: '',
      timestamp: turn.startedAt || new Date(0).toISOString(),
      metadata: { agent_turn: turn },
    };
    let rawUserIndex = -1;
    for (let index = sourceMessages.length - 1; index >= 0; index -= 1) {
      if (sourceMessages[index].role === 'user' && asString(sourceMessages[index].turn_id) === turnId) {
        rawUserIndex = index;
        break;
      }
    }
    const userMessageId = rawUserIndex >= 0 ? asString(sourceMessages[rawUserIndex].id) : '';
    const userMessageIndex = userMessageId
      ? messages.findIndex((message) => message.id === userMessageId)
      : -1;
    if (userMessageIndex >= 0) messages.splice(userMessageIndex + 1, 0, carrier);
    else messages.push(carrier);
  }

  return { messages, sessionId };
};

const is404 = (error: unknown): boolean => error instanceof AxiosError && error.response?.status === 404;

export class AgentSessionNotFoundError extends Error {
  constructor() {
    super('Saved agent session no longer exists.');
    this.name = 'AgentSessionNotFoundError';
  }
}

export async function fetchAgentSessionDetail(sessionId: string, signal?: AbortSignal): Promise<AgentSessionDetail> {
  // The OpenAPI response is an intentionally open object; retain runtime fields from the session API.
  return await apiGet('/api/agent/sessions/{session_id}', {
    params: { path: { session_id: sessionId } },
    config: { signal },
  }) as AgentSessionDetail;
}

export async function listAgentSessions(signal?: AbortSignal): Promise<AgentSessionSummary[]> {
  const result = await apiGet('/api/agent/sessions', {
    config: { signal },
  });
  if (!Array.isArray(result)) return [];
  return result.flatMap((value) => {
    const item = asRecord(value);
    const sessionId = asString(item.session_id);
    if (!sessionId) return [];
    return [{
      session_id: sessionId,
      title: asString(item.title) || '新建对话',
      status: asString(item.status) || 'active',
      turn_count: typeof item.turn_count === 'number' ? item.turn_count : 0,
      updated_at: asString(item.updated_at) || null,
    }];
  });
}

export async function createAgentSession(signal?: AbortSignal): Promise<AgentSessionSummary> {
  const result = asRecord(await apiPost('/api/agent/sessions', undefined, {
    config: { signal },
  }));
  const sessionId = asString(result.session_id);
  if (!sessionId) throw new Error('Server did not return a session_id.');
  return {
    session_id: sessionId,
    title: asString(result.title) || '新建对话',
    status: asString(result.status) || 'active',
    turn_count: typeof result.turn_count === 'number' ? result.turn_count : 0,
    updated_at: asString(result.updated_at) || null,
  };
}

async function fetchAdminTurnEvents(sessionId: string, turn: RawRecord & { turn_id?: string; trace_id?: string }, signal?: AbortSignal): Promise<AgentEventMessage[]> {
  const turnId = asString(turn.turn_id);
  if (!turnId) return [];
  try {
    const trace = await apiGet('/api/agent/sessions/{session_id}/turns/{turn_id}', {
      params: { path: { session_id: sessionId, turn_id: turnId } },
      config: { signal },
    });
    const events = normalizeEvents(sessionId, turnId, trace);
    if (events.length || !asString(turn.trace_id)) return events;
    const traceById = await apiGet('/api/agent/traces/{trace_id}', {
      params: { path: { trace_id: asString(turn.trace_id) } },
      config: { signal },
    });
    return normalizeEvents(sessionId, turnId, traceById);
  } catch (error) {
    const traceId = asString(turn.trace_id);
    if (!is404(error) || !traceId) throw error;
    const trace = await apiGet('/api/agent/traces/{trace_id}', {
      params: { path: { trace_id: traceId } },
      config: { signal },
    });
    return normalizeEvents(sessionId, turnId, trace);
  }
}

export async function restoreAgentSession(sessionId: string, user: Identity, signal?: AbortSignal) {
  let detail: AgentSessionDetail;
  try {
    detail = await fetchAgentSessionDetail(sessionId, signal);
  } catch (error) {
    if (is404(error)) {
      clearAgentSessionId(user);
      throw new AgentSessionNotFoundError();
    }
    throw error;
  }
  const eventOverrides = new Map<string, AgentEventMessage[]>();
  if (user.role !== 'visitor') {
    const turns = detail.turns ?? [];
    const eventsByTurn = await Promise.all(turns.map((turn) => fetchAdminTurnEvents(sessionId, turn, signal)));
    turns.forEach((turn, index) => {
      const turnId = asString(turn.turn_id);
      if (turnId) eventOverrides.set(turnId, eventsByTurn[index]);
    });
  }
  return buildRestoredConversation({ ...detail, session_id: detail.session_id || sessionId }, user, eventOverrides);
}

export async function deleteAgentSession(sessionId: string): Promise<void> {
  await apiDelete('/api/agent/sessions/{session_id}', {
    params: { path: { session_id: sessionId } },
  });
}
