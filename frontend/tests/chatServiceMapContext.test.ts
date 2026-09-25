import { strict as assert } from 'node:assert';
import { test } from 'vitest';

import { registerBrowserGisRuntime, setActiveBrowserGisRuntime } from '../src/gis/browserBridge';
import { withActiveMapContext } from '../src/services/chatService';

test('shared chat request helper attaches the active map context', () => {
  const unregister = registerBrowserGisRuntime('3d', {
    execute: async () => ({}),
    snapshot: () => ({
      schema_version: 2,
      revision: 4,
      dimension: '3d',
      ready: true,
      supported_tools: ['locate_map'],
      viewport: { center: [104, 30], zoom: 5, crs: 'EPSG:4326' },
      layer_tree: [],
      user_layers: [],
      available_files: [],
    }),
  });

  try {
    setActiveBrowserGisRuntime('3d');
    const request = withActiveMapContext({
      query: '定位成都',
      use_generation: true,
    });
    assert.equal(request.map_context?.dimension, '3d');
    assert.deepEqual(request.map_context?.supported_tools, ['locate_map']);
  } finally {
    unregister();
  }
});
