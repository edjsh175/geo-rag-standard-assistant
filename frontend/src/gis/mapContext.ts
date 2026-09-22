import type Map from 'ol/Map';
import { toLonLat } from 'ol/proj';
import type { BrowserMapContext, UserVectorLayerState } from './contracts';
import { listVectorDatasets } from './fileReferenceStore';

export const createMapContextReader = (map: Map, readUserLayers: () => UserVectorLayerState[]) => {
  let revision = 0;
  let signature = '';
  return () => {
    const center3857 = map.getView().getCenter();
    const center = center3857 ? toLonLat(center3857) : null;
    const zoom = map.getView().getZoom();
    const context = {
      schema_version: 1 as const,
      dimension: '2d' as const,
      ready: Boolean(map.getTargetElement()),
      supported_tools: ['import_vector_dataset', 'set_layer_visibility', 'set_vector_style', 'fit_vector_layer', 'locate_map'],
      viewport: center && Number.isFinite(zoom)
        ? { center: [center[0], center[1]] as [number, number], zoom: zoom!, crs: 'EPSG:4326' as const }
        : null,
      user_layers: readUserLayers(),
      available_files: listVectorDatasets(),
    };
    const next = JSON.stringify(context);
    if (next !== signature) {
      revision += 1;
      signature = next;
    }
    return { ...context, revision } satisfies BrowserMapContext;
  };
};
