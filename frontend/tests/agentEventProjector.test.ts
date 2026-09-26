import { strict as assert } from 'node:assert';
import { test } from 'vitest';
import { AgentEventProjector } from '../src/components/agent/eventProjector';

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
  const gisTool = model.items[0];
  if (gisTool.kind === 'tool') {
    assert.equal(gisTool.status, 'waiting_browser');
    assert.equal(gisTool.executionSite, 'browser');
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
  if (gisTool.kind === 'tool') {
    assert.equal(gisTool.status, 'succeeded');
    assert.equal(gisTool.browserReceipt?.runtimeDimension, '3d');
  }
});
