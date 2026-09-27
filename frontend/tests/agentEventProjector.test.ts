import { strict as assert } from 'node:assert';
import { test } from 'vitest';
import { AgentEventProjector } from '../src/components/agent/eventProjector';

test('historical process starts at its first persisted event', () => {
  const model = new AgentEventProjector('s', 't').ingest({
    event_type: 'user_message', session_id: 's', turn_id: 't',
    created_at: '2026-09-25T08:00:00Z', payload: { text: '定位成都' },
  });
  assert.equal(model.startedAt, '2026-09-25T08:00:00Z');
});

test('cancelled historical turn settles its unfinished tools', () => {
  const projector = new AgentEventProjector('s', 't');
  projector.ingest({ event_type: 'browser_tool_requested', session_id: 's', turn_id: 't',
    payload: { tool_name: 'locate_map', tool_call_id: 'gis-1' } });
  const model = projector.ingest({ event_type: 'run_cancelled', session_id: 's', turn_id: 't',
    created_at: '2026-09-25T08:01:00Z', payload: { reason: 'user_stop' } });
  assert.equal(model.status, 'cancelled');
  assert.equal(model.completedAt, '2026-09-25T08:01:00Z');
  assert.equal(model.items[0].kind === 'tool' && model.items[0].status, 'cancelled');
});

test('browser cancellation updates the original tool without assuming publication', () => {
  const projector = new AgentEventProjector('s', 't');
  projector.ingest({ event_type: 'browser_tool_requested', session_id: 's', turn_id: 't',
    payload: { tool_name: 'locate_map', tool_call_id: 'gis-1' } });
  const model = projector.ingest({ event_type: 'browser_tool_cancelled', session_id: 's', turn_id: 't',
    payload: { tool_call_id: 'gis-1', reason: 'superseded_by_user_request' } });
  assert.equal(model.items.length, 1);
  assert.equal(model.items[0].kind === 'tool' && model.items[0].status, 'cancelled');
  assert.equal(model.status, 'running');
});

test('AgentEventProjector projects full lifecycle into ordered timeline', () => {
  const projector = new AgentEventProjector('session-1', 'turn-1');

  // 1. Controller decision
  let model = projector.ingest({
    event_type: 'controller_decision',
    session_id: 'session-1',
    turn_id: 'turn-1',
    payload: {
      action: 'tool_call',
      tool_name: 'retrieve_kb',
      decision_summary: '需要先检索滑坡相关规范',
    },
  });
  assert.equal(model.items.length, 1);
  assert.equal(model.items[0].kind, 'decision');

  // 2. Tool started
  model = projector.ingest({
    event_type: 'tool_started',
    session_id: 'session-1',
    turn_id: 'turn-1',
    payload: {
      tool_name: 'retrieve_kb',
      tool_call_id: 'call-100',
      arguments: { query: '滑坡监测标准' },
    },
  });
  assert.equal(model.items.length, 2);
  const toolItem = model.items[1];
  assert.equal(toolItem.kind, 'tool');
  if (toolItem.kind === 'tool') {
    assert.equal(toolItem.callId, 'call-100');
    assert.equal(toolItem.status, 'running');
  }

  // 3. Tool completed
  model = projector.ingest({
    event_type: 'tool_completed',
    session_id: 'session-1',
    turn_id: 'turn-1',
    payload: {
      tool_name: 'retrieve_kb',
      tool_call_id: 'call-100',
      status: 'ok',
      result_summary: { matches: 3 },
    },
  });
  // Same callId updated in place
  assert.equal(model.items.length, 2);
  const updatedTool = model.items[1];
  if (updatedTool.kind === 'tool') {
    assert.equal(updatedTool.status, 'succeeded');
  }

  // 4. Evidence frozen
  model = projector.ingest({
    event_type: 'evidence_frozen',
    session_id: 'session-1',
    turn_id: 'turn-1',
    payload: {
      snapshot_id: 'snap-1',
      evidence_ids: ['ev-1', 'ev-2'],
    },
  });
  assert.equal(model.items.length, 3);
  assert.equal(model.items[2].kind, 'evidence_frozen');

  // 5. Answer generated
  model = projector.ingest({
    event_type: 'answer_generated',
    session_id: 'session-1',
    turn_id: 'turn-1',
    payload: { citations: ['ev-1'] },
  });
  assert.equal(model.items.length, 4);
  assert.equal(model.items[3].kind, 'stage');

  // 6. Review completed
  model = projector.ingest({
    event_type: 'review_completed',
    session_id: 'session-1',
    turn_id: 'turn-1',
    payload: { verdict: 'PASS' },
  });
  assert.equal(model.items.length, 5);
  assert.equal(model.items[4].kind, 'review');

  // 7. Publication completed
  model = projector.ingest({
    event_type: 'publication_completed',
    session_id: 'session-1',
    turn_id: 'turn-1',
    payload: { state: 'published' },
  });
  assert.equal(model.items.length, 6);
  assert.equal(model.status, 'published');
});

