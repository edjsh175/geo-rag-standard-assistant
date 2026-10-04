import type Map from 'ol/Map';
import type BaseLayer from 'ol/layer/Base';
import LayerGroup from 'ol/layer/Group';
import { toLonLat } from 'ol/proj';
import type { BrowserMapContext, LayerTreeNode, UserVectorLayerState } from './contracts';
import { listVectorDatasets } from './fileReferenceStore';
import { useMapStore } from '../store/useMapStore';

export const createMapContextReader = (map: Map, readUserLayers: () => UserVectorLayerState[]) => {
  let revision = 0;
  let signature = '';
  return () => {
    const userLayers = readUserLayers();
    const availableFiles = listVectorDatasets();
    // import_vector_dataset is always listed so the controller can attempt it with any
    // file_ref (including missing ones); the executor returns a failure receipt in that case.
    const supportedTools = ['locate_map', 'set_layer_visibility', 'import_vector_dataset', 'render_geojson_layer'];
    const hasSelectableRegions = map.getLayers().getArray().some((layer) => {
      if (String(layer.get('gisLayerRef') ?? '') !== 'system:provinces') return false;
      const source = (layer as any).getSource?.();
      return Array.isArray(source?.getFeatures?.()) && source.getFeatures().length > 0;
    });
    if (hasSelectableRegions) supportedTools.push('select_region');
    if (userLayers.length > 0) {
      supportedTools.push('set_vector_style', 'fit_vector_layer', 'inspect_layer_features');
    }
    // get_feature_geometry is always listed so the controller can attempt it with any
    // feature_ref (including missing ones); the executor returns a failure receipt in that case.
    supportedTools.push('get_feature_geometry');
    void availableFiles; // still serialized in context for the controller to read
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
      supported_tools: supportedTools,
      viewport: center && Number.isFinite(zoom)
        ? { center: [center[0], center[1]] as [number, number], zoom: zoom!, crs: 'EPSG:4326' as const }
        : null,
      active_region: useMapStore.getState().activeRegion ? { ...useMapStore.getState().activeRegion! } : null,
      layer_tree: map.getLayers().getArray().map((layer, index) => mapLayer(layer, undefined, index)),
      user_layers: userLayers,
      available_files: availableFiles,
    };
    const next = JSON.stringify(context);
    if (next !== signature) {
      revision += 1;
      signature = next;
    }
    return { ...context, revision } satisfies BrowserMapContext;
  };
};
