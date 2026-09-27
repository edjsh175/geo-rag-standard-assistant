import { strict as assert } from 'node:assert';
import { AxiosError } from 'axios';
import { test, vi } from 'vitest';
import { apiDelete, apiGet, apiPost, apiPostSse } from '../src/lib/api/contractClient';
import { chatService } from '../src/services/chatService';
import {
  buildRestoredConversation,
  createAgentSession,
  deleteAgentSession,
  listAgentSessions,
  AgentSessionNotFoundError,
  getAgentSessionStorageKey,
  readAgentSessionId,
  projectHistoricalTurn,
  restoreAgentSession,
} from '../src/services/agentHistory';

vi.mock('../src/lib/api/contractClient', () => ({
  apiGet: vi.fn(),
  apiDelete: vi.fn(),
  apiPost: vi.fn(),
  apiPostSse: vi.fn(),
}));

test('historical events are replayed in sequence once and cannot cross turn boundaries', () => {
  const first = projectHistoricalTurn('session-a', 'turn-a', [
    { event_type: 'tool_completed', session_id: 'session-a', turn_id: 'turn-b', sequence: 1, event_id: 'wrong', payload: { tool_call_id: 'x' } },
    { event_type: 'tool_completed', session_id: 'session-a', turn_id: 'turn-a', sequence: 2, event_id: 'finish', payload: { tool_call_id: 'call-1', tool_name: 'retrieve_kb', status: 'ok' } },
    { event_type: 'tool_started', session_id: 'session-a', turn_id: 'turn-a', sequence: 1, event_id: 'start', payload: { tool_call_id: 'call-1', tool_name: 'retrieve_kb' } },
    { event_type: 'tool_completed', session_id: 'session-a', turn_id: 'turn-a', sequence: 2, event_id: 'finish', payload: { tool_call_id: 'call-1', tool_name: 'retrieve_kb', status: 'failed' } },
    { event_type: 'controller_decision', session_id: 'session-a', turn_id: 'turn-a', sequence: 0, event_id: 'decision', payload: { decision_summary: '先检索' } },
  ]);

  assert.equal(first.items.length, 2);
  assert.equal(first.items[0].kind, 'decision');
  assert.equal(first.items[1].kind, 'tool');
  if (first.items[1].kind === 'tool') assert.equal(first.items[1].status, 'succeeded');
});

test('restored published messages keep server text and references; process-only turns get an empty carrier', () => {
  const result = buildRestoredConversation({
    session_id: 'session-a',
    messages: [
      { id: 'u1', role: 'user', content: '问题', turn_id: 'turn-1', timestamp: '2026-01-01T00:00:00Z' },
      { id: 'a1', role: 'assistant', content: '服务端答案', turn_id: 'turn-1', timestamp: '2026-01-01T00:00:01Z', references: [{ id: 'doc-1', title: '规范', content: '摘要', similarity: 0.9 }] },
      { id: 'u2', role: 'user', content: '另一个问题', turn_id: 'turn-2' },
      { id: 'u3', role: 'user', content: '第三个问题', turn_id: 'turn-3' },
    ],
    turns: [
      { turn_id: 'turn-1', events: [{ event_type: 'controller_decision', sequence: 1, payload: { decision_summary: '已检索' } }] },
      { turn_id: 'turn-2', events: [{ event_type: 'tool_started', sequence: 1, payload: { tool_call_id: 'call-2', tool_name: 'retrieve_kb' } }] },
      { turn_id: 'turn-3', events: [{ event_type: 'tool_started', sequence: 1, payload: { tool_call_id: 'call-3', tool_name: 'retrieve_kb' } }] },
    ],
  }, { role: 'visitor' });

  assert.equal(result.messages.find((message) => message.id === 'a1')?.content, '服务端答案');
  const restoredAnswer = result.messages.find((message) => message.id === 'a1');
  assert.equal(restoredAnswer?.metadata?.citations?.[0].document_id, 'doc-1');
  const carrier = result.messages.find((message) => message.metadata?.agent_turn?.turnId === 'turn-2');
  assert.ok(carrier);
  assert.equal(carrier?.content, '');
  assert.deepEqual(result.messages.map((message) => message.id), ['u1', 'a1', 'u2', 'process-turn-2', 'u3', 'process-turn-3']);
});