test('AgentEventProjector handles browser GIS tool continuation', () => {
  const projector = new AgentEventProjector('session-2', 'turn-1');

  // Browser tool started
  projector.ingest({
    event_type: 'tool_started',
    session_id: 'session-2',
    turn_id: 'turn-1',
    payload: { tool_name: 'locate_map', tool_call_id: 'call-gis-1' },
  });

  // Browser execution requested
  let model = projector.ingest({
    event_type: 'browser_tool_requested',
    session_id: 'session-2',
    turn_id: 'turn-1',
    payload: {
      tool_name: 'locate_map',
      tool_call_id: 'call-gis-1',
      arguments: { longitude: 104.06, latitude: 30.67 },
    },
  });
  assert.equal(model.items.length, 1);
  const waitingGisTool = model.items[0];
  if (waitingGisTool.kind === 'tool') {
    assert.equal(waitingGisTool.status, 'waiting_browser');
    assert.equal(waitingGisTool.executionSite, 'browser');
  }

  // Browser tool completed with receipt
  model = projector.ingest({
    event_type: 'browser_tool_completed',
    session_id: 'session-2',
    turn_id: 'turn-1',
    payload: {
      tool_name: 'locate_map',
      tool_call_id: 'call-gis-1',
      status: 'succeeded',
      receipt: { map_dimension: '3d', state_revision: 5 },
    },
  });
  assert.equal(model.items.length, 1);
  const completedGisTool = model.items[0];
  if (completedGisTool.kind === 'tool') {
    assert.equal(completedGisTool.status, 'succeeded');
    assert.equal(completedGisTool.browserReceipt?.runtimeDimension, '3d');
  }
});

test('deduplicates every event by event_id and does not accept events from another turn', () => {
  const projector = new AgentEventProjector('session-1', 'turn-1');
  const base = { session_id: 'session-1', turn_id: 'turn-1', event_id: 'evt-1' };
  projector.ingest({ ...base, event_type: 'evidence_frozen', payload: { snapshot_id: 'a' } });
  projector.ingest({ ...base, event_type: 'evidence_frozen', payload: { snapshot_id: 'b' } });
  const model = projector.ingest({ ...base, turn_id: 'turn-elsewhere', event_type: 'controller_decision', payload: { tool_name: 'bad' } });
  assert.equal(model.items.length, 1);
  assert.equal(model.items[0].kind === 'evidence_frozen' && model.items[0].snapshotId, 'a');
});

test('pairs tool lifecycle in O(1) model while preserving completion that arrives before start', () => {
  const projector = new AgentEventProjector('s', 't');
  projector.ingest({ event_type: 'tool_completed', session_id: 's', turn_id: 't', sequence: 2,
    payload: { tool_call_id: 'call-a', tool_name: 'retrieve_kb', status: 'ok', result_summary: { count: 4 } } });
  const model = projector.ingest({ event_type: 'tool_started', session_id: 's', turn_id: 't', sequence: 1,
    payload: { tool_call_id: 'call-a', tool_name: 'retrieve_kb', arguments: { query: 'x' } } });
  assert.equal(model.items.length, 1);
  assert.equal(model.items[0].kind === 'tool' && model.items[0].status, 'succeeded');
  assert.deepEqual(model.items[0].kind === 'tool' && model.items[0].output, { count: 4 });
});

test('keeps review lifecycle, actual verdict, and missing verdict is not PASS', () => {
  const projector = new AgentEventProjector('s', 't');
  projector.ingest({ event_type: 'review_started', session_id: 's', turn_id: 't', payload: {} });
  let model = projector.ingest({ event_type: 'review_completed', session_id: 's', turn_id: 't', payload: { verdict: 'SUPPORTED' } });
  const review = model.items.find((item) => item.kind === 'review');
  assert.equal(review?.kind === 'review' && review.verdict, 'SUPPORTED');
  projector.reset('s', 't');
  model = projector.ingest({ event_type: 'review_completed', session_id: 's', turn_id: 't', payload: {} });
  const missing = model.items.find((item) => item.kind === 'review');
  assert.notEqual(missing?.kind === 'review' && missing.verdict, 'PASS');
});

