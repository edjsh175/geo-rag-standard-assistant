import type OlMap from 'ol/Map';
import { fromLonLat } from 'ol/proj';
import type { BrowserMapAction, BrowserMapContext } from './contracts';
import { GisExecutionError } from './contracts';

const canonical = (value: unknown): string => {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value as Record<string, unknown>).sort().map((key) => `${JSON.stringify(key)}:${canonical((value as Record<string, unknown>)[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
};

export const createFrontendExecutor = ({
  map,
  capabilities,
  snapshot,
}: {
  map: OlMap;
  capabilities: ReturnType<typeof import('./userVectorCapabilities').createUserVectorCapabilities>;
  snapshot: () => BrowserMapContext;
}) => {
  const calls = new globalThis.Map<string, { signature: string; promise: Promise<Record<string, unknown>> }>();
  let queue = Promise.resolve();
  return {
    execute(runId: string, toolCallId: string, action: BrowserMapAction) {
      if (!runId || !toolCallId) return Promise.reject(new GisExecutionError('INVALID_TOOL_CALL', '缺少调用标识'));
      const signature = `${action.type}:${canonical(action.payload ?? {})}`;
      const key = `${runId}:${toolCallId}`;
      const known = calls.get(key);
      if (known) {
        if (known.signature !== signature) return Promise.reject(new GisExecutionError('TOOL_CALL_CONFLICT', '同一 tool_call_id 的参数发生冲突'));
        return known.promise;
      }
      const payload = structuredClone(action.payload ?? {});
      const promise = queue.then(async () => {
        switch (action.type) {
          case 'import_vector_dataset':
            return capabilities.importVectorDataset({ file_ref: String(payload.file_ref ?? ''), name: typeof payload.name === 'string' ? payload.name : undefined });
          case 'set_layer_visibility':
            return capabilities.setVisibility({ layer_ref: String(payload.layer_ref ?? ''), visible: Boolean(payload.visible) });
          case 'set_vector_style':
            if (!payload.style || typeof payload.style !== 'object') throw new GisExecutionError('INVALID_TOOL_CALL', '缺少 style');
            return capabilities.setVectorStyle({ layer_ref: String(payload.layer_ref ?? ''), style: payload.style as never });
          case 'fit_vector_layer':
            return capabilities.fit({ layer_ref: String(payload.layer_ref ?? '') });
          case 'inspect_layer_features':
            return capabilities.inspectFeatures({
              layer_ref: String(payload.layer_ref ?? ''),
              offset: Number(payload.offset ?? 0),
              limit: Number(payload.limit ?? 20),
            });
          case 'get_feature_geometry':
            return capabilities.getFeatureGeometry({ feature_ref: String(payload.feature_ref ?? '') });
          case 'locate_map': {
            const longitude = Number(payload.longitude);
            const latitude = Number(payload.latitude);
            const zoom = Number(payload.zoom ?? map.getView().getZoom() ?? 10);
            if (!Number.isFinite(longitude) || !Number.isFinite(latitude) || !Number.isFinite(zoom)) {
              throw new GisExecutionError('INVALID_TOOL_CALL', '定位参数无效');
            }
            await new Promise<void>((resolve, reject) => {
              map.getView().animate(
                { center: fromLonLat([longitude, latitude]), zoom, duration: 500 },
                (completed) => completed ? resolve() : reject(new GisExecutionError('OPERATION_CANCELLED', '地图视图操作未完成')),
              );
            });
            return { center: [longitude, latitude], zoom };
          }
          default:
            throw new GisExecutionError('UNSUPPORTED_TOOL', `不支持的 GIS 工具: ${action.type}`);
        }
      });
      calls.set(key, { signature, promise });
      queue = promise.then(() => undefined, () => undefined);
      return promise;
    },
    snapshot,
  };
};