test('session storage keys are scoped to the authenticated principal', () => {
  assert.equal(getAgentSessionStorageKey({ role: 'admin', username: 'alice', visitor_id: null }), 'geoai.agent.session.v1:admin:alice');
  assert.equal(getAgentSessionStorageKey({ role: 'visitor', username: 'demo-visitor', visitor_id: 'visitor-7' }), 'geoai.agent.session.v1:visitor:visitor-7');
  assert.equal(getAgentSessionStorageKey({ role: 'visitor', username: 'demo-visitor', visitor_id: null }), null);
});

test('session management uses the server session lifecycle endpoints', async () => {
  const get = vi.mocked(apiGet);
  const post = vi.mocked(apiPost);
  const remove = vi.mocked(apiDelete);
  get.mockReset();
  post.mockReset();
  remove.mockReset();
  get.mockResolvedValueOnce([
    { session_id: 'session-a', title: '土地整治', status: 'active', turn_count: 2, updated_at: '2026-09-27T08:00:00Z' },
  ] as never);
  post.mockResolvedValueOnce({
    session_id: 'session-b', title: '新建对话', status: 'active', turn_count: 0,
  } as never);
  remove.mockResolvedValueOnce({ session_id: 'session-a', deleted: true } as never);

  const sessions = await listAgentSessions();
  const created = await createAgentSession();
  await deleteAgentSession('session-a');

  assert.deepEqual(sessions, [{
    session_id: 'session-a', title: '土地整治', status: 'active', turn_count: 2, updated_at: '2026-09-27T08:00:00Z',
  }]);
  assert.equal(created.session_id, 'session-b');
  assert.equal(get.mock.calls[0][0], '/api/agent/sessions');
  assert.equal(post.mock.calls[0][0], '/api/agent/sessions');
  assert.equal(remove.mock.calls[0][0], '/api/agent/sessions/{session_id}');
});

test('visitor restoration only reads session detail and its embedded turn events', async () => {
  const get = vi.mocked(apiGet);
  get.mockReset();
  get.mockResolvedValueOnce({
    session_id: 'session-v',
    messages: [],
    turns: [{ turn_id: 'turn-v', events: [{ event_id: 'e1', event_type: 'controller_decision', sequence: 1, payload: {} }] }],
  } as never);

  await restoreAgentSession('session-v', { role: 'visitor', username: 'demo-visitor', visitor_id: 'visitor-7' });

  assert.equal(get.mock.calls.length, 1);
  assert.equal(get.mock.calls[0][0], '/api/agent/sessions/{session_id}');
});

test('admin restoration fetches each turn trace through the admin turn endpoint', async () => {
  const get = vi.mocked(apiGet);
  get.mockReset();
  get.mockResolvedValueOnce({
    session_id: 'session-a',
    messages: [],
    turns: [{ turn_id: 'turn-a', trace_id: 'trace-a', events: [] }],
  } as never);
  get.mockResolvedValueOnce({
    session_id: 'session-a', turn_id: 'turn-a', trace_id: 'trace-a',
    ordered_events: [{ event_id: 'e1', event_type: 'controller_decision', sequence: 1, payload: {} }],
  } as never);

  await restoreAgentSession('session-a', { role: 'admin', username: 'alice', visitor_id: null });

  assert.deepEqual(get.mock.calls.map(([path]) => path), [
    '/api/agent/sessions/{session_id}',
    '/api/agent/sessions/{session_id}/turns/{turn_id}',
  ]);
});

