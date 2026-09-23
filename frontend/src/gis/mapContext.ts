import type Map from 'ol/Map';
import type BaseLayer from 'ol/layer/Base';
import LayerGroup from 'ol/layer/Group';
import { toLonLat } from 'ol/proj';
import type { BrowserMapContext, LayerTreeNode, UserVectorLayerState } from './contracts';
import { listVectorDatasets } from './fileReferenceStore';

export const createMapContextReader = (map: Map, readUserLayers: () => UserVectorLayerState[]) => {
  let revision = 0;
  let signature = '';
  return () => {
    const center3857 = map.getView().getCenter();
    const center = center3857 ? toLonLat(center3857) : null;
    const zoom = map.getView().getZoom();
    const mapLayer = (layer: BaseLayer, parentRef?: string, index = 0): LayerTreeNode => {
      const fallbackRef = parentRef ? `${parentRef}:${index}` : `map:${index}`;
      const layerRef = String(layer.get('gisLayerRef') ?? layer.get('gisUserLayerRef') ?? fallbackRef);
      const node: LayerTreeNode = {
        layer_ref: layerRef,
        parent_ref: parentRef,
        name: String(layer.get('gisLayerName') ?? layer.get('gisUserLayerName') ?? layerRef),
        kind: (layer.get('gisLayerKind') ?? (layer.get('gisUserLayerRef') ? 'user_vector' : layer instanceof LayerGroup ? 'group' : 'unknown')) as LayerTreeNode['kind'],
        visible: layer.getVisible(),
        opacity: layer.getOpacity(),
        z_index: layer.getZIndex(),
      };
      if (layer instanceof LayerGroup) node.children = layer.getLayers().getArray().map((child, childIndex) => mapLayer(child, layerRef, childIndex));
      return node;
    };
    const context = {
      schema_version: 2 as const,
      dimension: '2d' as const,
      ready: Boolean(map.getTargetElement()),
      supported_tools: ['import_vector_dataset', 'set_layer_visibility', 'set_vector_style', 'fit_vector_layer', 'locate_map', 'inspect_layer_features', 'get_feature_geometry'],
      viewport: center && Number.isFinite(zoom)
        ? { center: [center[0], center[1]] as [number, number], zoom: zoom!, crs: 'EPSG:4326' as const }
        : null,
      layer_tree: map.getLayers().getArray().map((layer, index) => mapLayer(layer, undefined, index)),
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
