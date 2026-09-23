import GeoJSON from 'ol/format/GeoJSON';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import { Circle as CircleStyle, Fill, Stroke, Style } from 'ol/style';
import type Map from 'ol/Map';
import type { VectorStyle } from './contracts';
import { GisExecutionError } from './contracts';

const rgba = (hex: string, opacity: number) => {
  const value = hex.slice(1);
  return `rgba(${parseInt(value.slice(0, 2), 16)}, ${parseInt(value.slice(2, 4), 16)}, ${parseInt(value.slice(4, 6), 16)}, ${opacity})`;
};

const styleFunction = (style: VectorStyle) => {
  const stroke = new Stroke({ color: rgba(style.stroke.color, style.stroke.opacity), width: style.stroke.width });
  const fill = new Fill({ color: rgba(style.fill.color, style.fill.opacity) });
  const point = new Style({ image: new CircleStyle({ radius: style.radius, fill, stroke }) });
  const line = new Style({ stroke });
  const polygon = new Style({ stroke, fill });
  return (feature: import('ol/Feature').default) => {
    const type = feature.getGeometry()?.getType();
    if (type === 'Point' || type === 'MultiPoint') return point;
    if (type === 'LineString' || type === 'MultiLineString') return line;
    return polygon;
  };
};

export const createUserVectorLayer = (
  map: Map,
  features: Array<Record<string, unknown>>,
  options: { layerRef: string; name: string; style: VectorStyle },
) => {
  const formatter = new GeoJSON();
  const converted = formatter.readFeatures({ type: 'FeatureCollection', features } as never, {
    dataProjection: 'EPSG:4326',
    featureProjection: map.getView().getProjection(),
  });
  if (!converted.length || converted.some((feature) => !feature.getGeometry()?.getExtent().every(Number.isFinite))) {
    throw new GisExecutionError('INVALID_GEOMETRY', '矢量数据包含无效几何');
  }
  const source = new VectorSource({ features: converted });
  const layer = new VectorLayer({ source, visible: true });
  layer.set('gisUserLayerRef', options.layerRef);
  layer.set('gisUserLayerName', options.name);
  layer.setStyle(styleFunction(options.style));
  map.addLayer(layer);
  return {
    layer,
    features: converted,
    featureCount: converted.length,
    geometryTypes: [...new Set(converted.map((item) => item.getGeometry()?.getType()).filter(Boolean))] as string[],
  };
};

export const setUserVectorStyle = (layer: VectorLayer<VectorSource>, style: VectorStyle) => layer.setStyle(styleFunction(style));
export const setUserVectorVisibility = (layer: VectorLayer<VectorSource>, visible: boolean) => layer.setVisible(visible);
