import { strict as assert } from 'node:assert';
import { test } from 'vitest';

import { createCesiumGisRuntime } from '../src/gis/cesiumRuntime';
import { executeBrowserTool, registerBrowserGisRuntime, setActiveBrowserGisRuntime } from '../src/gis/browserBridge';

test('invalid coordinates produce a failed 3d receipt without moving the camera', async () => {
  let moves = 0;
  const runtime = createCesiumGisRuntime({
    readState: () => ({ ready: true, center: [104, 30], zoom: 5, adminVisible: true, satelliteVisible: false }),
    locateMap: async () => { moves += 1; return {}; },
    setLayerVisibility: async () => ({}),
  });
  const unregister = registerBrowserGisRuntime('3d', runtime);
  setActiveBrowserGisRuntime('3d');
  try {
    for (const [longitude, latitude] of [[999, 999], [-181, 30], [104, 91]]) {
      const receipt = await executeBrowserTool('invalid-location', `${longitude}:${latitude}`, {
        type: 'locate_map', target: 'browser_map', payload: { longitude, latitude },
      });
      assert.equal(receipt.status, 'failed');
      assert.equal(receipt.tool_name, 'locate_map');
      assert.deepEqual(receipt.map_context?.viewport.center, [104, 30]);
    }
    assert.equal(moves, 0);
  } finally {
    unregister();
  }
});

test('cesium runtime exposes only implemented 3d tools and logical map state', () => {
  const runtime = createCesiumGisRuntime({
    readState: () => ({
      ready: true,
      center: [104, 30],
      zoom: 5,
      adminVisible: true,
      satelliteVisible: false,
    }),
    locateMap: async () => ({ center: [104, 30], zoom: 6 }),
    setLayerVisibility: async (layerRef, visible) => ({ layer_ref: layerRef, visible }),
  });

  const snapshot = runtime.snapshot();
  assert.equal(snapshot.dimension, '3d');
  assert.deepEqual(snapshot.supported_tools, ['locate_map', 'set_layer_visibility']);
  assert.equal(snapshot.layer_tree.find((item) => item.layer_ref === 'system:provinces')?.visible, true);
  assert.equal(snapshot.layer_tree.find((item) => item.layer_ref === 'base:vector')?.visible, true);
  assert.equal(snapshot.layer_tree.find((item) => item.layer_ref === 'base:satellite')?.visible, false);
});

test('cesium runtime delegates locate and logical layer visibility actions', async () => {
  const calls: Array<Record<string, unknown>> = [];
  const runtime = createCesiumGisRuntime({
    readState: () => ({
      ready: true,
      center: [104, 30],
      zoom: 5,
      adminVisible: true,
      satelliteVisible: false,
    }),
    locateMap: async (input) => {
      calls.push({ type: 'locate', ...input });
      return { center: [input.longitude, input.latitude], zoom: input.zoom ?? 5 };
    },
    setLayerVisibility: async (layerRef, visible) => {
      calls.push({ type: 'visibility', layerRef, visible });
      return { layer_ref: layerRef, visible };
    },
  });

  await runtime.execute('run-1', 'call-1', {
    type: 'locate_map',
    target: 'browser_map',
    payload: { longitude: 106.5, latitude: 29.5, zoom: 7 },
  });
  await runtime.execute('run-1', 'call-2', {
    type: 'set_layer_visibility',
    target: 'browser_map',
    payload: { layer_ref: 'system:provinces', visible: false },
  });

  assert.deepEqual(calls, [
    { type: 'locate', longitude: 106.5, latitude: 29.5, zoom: 7 },
    { type: 'visibility', layerRef: 'system:provinces', visible: false },
  ]);
});
