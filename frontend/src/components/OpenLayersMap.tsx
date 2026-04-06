import React, { useEffect, useRef, useCallback } from 'react';
import 'ol/ol.css';
import Map from 'ol/Map';
import View from 'ol/View';
import TileLayer from 'ol/layer/Tile';
import VectorLayer from 'ol/layer/Vector';
import VectorSource from 'ol/source/Vector';
import OSM from 'ol/source/OSM';
import { fromLonLat, toLonLat } from 'ol/proj';
import GeoJSON from 'ol/format/GeoJSON';
import { Style, Stroke, Fill } from 'ol/style';
import Feature from 'ol/Feature';
import { easeOut } from 'ol/easing';
import type MapBrowserEvent from 'ol/MapBrowserEvent';
import { useMapStore, INITIAL_VIEW, type ActiveRegion } from '../store/useMapStore';

// ============================================================
//  OpenLayers 2D 地图引擎
//  订阅 useMapStore.activeRegion → 高亮同步 + flyTo
//  切换到 3D 前由 App 读取此引擎的视角写入 Store
// ============================================================

interface OpenLayersMapProps {
  visible: boolean;
  layers: {
    admin: boolean;
    standards: boolean;
    wms: boolean;
  };
}

// ==================== 三态样式 ====================

// 默认：科技黑底 + 极淡边框
const DEFAULT_STYLE = new Style({
  stroke: new Stroke({ color: 'rgba(255, 120, 0, 0.35)', width: 1 }),
  fill: new Fill({ color: 'rgba(255, 120, 0, 0.04)' }),
});

// 悬浮：填充微亮
const HOVER_STYLE = new Style({
  stroke: new Stroke({ color: 'rgba(255, 120, 0, 0.35)', width: 1 }),
  fill: new Fill({ color: 'rgba(255, 140, 40, 0.28)' }),
});

// 选中/高亮：加粗金橙色边框 + 半透明填充（高级感）
const SELECTED_STYLE = new Style({
  stroke: new Stroke({ color: 'rgba(255, 180, 60, 0.95)', width: 3 }),
  fill: new Fill({ color: 'rgba(255, 160, 40, 0.35)' }),
});

