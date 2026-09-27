import { strict as assert } from 'node:assert';
import { test, vi } from 'vitest';
import { apiPost, apiPostSse } from '../src/lib/api/contractClient';
import { executeBrowserTool } from '../src/gis/browserBridge';
import { chatService } from '../src/services/chatService';
import type { AgentEventMessage } from '../src/components/agent/types';
import type { components } from '../src/lib/api/generated/schema';

vi.mock('../src/lib/api/contractClient', () => ({ apiPost: vi.fn(), apiPostSse: vi.fn(), apiGet: vi.fn(), apiDelete: vi.fn() }));
vi.mock('../src/gis/browserBridge', () => ({ executeBrowserTool: vi.fn(), getBrowserMapContext: () => undefined }));

const frame = (type: string, callId: string, sequence: number) => JSON.stringify({
  session_id: 's', turn_id: 't', trace_id: 'trace', event_id: `evt-${sequence}`, sequence,
  payload: { tool_name: 'locate_map', tool_call_id: callId, status: 'succeeded', state: 'published' },
});
const handoff = (callId: string) => ({
  session_id: 's', trace_id: 'trace', publication_state: 'tool_execution_required',
  pending_tool_call_id: callId, continuation_token: `token-${callId}`,
  map_action: { type: 'locate_map', target: '成都' },
});
const receipt = (callId: string, status: 'succeeded' | 'failed' = 'succeeded') => ({
  tool_call_id: callId, tool_name: 'locate_map', status,
  effect: { status: 'applied', state_revision: 8 },
  map_context: { dimension: '3d', revision: 8 },
});

test('every browser handoff resumes the same SSE path and forwards complete process envelopes', async () => {
  vi.mocked(apiPost).mockReset().mockResolvedValue({ session_id: 's', generated_answer: '正式答案', publication_state: 'published' } as never);
  const stream = vi.mocked(apiPostSse).mockReset();
  stream.mockImplementationOnce(async (_path, _body, emit) => {
    emit?.('browser_tool_requested', frame('browser_tool_requested', 'gis-1', 1));
    emit?.('result', JSON.stringify(handoff('gis-1')));
  }).mockImplementationOnce(async (_path, body, emit) => {
    const request = body as components['schemas']['SearchRequest'];
    assert.equal(request.continuation_token, 'token-gis-1');
    assert.equal(request.browser_tool_receipt?.tool_call_id, 'gis-1');
    emit?.('browser_tool_completed', frame('browser_tool_completed', 'gis-1', 2));
    emit?.('browser_tool_requested', frame('browser_tool_requested', 'gis-2', 3));
    emit?.('result', JSON.stringify(handoff('gis-2')));
  }).mockImplementationOnce(async (_path, body, emit) => {
    assert.equal((body as components['schemas']['SearchRequest']).continuation_token, 'token-gis-2');
    emit?.('browser_tool_completed', frame('browser_tool_completed', 'gis-2', 4));
    emit?.('answer_generated', frame('answer_generated', '', 5));
    emit?.('review_started', frame('review_started', '', 6));
    emit?.('review_completed', frame('review_completed', '', 7));
    emit?.('publication_completed', frame('publication_completed', '', 8));
    emit?.('result', JSON.stringify({ session_id: 's', generated_answer: '正式答案', publication_state: 'published' }));
  });
  vi.mocked(executeBrowserTool).mockReset().mockResolvedValueOnce(receipt('gis-1') as never).mockResolvedValueOnce(receipt('gis-2') as never);
  const events: AgentEventMessage[] = [];
  const response = await chatService.sendMessageStream('问题', undefined, undefined, [], undefined, (event) => events.push(event));
  assert.equal(response.message, '正式答案');
  assert.equal(stream.mock.calls.length, 3);
  assert.equal(vi.mocked(apiPost).mock.calls.length, 0);
  const facts = events.filter((event) => event.turn_id === 't');
  assert.deepEqual(facts.map((event) => event.sequence), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(facts.map((event) => event.event_id), [1, 2, 3, 4, 5, 6, 7, 8].map((id) => `evt-${id}`));
});

test('failed browser receipt is sent to Runtime before fail-closed publication is displayed', async () => {
  vi.mocked(apiPost).mockReset().mockResolvedValue({ session_id: 's', generated_answer: '地图操作未完成。', publication_state: 'tool_execution_failed' } as never);
  const stream = vi.mocked(apiPostSse).mockReset();
  stream.mockImplementationOnce(async (_path, _body, emit) => emit?.('result', JSON.stringify(handoff('gis-1'))))
    .mockImplementationOnce(async (_path, body, emit) => {
      assert.equal((body as components['schemas']['SearchRequest']).browser_tool_receipt?.status, 'failed');
      emit?.('browser_tool_completed', frame('browser_tool_completed', 'gis-1', 2));
      emit?.('publication_completed', JSON.stringify({ session_id: 's', turn_id: 't', payload: { state: 'tool_execution_failed' } }));
      emit?.('result', JSON.stringify({ session_id: 's', publication_state: 'tool_execution_failed', generated_answer: '地图操作未完成。' }));
    });
  vi.mocked(executeBrowserTool).mockReset().mockResolvedValueOnce(receipt('gis-1', 'failed') as never);
  const events: AgentEventMessage[] = [];
  const response = await chatService.sendMessageStream('问题', undefined, undefined, [], undefined, (event) => events.push(event));
  assert.equal(response.message, '地图操作未完成。');
  assert.equal(events.find((event) => event.event_type === 'publication_completed')?.payload.state, 'tool_execution_failed');
});

test('abort during browser execution cannot start a continuation request', async () => {
  vi.mocked(apiPost).mockReset().mockResolvedValue({ session_id: 's', generated_answer: '不应到达', publication_state: 'published' } as never);
  const stream = vi.mocked(apiPostSse).mockReset();
  stream.mockImplementationOnce(async (_path, _body, emit) => emit?.('result', JSON.stringify(handoff('gis-1'))));
  const controller = new AbortController();
  vi.mocked(executeBrowserTool).mockReset().mockImplementationOnce(async () => {
    controller.abort();
    return receipt('gis-1') as never;
  });
  const log = vi.spyOn(console, 'error').mockImplementation(() => {});
  try {
    await assert.rejects(chatService.sendMessageStream('问题', undefined, undefined, [], undefined, undefined, controller.signal), { name: 'AbortError' });
    assert.equal(stream.mock.calls.length, 1);
  } finally { log.mockRestore(); }
});