test('admin falls back to the trace id endpoint only when a turn trace is missing', async () => {
  const get = vi.mocked(apiGet);
  get.mockReset();
  get.mockResolvedValueOnce({
    session_id: 'session-a', messages: [],
    turns: [{ turn_id: 'turn-a', trace_id: 'trace-a', events: [] }],
  } as never);
  get.mockRejectedValueOnce(Object.assign(new AxiosError('missing turn trace'), { response: { status: 404 } }));
  get.mockResolvedValueOnce({
    session_id: 'session-a', turn_id: 'turn-a', trace_id: 'trace-a',
    ordered_events: [{ event_id: 'e1', event_type: 'controller_decision', sequence: 1, payload: {} }],
  } as never);

  await restoreAgentSession('session-a', { role: 'admin', username: 'alice', visitor_id: null });

  assert.deepEqual(get.mock.calls.map(([path]) => path), [
    '/api/agent/sessions/{session_id}',
    '/api/agent/sessions/{session_id}/turns/{turn_id}',
    '/api/agent/traces/{trace_id}',
  ]);
});

test('stream failure after receiving a session id keeps the real id for retry', async () => {
  const log = vi.spyOn(console, 'error').mockImplementation(() => {});
  const stream = vi.mocked(apiPostSse);
  stream.mockReset();
  stream.mockImplementationOnce(async (_path, _body, onEvent) => {
    onEvent?.('controller_decision', JSON.stringify({ session_id: 'session-real', turn_id: 'turn-1', payload: {} }));
    throw new Error('connection dropped');
  });
  let observedSessionId = '';
  const response = await chatService.sendMessageStream(
    '问题', undefined, undefined, [], undefined,
    (event) => { observedSessionId = event.session_id; },
  );
  assert.equal(observedSessionId, 'session-real');
  assert.equal(response.conversation_id, 'session-real');
  log.mockRestore();
});

test('aborted stream propagates abort after session id was observed', async () => {
  const log = vi.spyOn(console, 'error').mockImplementation(() => {});
  const stream = vi.mocked(apiPostSse);
  stream.mockReset();
  const controller = new AbortController();
  stream.mockImplementationOnce(async (_path, _body, onEvent) => {
    onEvent?.('controller_decision', JSON.stringify({ session_id: 'session-real', turn_id: 'turn-1', payload: {} }));
    controller.abort();
    throw new DOMException('The operation was aborted.', 'AbortError');
  });
  await assert.rejects(
    chatService.sendMessageStream('问题', undefined, undefined, [], undefined, undefined, controller.signal),
    { name: 'AbortError' },
  );
  log.mockRestore();
});

test('missing saved session clears its principal storage key', async () => {
  const storage = createMemoryStorage();
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { localStorage: storage } });
  const get = vi.mocked(apiGet);
  get.mockReset();
  const error = Object.assign(new AxiosError('not found'), { response: { status: 404 } });
  get.mockRejectedValueOnce(error);
  const user = { role: 'admin', username: 'alice', visitor_id: null } as const;
  storage.setItem(getAgentSessionStorageKey(user)!, 'gone-session');

  try {
    await assert.rejects(restoreAgentSession('gone-session', user), AgentSessionNotFoundError);
    assert.equal(readAgentSessionId(user), undefined);
  } finally {
    Object.defineProperty(globalThis, 'window', { configurable: true, value: previousWindow });
  }
});

test('transient session restore failure leaves the saved ID available for retry', async () => {
  const storage = createMemoryStorage();
  const previousWindow = globalThis.window;
  Object.defineProperty(globalThis, 'window', { configurable: true, value: { localStorage: storage } });
  const get = vi.mocked(apiGet);
  get.mockReset();
  const error = Object.assign(new AxiosError('server error'), { response: { status: 500 } });
  get.mockRejectedValueOnce(error);
  const user = { role: 'admin', username: 'alice', visitor_id: null } as const;
  storage.setItem(getAgentSessionStorageKey(user)!, 'retry-session');

  try {
    await assert.rejects(restoreAgentSession('retry-session', user));
    assert.equal(readAgentSessionId(user), 'retry-session');
  } finally {
    Object.defineProperty(globalThis, 'window', { configurable: true, value: previousWindow });
  }
});

function createMemoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => { values.set(key, value); },
    removeItem: (key: string) => { values.delete(key); },
  };
}