const OpenLayersMap: React.FC<OpenLayersMapProps> = ({ visible, layers }) => {
  const mapElement = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const provincesLayerRef = useRef<VectorLayer | null>(null);
  const provincesSourceRef = useRef<VectorSource | null>(null);
  const geoJsonCache = useRef<any>(null);

  // 交互状态
  const hoveredFeatureRef = useRef<Feature | null>(null);
  const selectedFeatureRef = useRef<Feature | null>(null);
  // 防止 store 订阅与自身点击重复触发
  const suppressStoreSync = useRef(false);

  // ==================== Store 引用 ====================
  const setActiveRegion = useMapStore((s) => s.setActiveRegion);
  const setViewState = useMapStore((s) => s.setViewState);

  // ==================== 数据加载 ====================
  const loadProvincesData = useCallback(async () => {
    if (geoJsonCache.current) return geoJsonCache.current;
    try {
      const response = await fetch('http://localhost:8000/api/spatial/provinces?simplify=0.001');
      if (!response.ok) {
        const empty = { type: 'FeatureCollection', features: [] };
        geoJsonCache.current = empty;
        return empty;
      }
      const geoJson = await response.json();
      geoJsonCache.current = geoJson;
      return geoJson;
    } catch (error) {
      console.error('OpenLayers: 加载行政区划数据失败:', error);
      const empty = { type: 'FeatureCollection', features: [] };
      geoJsonCache.current = empty;
      return empty;
    }
  }, []);

  // ==================== flyTo：自适应 extent ====================
  const flyToFeature = useCallback((feature: Feature) => {
    const map = mapRef.current;
    if (!map) return;
    const geometry = feature.getGeometry();
    if (!geometry) return;

    map.getView().fit(geometry.getExtent(), {
      duration: 1800,
      padding: [80, 80, 80, 80],
      easing: easeOut,
      maxZoom: 9,
    });
  }, []);

  // ==================== 高亮同步：根据 adcode 遍历要素 ====================
  const syncHighlight = useCallback((adcode: string | null) => {
    const source = provincesSourceRef.current;
    if (!source) return;

    // 清除旧选中
    if (selectedFeatureRef.current) {
      selectedFeatureRef.current.setStyle(DEFAULT_STYLE);
      selectedFeatureRef.current = null;
    }

    if (!adcode) return;

    // 遍历查找匹配要素
    for (const feature of source.getFeatures()) {
      if (feature.get('adcode') === adcode) {
        feature.setStyle(SELECTED_STYLE);
        selectedFeatureRef.current = feature;
        flyToFeature(feature);
        break;
      }
    }
  }, [flyToFeature]);

  // ==================== 暴露读取当前视角的方法（供外部切换时调用） ====================
  /** 将当前 OL 视角快照写入全局 Store */
  const snapshotViewToStore = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;

    const view = map.getView();
    const center3857 = view.getCenter();
    const zoom = view.getZoom() ?? INITIAL_VIEW.zoom;

    if (center3857) {
      const [lon, lat] = toLonLat(center3857);
      setViewState({ center: [lon, lat], zoom });
    }
  }, [setViewState]);

  // 把 snapshot 方法挂到 DOM 元素上，App 切换模式时可以调用
  useEffect(() => {
    const el = mapElement.current;
    if (el) {
      (el as any).__snapshotView = snapshotViewToStore;
    }
  }, [snapshotViewToStore]);

  // ==================== 订阅 Store: activeRegion 变化 → 高亮 + flyTo ====================
  useEffect(() => {
    const unsub = useMapStore.subscribe(
      (state, prev) => {
        // 只在 flyTrigger 真正变化时响应（避免其他 store 字段更新误触发）
        if (state.flyTrigger === prev.flyTrigger) return;
        if (!visible) return;
        if (suppressStoreSync.current) {
          suppressStoreSync.current = false;
          return;
        }

        if (state.activeRegion) {
          syncHighlight(state.activeRegion.adcode);
        } else {
          // 复位：清除高亮 + 飞回初始视角
          syncHighlight(null);
          const map = mapRef.current;
          if (map) {
            map.getView().animate({
              center: fromLonLat(INITIAL_VIEW.center),
              zoom: INITIAL_VIEW.zoom,
              duration: 1800,
              easing: easeOut,
            });
          }
        }
      }
    );
    return unsub;
  }, [visible, syncHighlight]);

  // ==================== 从 Store 恢复视角（2D 切入时） ====================
  useEffect(() => {
    if (!visible) return;
    const map = mapRef.current;
    if (!map) return;

    // 读取 Store 中的视角参数，无动画地直接设定（视觉欺骗的关键）
    const { center, zoom } = useMapStore.getState().viewState;
    const view = map.getView();
    view.setCenter(fromLonLat(center));
    view.setZoom(zoom);

    // 同时恢复高亮状态
    const region = useMapStore.getState().activeRegion;
    if (region) {
      // 延迟一帧确保数据已加载
      requestAnimationFrame(() => syncHighlight(region.adcode));
    }

    // 刷新尺寸（从 hidden → visible 后 OL 需要重算）
    setTimeout(() => map.updateSize(), 50);
  }, [visible, syncHighlight]);

  // ==================== 初始化地图 + 交互 ====================
  useEffect(() => {
    if (!mapElement.current) return;

    const provincesSource = new VectorSource();
    const provincesLayer = new VectorLayer({
      source: provincesSource,
      style: DEFAULT_STYLE,
    });

    provincesSourceRef.current = provincesSource;
    provincesLayerRef.current = provincesLayer;

    const map = new Map({
      target: mapElement.current,
      layers: [
        new TileLayer({ source: new OSM() }),
        provincesLayer,
      ],
      view: new View({
        center: fromLonLat(INITIAL_VIEW.center),
        zoom: INITIAL_VIEW.zoom,
      }),
      controls: [],
    });

    mapRef.current = map;

    // —————— Hover ——————
    map.on('pointermove', (evt: MapBrowserEvent<PointerEvent>) => {
      if (evt.dragging) return;

      let hit = false;
      map.forEachFeatureAtPixel(
        evt.pixel,
        (feature) => {
          if (hit) return;
          hit = true;
          const f = feature as Feature;

          if (f === selectedFeatureRef.current) return;

          if (hoveredFeatureRef.current && hoveredFeatureRef.current !== f && hoveredFeatureRef.current !== selectedFeatureRef.current) {
            hoveredFeatureRef.current.setStyle(DEFAULT_STYLE);
          }
          if (hoveredFeatureRef.current !== f) {
            f.setStyle(HOVER_STYLE);
            hoveredFeatureRef.current = f;
          }
        },
        { hitTolerance: 2, layerFilter: (l) => l === provincesLayer }
      );

      if (!hit && hoveredFeatureRef.current && hoveredFeatureRef.current !== selectedFeatureRef.current) {
        hoveredFeatureRef.current.setStyle(DEFAULT_STYLE);
        hoveredFeatureRef.current = null;
      }
      map.getTargetElement().style.cursor = hit ? 'pointer' : '';
    });

    // —————— Click → 写入全局 Store ——————
    map.on('singleclick', (evt: MapBrowserEvent<PointerEvent>) => {
      let clicked = false;

      map.forEachFeatureAtPixel(
        evt.pixel,
        (feature) => {
          if (clicked) return;
          clicked = true;
          const f = feature as Feature;
          const adcode = f.get('adcode') as string | undefined;
          if (!adcode) return;

          // 从所有可能的属性字段中提取名称
          const name = (
            f.get('region_name') ||
            f.get('name') ||
            f.get('NAME_ZH') ||
            f.get('province') ||
            ''
          ) as string;

          // Toggle：点击已选中 → 取消
          if (f === selectedFeatureRef.current) {
            f.setStyle(DEFAULT_STYLE);
            selectedFeatureRef.current = null;
            suppressStoreSync.current = true;
            setActiveRegion(null);
            return;
          }

          // 选中：先设本地样式，再写入 Store
          if (selectedFeatureRef.current) {
            selectedFeatureRef.current.setStyle(DEFAULT_STYLE);
          }
          f.setStyle(SELECTED_STYLE);
          selectedFeatureRef.current = f;
          hoveredFeatureRef.current = null;

          flyToFeature(f);

          // 阻止 store 订阅重复触发本组件
          suppressStoreSync.current = true;
          setActiveRegion({ adcode, name });
        },
        { hitTolerance: 2, layerFilter: (l) => l === provincesLayer }
      );
    });

    // 加载行政区划数据
    (async () => {
      const geoJson = await loadProvincesData();
      if (!geoJson || !provincesSourceRef.current) return;

      const format = new GeoJSON();
      const features = format.readFeatures(geoJson, {
        featureProjection: 'EPSG:3857',
        dataProjection: 'EPSG:4326',
      });
      provincesSourceRef.current.clear();
      provincesSourceRef.current.addFeatures(features);
    })();

    return () => {
      map.setTarget(undefined);
    };
  }, [loadProvincesData, flyToFeature, setActiveRegion]);

  // ==================== 图层可见性 ====================
  useEffect(() => {
    if (provincesLayerRef.current) {
      provincesLayerRef.current.setVisible(layers.admin);
    }
  }, [layers]);

  return (
    <div
      ref={mapElement}
      className={visible ? 'w-full h-full' : 'hidden'}
    />
  );
};

export default OpenLayersMap;