test('ignores non-terminal publication events and does not infer published from missing state', () => {
  const projector = new AgentEventProjector('s', 't');
  let model = projector.ingest({ event_type: 'publication_started', session_id: 's', turn_id: 't', payload: {} });
  assert.equal(model.status, 'running');
  model = projector.ingest({ event_type: 'publication_completed', session_id: 's', turn_id: 't', payload: {} });
  assert.notEqual(model.status, 'published');
});

test('snapshots are immutable and sequence fallback deduplicates events without event_id', () => {
  const projector = new AgentEventProjector('s', 't');
  const first = projector.ingest({ event_type: 'controller_decision', session_id: 's', turn_id: 't', sequence: 4, payload: { tool_name: 'a' } });
  projector.ingest({ event_type: 'controller_decision', session_id: 's', turn_id: 't', sequence: 4, payload: { tool_name: 'b' } });
  assert.equal(first.items.length, 1);
  assert.equal(projector.snapshot().items.length, 1);
  assert.notEqual(first.items, projector.snapshot().items);
});

test('keeps user message start time and sorts a late start by first lifecycle sequence', () => {
  const projector = new AgentEventProjector('s', 't');
  projector.ingest({ event_type: 'user_message', session_id: 's', turn_id: 't', sequence: 1,
    created_at: '2026-09-25T08:00:00Z', payload: { text: '开始' } });
  projector.ingest({ event_type: 'tool_completed', session_id: 's', turn_id: 't', sequence: 4,
    payload: { tool_call_id: 'late', tool_name: 'retrieve_kb', status: 'partial', result_summary: { admitted_count: 2 } } });
  const model = projector.ingest({ event_type: 'tool_started', session_id: 's', turn_id: 't', sequence: 3,
    created_at: '2026-09-25T08:01:00Z', payload: { tool_call_id: 'late', tool_name: 'retrieve_kb', arguments: { query: 'roads' } } });
  assert.equal(model.startedAt, '2026-09-25T08:00:00Z');
  assert.equal(model.items[0].kind, 'tool');
  assert.equal(model.items[0].kind === 'tool' && model.items[0].status, 'succeeded');
  assert.deepEqual(model.items[0].kind === 'tool' && model.items[0].arguments, { query: 'roads' });
});

test('browser execution state and receipt effect remain separate; publication is upserted once', () => {
  const projector = new AgentEventProjector('s', 't');
  projector.ingest({ event_type: 'browser_tool_completed', session_id: 's', turn_id: 't', payload: {
    tool_call_id: 'b', tool_name: 'locate_map', status: 'succeeded', receipt: { effect_status: 'applied', map_dimension: '2d' },
  } });
  let model = projector.ingest({ event_type: 'publication_completed', session_id: 's', turn_id: 't', payload: { state: 'published' } });
  model = projector.ingest({ event_type: 'publication_completed', event_id: 'different-event', session_id: 's', turn_id: 't', payload: { state: 'failed' } });
  assert.equal(model.items.filter((item) => item.kind === 'publication').length, 1);
  const tool = model.items.find((item) => item.kind === 'tool');
  assert.equal(tool?.kind === 'tool' && tool.browserReceipt?.status, 'succeeded');
  assert.equal(tool?.kind === 'tool' && tool.browserReceipt?.effectStatus, 'applied');
});

test('late browser handoff enriches but does not downgrade a completed browser tool', () => {
  const projector = new AgentEventProjector('s', 't');
  projector.ingest({ event_type: 'browser_tool_completed', session_id: 's', turn_id: 't', sequence: 3,
    payload: { tool_call_id: 'b', tool_name: 'locate_map', status: 'succeeded', receipt: { effect_status: 'applied' } } });
  const model = projector.ingest({ event_type: 'tool_completed', session_id: 's', turn_id: 't', sequence: 2,
    payload: { tool_call_id: 'b', tool_name: 'locate_map', status: 'browser_execution_required', arguments: { longitude: 104 } } });
  const tool = model.items.find((item) => item.kind === 'tool');
  assert.equal(tool?.kind === 'tool' && tool.status, 'succeeded');
  assert.deepEqual(tool?.kind === 'tool' && tool.arguments, { longitude: 104 });
});
