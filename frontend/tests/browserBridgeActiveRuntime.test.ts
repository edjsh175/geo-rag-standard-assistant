import { strict as assert } from 'node:assert';
import { test } from 'vitest';

import {
  executeBrowserTool,
  getBrowserMapContext,
  registerBrowserGisRuntime,
  setActiveBrowserGisRuntime,
} from '../src/gis/browserBridge';
import type { BrowserMapContext } from '../src/gis/contracts';

const context = (dimension: '2d' | '3d', supportedTools: string[]): BrowserMapContext => ({
  schema_version: 2,
  revision: 1,
  dimension,
  ready: true,
  supported_tools: supportedTools,
  viewport: { center: [104, 30], zoom: 5, crs: 'EPSG:4326' },
  layer_tree: [],
  user_layers: [],
  available_files: [],
});

test('browser bridge reads and executes only the active map runtime', async () => {
  const calls: string[] = [];
  const unregister2d = registerBrowserGisRuntime('2d', {
    snapshot: () => context('2d', ['import_vector_dataset']),
    execute: async () => {
      calls.push('2d');
      return { engine: '2d' };
    },
  });
  const unregister3d = registerBrowserGisRuntime('3d', {
    snapshot: () => context('3d', ['locate_map']),
    execute: async () => {
      calls.push('3d');
      return { engine: '3d' };
    },
  });

  try {
    setActiveBrowserGisRuntime('3d');
    assert.equal(getBrowserMapContext()?.dimension, '3d');
    const threeDReceipt = await executeBrowserTool(
      'run-1',
      'call-1',
      { type: 'locate_map', target: 'browser_map', payload: { longitude: 104, latitude: 30, zoom: 6 } },
    );
    assert.equal(threeDReceipt.status, 'succeeded');
    assert.deepEqual(calls, ['3d']);

    setActiveBrowserGisRuntime('2d');
    assert.equal(getBrowserMapContext()?.dimension, '2d');
    const twoDReceipt = await executeBrowserTool(
      'run-2',
      'call-2',
      { type: 'import_vector_dataset', target: 'browser_map', payload: { file_ref: 'vf_1' } },
    );
    assert.equal(twoDReceipt.status, 'succeeded');
    assert.deepEqual(calls, ['3d', '2d']);
  } finally {
    unregister2d();
    unregister3d();
  }
});

test('browser bridge rejects a tool not declared by the active runtime', async () => {
  let executions = 0;
  const unregister = registerBrowserGisRuntime('3d', {
    snapshot: () => context('3d', ['locate_map']),
    execute: async () => {
      executions += 1;
      return {};
    },
  });

  try {
    setActiveBrowserGisRuntime('3d');
    const receipt = await executeBrowserTool(
      'run-3',
      'call-3',
      { type: 'set_vector_style', target: 'browser_map', payload: { layer_ref: 'ul_1', style: {} } },
    );
    assert.equal(receipt.status, 'failed');
    assert.match(receipt.error ?? '', /not supported|不支持/i);
    assert.equal(executions, 0);
  } finally {
    unregister();
  }
});

test('browser bridge does not execute tools before the active map runtime is ready', async () => {
  let executions = 0;
  const unregister = registerBrowserGisRuntime('3d', {
    snapshot: () => ({ ...context('3d', ['locate_map']), ready: false }),
    execute: async () => {
      executions += 1;
      return {};
    },
  });

  try {
    setActiveBrowserGisRuntime('3d');
    const receipt = await executeBrowserTool(
      'run-not-ready',
      'call-not-ready',
      { type: 'locate_map', target: 'browser_map', payload: { longitude: 104, latitude: 30 } },
    );
    assert.equal(receipt.status, 'failed');
    assert.match(receipt.error ?? '', /not ready|未就绪/i);
    assert.equal(executions, 0);
  } finally {
    unregister();
  }
});
