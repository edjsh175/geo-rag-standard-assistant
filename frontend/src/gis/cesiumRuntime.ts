import type { BrowserMapAction, BrowserMapContext } from './contracts';
import { GisExecutionError } from './contracts';

export interface CesiumRuntimeState {
  ready: boolean;
  center: [number, number];
  zoom: number;
  adminVisible: boolean;
  satelliteVisible: boolean;
}

export const createCesiumGisRuntime = ({
  readState,
  locateMap,
  setLayerVisibility,
}: {
  readState: () => CesiumRuntimeState;
  locateMap: (input: { longitude: number; latitude: number; zoom?: number }) => Promise<Record<string, unknown>>;
  setLayerVisibility: (layerRef: string, visible: boolean) => Promise<Record<string, unknown>>;
}) => {
  let revision = 0;
  let signature = '';

  const snapshot = (): BrowserMapContext => {
    const state = readState();
    const context = {
      schema_version: 2 as const,
      dimension: '3d' as const,
      ready: state.ready,
      supported_tools: ['locate_map', 'set_layer_visibility'],
      viewport: {
        center: state.center,
        zoom: state.zoom,
        crs: 'EPSG:4326' as const,
      },
      layer_tree: [
        {
          layer_ref: 'system:provinces',
          name: '行政区划',
          kind: 'business' as const,
          visible: state.adminVisible,
          opacity: 1,
        },
        {
          layer_ref: 'base:vector',
          name: '矢量底图',
          kind: 'base' as const,
          visible: !state.satelliteVisible,
          opacity: 1,
        },
        {
          layer_ref: 'base:satellite',
          name: '卫星影像',
          kind: 'base' as const,
          visible: state.satelliteVisible,
          opacity: 1,
        },
      ],
      user_layers: [],
      available_files: [],
    };
    const next = JSON.stringify(context);
    if (next !== signature) {
      revision += 1;
      signature = next;
    }
    return { ...context, revision };
  };

  return {
    snapshot,
    async execute(_runId: string, _toolCallId: string, action: BrowserMapAction) {
      const payload = action.payload ?? {};
      switch (action.type) {
        case 'locate_map': {
          const longitude = Number(payload.longitude);
          const latitude = Number(payload.latitude);
          const zoom = payload.zoom == null ? undefined : Number(payload.zoom);
          if (!Number.isFinite(longitude) || !Number.isFinite(latitude) || (zoom != null && !Number.isFinite(zoom))) {
            throw new GisExecutionError('INVALID_TOOL_CALL', '定位参数无效');
          }
          return locateMap({ longitude, latitude, zoom });
        }
        case 'set_layer_visibility': {
          const layerRef = String(payload.layer_ref ?? '');
          if (!['system:provinces', 'base:vector', 'base:satellite'].includes(layerRef)) {
            throw new GisExecutionError('UNKNOWN_LAYER', `图层不存在: ${layerRef}`);
          }
          return setLayerVisibility(layerRef, Boolean(payload.visible));
        }
        default:
          throw new GisExecutionError('UNSUPPORTED_TOOL', `不支持的 3D GIS 工具: ${action.type}`);
      }
    },
  };
};
