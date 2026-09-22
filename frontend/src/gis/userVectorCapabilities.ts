import type OlMap from 'ol/Map';
import type VectorLayer from 'ol/layer/Vector';
import type VectorSource from 'ol/source/Vector';
import type { UserVectorLayerState, VectorStylePatch } from './contracts';
import { GisExecutionError } from './contracts';
import { readVectorDataset } from './readVectorDataset';
import { createUserVectorLayer, setUserVectorStyle, setUserVectorVisibility } from './openlayersAdapter';
import { defaultVectorStyle, mergeVectorStyle } from './styleContract';

type RecordState = UserVectorLayerState & { layer: VectorLayer<VectorSource> };

export const createUserVectorCapabilities = (map: OlMap, getFitPadding: () => number[]) => {
  const records = new globalThis.Map<string, RecordState>();
  const summary = (record: RecordState): UserVectorLayerState => ({
    layer_ref: record.layer_ref,
    name: record.name,
    geometry_types: [...record.geometry_types],
    feature_count: record.feature_count,
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
      const parsed = await readVectorDataset(input.file_ref);
      const layerRef = `ul_${crypto.randomUUID()}`;
      const style = defaultVectorStyle();
      const created = createUserVectorLayer(map, parsed.features, { layerRef, name: input.name || parsed.name, style });
      const record: RecordState = {
        layer_ref: layerRef,
        name: input.name || parsed.name,
        geometry_types: created.geometryTypes,
        feature_count: created.featureCount,
        visible: true,
        style,
        layer: created.layer,
      };
      records.set(layerRef, record);
      return summary(record);
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
    },
  };
};
