import { strict as assert } from 'node:assert';
import { test } from 'vitest';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { AgentProcess } from '../src/components/agent/AgentProcess';
import { GenericToolView } from '../src/components/agent/GenericToolView';
import { AgentTurnViewModel, AgentToolItem } from '../src/components/agent/types';

const turn = (status: AgentTurnViewModel['status'], items: AgentTurnViewModel['items']): AgentTurnViewModel => ({
  sessionId: 's', turnId: 't', status, items,
});

test('executing process is expanded with accessible disclosure state', () => {
  const html = renderToStaticMarkup(<AgentProcess turn={turn('running', [
    { kind: 'tool', callId: 'c1', toolName: 'retrieve_kb', status: 'running', arguments: { query: 'roads' } },
  ])} />);
  assert.match(html, /aria-expanded="true"/);
  assert.match(html, /aria-controls=/);
  assert.match(html, /aria-expanded="false"/);
});

test('all P0 tools have specific renderer output and expose call id', () => {
  const names = ['retrieve_kb', 'import_vector_dataset', 'set_layer_visibility', 'set_vector_style',
    'fit_vector_layer', 'locate_map', 'inspect_layer_features', 'get_feature_geometry',
    'query_spatial_relation', 'spatial_overlay'];
  const items: AgentToolItem[] = names.map((toolName, i) => ({
    kind: 'tool', callId: `call-${i}`, toolName, status: 'running',
    arguments: [
      { query: 'roads' }, { file_ref: `file-${i}`, name: 'roads' }, { layer_ref: `layer-${i}`, visible: true },
      { layer_ref: `layer-${i}`, style: { stroke: { color: '#123456' } } }, { layer_ref: `layer-${i}` },
      { longitude: 104.06, latitude: 30.67, zoom: 8 }, { layer_ref: `layer-${i}`, offset: 0, limit: 20 },
      { feature_ref: `feature-${i}` }, { left: { region: { region_name: '成都' } }, right: { geometry: {} }, relation: 'within' },
      { left: { region: { adcode: '510100' } }, right: { geometry: {} }, operation: 'intersection' },
    ][i],
    output: { evidence_ids: [`evidence-${i}`], feature_count: i + 1 },
  }));
  const html = renderToStaticMarkup(<AgentProcess turn={turn('published', items)} defaultExpanded />);
  const titles = ['检索知识库', '导入矢量数据集', '图层显隐控制', '更新矢量样式', '缩放至图层范围',
    '地图视角定位', '要素属性探查', '提取要素空间几何', 'PostGIS 空间关系查询', 'PostGIS 空间拓扑叠加'];
  for (const title of titles) assert.ok(html.includes(title), `missing specific renderer title ${title}`);
  for (let i = 0; i < names.length; i++) assert.ok(html.includes(`call-${i}`), `missing call id ${i}`);
  const expectedFields = ['query', 'file_ref', 'layer_ref', 'style', 'layer_ref', 'longitude', 'offset', 'feature_ref', 'relation', 'operation'];
  items.forEach((item, index) => {
    const body = renderToStaticMarkup(<GenericToolView tool={item} />);
    assert.ok(body.includes(`data-tool-renderer="${item.toolName}"`), `missing keyed renderer ${item.toolName}`);
    assert.ok(body.includes(expectedFields[index]), `missing canonical field ${expectedFields[index]} for ${item.toolName}`);
  });
});

test('long tool payload is bounded and browser cancellation shows receipt or error state', () => {
  const huge = 'x'.repeat(20_000);
  const item: AgentToolItem = {
    kind: 'tool', callId: 'kb-1', toolName: 'retrieve_kb', status: 'failed',
    arguments: { query: huge }, error: 'retrieval failed',
  };
  const html = renderToStaticMarkup(<GenericToolView tool={item} />);
  assert.ok(html.length < 12_000, `unbounded payload rendered (${html.length} chars)`);
  assert.match(html, /ERROR/);
  const browserHtml = renderToStaticMarkup(<GenericToolView tool={{
    kind: 'tool', callId: 'browser-1', toolName: 'locate_map', status: 'cancelled', executionSite: 'browser',
    arguments: { longitude: 104.06, latitude: 30.67 }, error: 'superseded',
    browserReceipt: { status: 'cancelled', runtimeDimension: '2d' },
  }} />);
  assert.match(browserHtml, /ERROR/);
  assert.match(browserHtml, /BROWSER RECEIPT/);
});

test('unknown tool uses bounded generic fallback', () => {
  const html = renderToStaticMarkup(<GenericToolView tool={{
    kind: 'tool', callId: 'unknown-call', toolName: 'future_tool', status: 'failed',
    arguments: { input: 'bounded' }, error: 'failed',
  }} />);
  assert.match(html, /data-tool-renderer="generic"/);
  assert.match(html, /unknown-call/);
  assert.match(html, /INPUT/);
  assert.match(html, /OUTPUT/);
  assert.match(html, /ERROR/);
});

test('successful process collapses by default and failure or interruption stays open without spinner', () => {
  const item: AgentToolItem = { kind: 'tool', callId: 'c', toolName: 'retrieve_kb', status: 'running' };
  const success = renderToStaticMarkup(<AgentProcess turn={turn('published', [{ ...item, status: 'succeeded' }])} />);
  assert.match(success, /aria-expanded="false"/);
  const interrupted = renderToStaticMarkup(<AgentProcess turn={{
    ...turn('running', [item]), interruption: { kind: 'connection_error', message: '连接已断开' },
  }} />);
  assert.match(interrupted, /连接已断开/);
  assert.match(interrupted, /aria-expanded="true"/);
  assert.doesNotMatch(interrupted, /animate-spin|animate-pulse/);
});

test('process header shows the latest review verdict after a revision cycle', () => {
  const html = renderToStaticMarkup(<AgentProcess turn={turn('published', [
    { kind: 'review', verdict: 'REVISE', status: 'completed', summary: '需要收敛', timestamp: '1' },
    { kind: 'review', verdict: 'SUPPORTED', status: 'completed', summary: '支持', timestamp: '2' },
    { kind: 'publication', state: 'published', summary: '发布', timestamp: '3' },
  ])} />);
  assert.match(html, /审查: SUPPORTED/);
  assert.doesNotMatch(html, /审查: REVISE/);
});

test('unexpanded process header bounds content and prevents right boundary clipping', () => {
  const html = renderToStaticMarkup(<AgentProcess turn={turn('published', [
    { kind: 'tool', callId: 'c1', toolName: 'retrieve_kb', status: 'succeeded' },
    { kind: 'review', verdict: 'SUPPORTED', status: 'completed', summary: '支持', timestamp: '1' },
  ])} />);
  assert.match(html, /min-w-0/);
  assert.match(html, /truncate/);
  assert.match(html, /shrink-0 ml-auto/);
  assert.match(html, /whitespace-nowrap/);
});

