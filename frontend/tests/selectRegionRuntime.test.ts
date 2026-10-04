import { strict as assert } from 'node:assert';
import { test } from 'vitest';

import { createFrontendExecutor } from '../src/gis/frontendExecutor';

test('2d executor delegates select_region to the canonical region selector', async () => {
  const calls: Array<Record<string, string>> = [];
  const executor = createFrontendExecutor({
    map: {} as never,
    capabilities: {} as never,
    snapshot: () => ({
      schema_version: 2,
      revision: 1,
      dimension: '2d',
      ready: true,
      supported_tools: ['select_region'],
      viewport: null,
      active_region: null,
      layer_tree: [],
      user_layers: [],
      available_files: [],
    }),
    selectRegion: async (region) => {
      calls.push(region);
      return region;
    },
  });

  const result = await executor.execute('run-1', 'select-1', {
    type: 'select_region',
    target: 'browser_map',
    payload: { adcode: '510000', name: '四川省' },
  });

  assert.deepEqual(result, { adcode: '510000', name: '四川省' });
  assert.deepEqual(calls, [{ adcode: '510000', name: '四川省' }]);
});

test('2d executor rejects incomplete select_region payload', async () => {
  const executor = createFrontendExecutor({
    map: {} as never,
    capabilities: {} as never,
    snapshot: () => ({
      schema_version: 2,
      revision: 1,
      dimension: '2d',
      ready: true,
      supported_tools: ['select_region'],
      viewport: null,
      active_region: null,
      layer_tree: [],
      user_layers: [],
      available_files: [],
    }),
    selectRegion: async (region) => region,
  });

  await assert.rejects(
    executor.execute('run-1', 'select-2', {
      type: 'select_region',
      target: 'browser_map',
      payload: { adcode: '510000' },
    }),
    /缺少行政区/,
  );
});
