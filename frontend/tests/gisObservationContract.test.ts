import { strict as assert } from 'node:assert';
import Collection from 'ol/Collection';
import LayerGroup from 'ol/layer/Group';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import View from 'ol/View';
import { test } from 'vitest';

import { createMapContextReader } from '../src/gis/mapContext';
import { createUserVectorCapabilities } from '../src/gis/userVectorCapabilities';

test('map context exposes the complete recursive layer tree', () => {
  const base = new VectorLayer({ source: new VectorSource() });
  base.set('gisLayerRef', 'system:base');
  base.set('gisLayerName', '基础底图');
  base.set('gisLayerKind', 'base');

  const business = new VectorLayer({ source: new VectorSource() });
  business.set('gisLayerRef', 'system:business');
  business.set('gisLayerName', '业务图层');
  business.set('gisLayerKind', 'business');

  const group = new LayerGroup({ layers: [business] });
  group.set('gisLayerRef', 'system:group');
  group.set('gisLayerName', '业务组');
  group.set('gisLayerKind', 'group');

  const fakeMap = {
    getView: () => ({ getCenter: () => [0, 0], getZoom: () => 5 }),
    getTargetElement: () => ({}),
    getLayers: () => new Collection([base, group]),
  } as never;

  const snapshot = createMapContextReader(fakeMap, () => [])();
  assert.equal(snapshot.schema_version, 2);
  assert.equal(snapshot.layer_tree.length, 2);
  assert.equal(snapshot.layer_tree[0].layer_ref, 'system:base');
  assert.equal(snapshot.layer_tree[1].children?.[0].layer_ref, 'system:business');
});

test('feature refs remain stable across inspect and geometry reads', async () => {
  const view = new View({ center: [0, 0], zoom: 5, projection: 'EPSG:3857' });
  const fakeMap = {
    getView: () => view,
    addLayer: () => undefined,
    removeLayer: () => undefined,
  } as never;
  const capabilities = createUserVectorCapabilities(
    fakeMap,
    () => [0, 0, 0, 0],
    async () => ({
      name: 'test.geojson',
      features: [{
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [104, 30] },
        properties: { name: '测试点', value: 7 },
      }],
    }),
  );

  const imported = await capabilities.importVectorDataset({ file_ref: 'vf_test' });
  const firstInspect = capabilities.inspectFeatures({ layer_ref: imported.layer_ref, offset: 0, limit: 10 });
  const secondInspect = capabilities.inspectFeatures({ layer_ref: imported.layer_ref, offset: 0, limit: 10 });
  assert.equal(firstInspect.features[0].feature_ref, imported.feature_refs[0]);
  assert.equal(secondInspect.features[0].feature_ref, imported.feature_refs[0]);
  assert.equal(firstInspect.features[0].properties.name, '测试点');

  const geometry = capabilities.getFeatureGeometry({ feature_ref: imported.feature_refs[0] });
  assert.equal(geometry.feature_ref, imported.feature_refs[0]);
  assert.equal(geometry.geometry.type, 'Point');
  const [lon, lat] = geometry.geometry.coordinates as number[];
  assert.ok(Math.abs(lon - 104) < 1e-9);
  assert.ok(Math.abs(lat - 30) < 1e-9);
});
