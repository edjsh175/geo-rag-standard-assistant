import type OlMap from 'ol/Map';
import type VectorLayer from 'ol/layer/Vector';
import type VectorSource from 'ol/source/Vector';
import GeoJSON from 'ol/format/GeoJSON';
import type Feature from 'ol/Feature';
import type Geometry from 'ol/geom/Geometry';
import type { FeatureObservation, UserVectorLayerState, VectorStylePatch } from './contracts';
import { GisExecutionError } from './contracts';
import { readVectorDataset } from './readVectorDataset';
import { createUserVectorLayer, setUserVectorStyle, setUserVectorVisibility } from './openlayersAdapter';
import { defaultVectorStyle, mergeVectorStyle } from './styleContract';

type FeatureState = { feature_ref: string; layer_ref: string; feature: Feature<Geometry> };
type RecordState = UserVectorLayerState & { layer: VectorLayer<VectorSource>; features: FeatureState[] };

export const createUserVectorCapabilities = (
  map: OlMap,
  getFitPadding: () => number[],
  readDataset = readVectorDataset,
) => {
  const records = new globalThis.Map<string, RecordState>();
  const featureIndex = new globalThis.Map<string, FeatureState>();
  const geojson = new GeoJSON();
  const summary = (record: RecordState): UserVectorLayerState => ({
    layer_ref: record.layer_ref,
    name: record.name,
    geometry_types: [...record.geometry_types],
    feature_count: record.feature_count,
    feature_refs: record.features.slice(0, 10).map((item) => item.feature_ref),
    visible: record.layer.getVisible(),
    style: structuredClone(record.style),
  });
  const get = (layerRef: string) => {
    const record = records.get(layerRef);
    if (!record) throw new GisExecutionError('UNKNOWN_USER_LAYER', `图层不存在: ${layerRef}`);
    return record;
  };
  return {
    list: () => [...records.values()].map(summary),
    async importVectorDataset(input: { file_ref: string; name?: string }) {
      const parsed = await readDataset(input.file_ref);
      const layerRef = `ul_${crypto.randomUUID()}`;
      const style = defaultVectorStyle();
      const created = createUserVectorLayer(map, parsed.features, { layerRef, name: input.name || parsed.name, style });
      const features = created.features.map((feature) => {
        const featureState: FeatureState = { feature_ref: `uf_${crypto.randomUUID()}`, layer_ref: layerRef, feature };
        feature.set('gisFeatureRef', featureState.feature_ref, true);
        featureIndex.set(featureState.feature_ref, featureState);
        return featureState;
      });
      const record: RecordState = {
        layer_ref: layerRef,
        name: input.name || parsed.name,
        geometry_types: created.geometryTypes,
        feature_count: created.featureCount,
        feature_refs: features.slice(0, 10).map((item) => item.feature_ref),
        visible: true,
        style,
        layer: created.layer,
        features,
      };
      records.set(layerRef, record);
      return summary(record);
    },
    inspectFeatures(input: { layer_ref: string; offset: number; limit: number }) {
      const record = get(input.layer_ref);
      const offset = Math.max(0, Math.trunc(input.offset));
      const limit = Math.min(50, Math.max(1, Math.trunc(input.limit)));
      const features: FeatureObservation[] = record.features.slice(offset, offset + limit).map((item) => ({
        feature_ref: item.feature_ref,
        layer_ref: item.layer_ref,
        geometry_type: item.feature.getGeometry()?.getType() ?? null,
        properties: Object.fromEntries(Object.entries(item.feature.getProperties()).filter(([key]) => key !== 'geometry')),
      }));
      return { layer_ref: input.layer_ref, offset, limit, total: record.features.length, features };
    },
    getFeatureGeometry(input: { feature_ref: string }) {
      const item = featureIndex.get(input.feature_ref);
      if (!item) throw new GisExecutionError('UNKNOWN_FEATURE', `要素不存在: ${input.feature_ref}`);
      const geometry = item.feature.getGeometry();
      if (!geometry) throw new GisExecutionError('INVALID_GEOMETRY', '要素没有有效几何');
      return {
        feature_ref: item.feature_ref,
        layer_ref: item.layer_ref,
        geometry: geojson.writeGeometryObject(geometry, { featureProjection: map.getView().getProjection(), dataProjection: 'EPSG:4326' }),
        properties: Object.fromEntries(Object.entries(item.feature.getProperties()).filter(([key]) => key !== 'geometry')),
      };
    },
    setVectorStyle(input: { layer_ref: string; style: VectorStylePatch }) {
      const record = get(input.layer_ref);
      record.style = mergeVectorStyle(record.style, input.style);
      setUserVectorStyle(record.layer, record.style);
      return summary(record);
    },
    setVisibility(input: { layer_ref: string; visible: boolean }) {
      const record = get(input.layer_ref);
      setUserVectorVisibility(record.layer, input.visible);
      return { layer_ref: input.layer_ref, visible: record.layer.getVisible() };
    },
    async fit(input: { layer_ref: string }) {
      const record = get(input.layer_ref);
      const extent = record.layer.getSource()?.getExtent();
      if (!extent?.every(Number.isFinite)) throw new GisExecutionError('EMPTY_VECTOR_DATASET', '图层没有有效范围');
      await new Promise<void>((resolve, reject) => {
        map.getView().fit(extent, {
          duration: 500,
          padding: getFitPadding(),
          maxZoom: 14,
          callback: (completed) => completed ? resolve() : reject(new GisExecutionError('OPERATION_CANCELLED', '地图视图操作未完成')),
        });
      });
      return { layer_ref: input.layer_ref, feature_count: record.feature_count };
    },
    dispose() {
      for (const record of records.values()) map.removeLayer(record.layer);
      records.clear();
      featureIndex.clear();
    },
  };
};
