import React, { useEffect, useRef, useCallback } from 'react';
import 'ol/ol.css';
import Map from 'ol/Map';
import View from 'ol/View';
import TileLayer from 'ol/layer/Tile';
import VectorImageLayer from 'ol/layer/VectorImage';
import VectorSource from 'ol/source/Vector';
import XYZ from 'ol/source/XYZ';
import { fromLonLat, toLonLat } from 'ol/proj';
import GeoJSON from 'ol/format/GeoJSON';
import { Style, Stroke, Fill } from 'ol/style';
import Feature from 'ol/Feature';
import { easeOut } from 'ol/easing';
import type MapBrowserEvent from 'ol/MapBrowserEvent';
import { loadProvinceCollection } from '../lib/bootstrap';
import { useMapStore, INITIAL_VIEW, type ActiveRegion } from '../store/useMapStore';

// ============================================================
//  OpenLayers 2D 地图引擎
//  订阅 useMapStore.activeRegion → 高亮同步 + flyTo
//  切换到 3D 前由 App 读取此引擎的视角写入 Store
// ============================================================

interface OpenLayersMapProps {
  visible: boolean;
  theme?: 'light' | 'dark';
  layers: {
    admin: boolean;
    wms: boolean;
  };
  onReady?: () => void;
}

// ==================== 三态样式 ====================

const TECH_ORANGE = '#f07040';

// 默认：极细边框，低透明填充
const DEFAULT_STYLE = new Style({
  stroke: new Stroke({ color: 'rgba(240, 112, 64, 0.25)', width: 1.2 }),
  fill: new Fill({ color: 'rgba(240, 112, 64, 0.08)' }),
});

// 悬浮：中等边框，中透明填充
const HOVER_STYLE = new Style({
  stroke: new Stroke({ color: 'rgba(240, 112, 64, 0.85)', width: 2.2 }),
  fill: new Fill({ color: 'rgba(240, 112, 64, 0.25)' }),
});

// 选中/高亮：加粗边框并模拟发光效果 (双层 Stroke)
const SELECTED_STYLE = [
  new Style({
    stroke: new Stroke({ color: 'rgba(240, 112, 64, 0.3)', width: 8 }),
  }),
  new Style({
    stroke: new Stroke({ color: 'rgba(240, 112, 64, 1.0)', width: 4 }),
    fill: new Fill({ color: 'rgba(240, 112, 64, 0.4)' }),
  })
];

const OpenLayersMap: React.FC<OpenLayersMapProps> = ({ visible, theme = 'dark', layers, onReady }) => {
  const mapElement = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const provincesLayerRef = useRef<VectorImageLayer | null>(null);
  const provincesSourceRef = useRef<VectorSource | null>(null);
  const baseLayersRef = useRef<{ cartoLight?: TileLayer, cartoDark?: TileLayer, tdtCva?: TileLayer, satellite?: TileLayer }>({});
  const geoJsonCache = useRef<any>(null);
  const readyNotifiedRef = useRef(false);
  const onReadyRef = useRef(onReady);

  // 交互状态
  const hoveredFeatureRef = useRef<Feature | null>(null);
  const selectedFeatureRef = useRef<Feature | null>(null);
  // 防止 store 订阅与自身点击重复触发
  const suppressStoreSync = useRef(false);

  // ==================== Store 引用 ====================
  const setActiveRegion = useMapStore((s) => s.setActiveRegion);
  const setViewState = useMapStore((s) => s.setViewState);

  useEffect(() => {
    onReadyRef.current = onReady;
  }, [onReady]);

  const notifyReady = useCallback(() => {
    if (!readyNotifiedRef.current) {
      readyNotifiedRef.current = true;
      onReadyRef.current?.();
    }
  }, []);

  // ==================== 数据加载 ====================
  const loadProvincesData = useCallback(async () => {
    if (geoJsonCache.current) return geoJsonCache.current;
    try {
      const geoJson = await loadProvinceCollection();
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

    const extent = geometry.getExtent();
    const width = extent[2] - extent[0];
    const height = extent[3] - extent[1];
    
    // 宽和高外扩 30% 代表视角减小一档，与 Cesium 计算强一致
    const expandedExtent = [
      extent[0] - width * 0.3,
      extent[1] - height * 0.3,
      extent[2] + width * 0.3,
      extent[3] + height * 0.3,
    ];

    map.getView().fit(expandedExtent, {
      duration: 800,
      padding: [40, 40, 40, 40], // extent 已自带宏大留白，无需过大 padding
      easing: easeOut,
      maxZoom: 9,
    });
  }, []);

  // ==================== 高亮同步：根据 adcode 遍历要素 ====================
  const syncHighlight = useCallback((adcode: string | null, shouldFly = true) => {
    const source = provincesSourceRef.current;
    if (!source) return;

    let styleChanged = false;
    let targetFeature: Feature | null = null;

    if (selectedFeatureRef.current && String(selectedFeatureRef.current.get('adcode')) !== adcode) {
      selectedFeatureRef.current.setStyle(DEFAULT_STYLE);
      selectedFeatureRef.current = null;
      styleChanged = true;
    }

    if (!adcode) {
      if (styleChanged) {
        mapRef.current?.renderSync();
      }
      return;
    }

    for (const feature of source.getFeatures()) {
      if (String(feature.get('adcode')) === adcode) {
        targetFeature = feature;
        break;
      }
    }

    if (!targetFeature) return;

    if (selectedFeatureRef.current !== targetFeature) {
      targetFeature.setStyle(SELECTED_STYLE);
      selectedFeatureRef.current = targetFeature;
      styleChanged = true;
    }

    if (styleChanged) {
      mapRef.current?.renderSync();
    }

    if (shouldFly) {
      setTimeout(() => {
        if (targetFeature) {
          flyToFeature(targetFeature);
        }
      }, 10);
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
              duration: 800,
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

    // 刷新尺寸（从 hidden → visible 后 OL 需要重算）并确保算准后再飞向选中区
    setTimeout(() => {
      map.updateSize();
      const region = useMapStore.getState().activeRegion;
      syncHighlight(region?.adcode ?? null, false);
    }, 100);
  }, [visible, syncHighlight]);

  // ==================== 初始化地图 + 交互 ====================
  useEffect(() => {
    if (!mapElement.current) return;

    const provincesSource = new VectorSource();
    const provincesLayer = new VectorImageLayer({
      source: provincesSource,
      style: DEFAULT_STYLE,
      // 终极优化：使用 VectorImageLayer 将矢量数据预先栅格化成屏幕大小的图片
      // 并且 imageRatio 设置为 2，代表预先渲染出屏幕 2 倍大小的图层快照
      // 这样无论你怎么拖拽、缩放，由于底层只是一张图片在运动，60帧丝滑，也绝对不会出现白框
      imageRatio: 2,
    });

    provincesSourceRef.current = provincesSource;
    provincesLayerRef.current = provincesLayer;

    const TDT_TK = import.meta.env.VITE_TIANDITU_TK || '';
    const getTiandituUrl = (layer: 'vec_w' | 'cva_w' | 'img_w') =>
      `/tianditu/DataServer?T=${layer}&x={x}&y={y}&l={z}&tk=${TDT_TK}`;

    // Same-origin Tianditu vector base map for mainland network reliability.
    const cartoLightLayer = new TileLayer({
      source: new XYZ({
        url: getTiandituUrl('vec_w'),
      }),
      preload: 4,
      visible: !layers.wms && theme === 'light',
    });

    // Dark mode reuses Tianditu through the same proxy for mainland reliability.
    const cartoDarkLayer = new TileLayer({
      source: new XYZ({
        url: getTiandituUrl('vec_w'),
      }),
      preload: 4,
      visible: !layers.wms && theme === 'dark',
    });

    // 天地图中文注记
    const tdtCvaLayer = new TileLayer({
      source: new XYZ({
        url: getTiandituUrl('cva_w'),
      }),
      preload: 4,
      visible: true, // 注记始终保持在上面（如果你希望在卫星下也显示的话。如果没有字就不显示，可以改为 !layers.wms）
    });
    // 如果用户希望保留原有逻辑(wms下没字)：
    tdtCvaLayer.setVisible(!layers.wms);

    // 天地图卫星影像
    const satelliteLayer = new TileLayer({
      source: new XYZ({
        url: getTiandituUrl('img_w'),
      }),
      preload: 4,
      visible: layers.wms,
    });

    baseLayersRef.current = { cartoLight: cartoLightLayer, cartoDark: cartoDarkLayer, tdtCva: tdtCvaLayer, satellite: satelliteLayer };

    const map = new Map({
      target: mapElement.current,
      layers: [
        cartoLightLayer,
        cartoDarkLayer,
        tdtCvaLayer,
        satelliteLayer,
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

    // —————— 鼠标移出画布（即移动到上层UI上方）时，清除悬浮状态避免卡滞 ——————
    const handlePointerLeave = () => {
      if (hoveredFeatureRef.current && hoveredFeatureRef.current !== selectedFeatureRef.current) {
        hoveredFeatureRef.current.setStyle(DEFAULT_STYLE);
        hoveredFeatureRef.current = null;
        map.getTargetElement().style.cursor = '';
      }
    };
    const viewport = map.getViewport();
    viewport.addEventListener('pointerleave', handlePointerLeave);

    // —————— Click → 写入全局 Store ——————
    map.on('singleclick', (evt: MapBrowserEvent<PointerEvent>) => {
      let clicked = false;

      map.forEachFeatureAtPixel(
        evt.pixel,
        (feature) => {
          if (clicked) return;
          clicked = true;
          const f = feature as Feature;
          // DataV adcode 为 number，转为 string 以匹配 Store 类型
          const rawAdcode = f.get('adcode');
          const adcode = rawAdcode != null ? String(rawAdcode) : undefined;
          if (!adcode) return;

          // 从所有可能的属性字段中提取名称（DataV 优先使用 name 字段）
          const name = (
            f.get('name') ||
            f.get('region_name') ||
            f.get('NAME_ZH') ||
            f.get('province') ||
            ''
          ) as string;

          // Toggle：点击已选中 → 取消
          if (f === selectedFeatureRef.current) {
            f.setStyle(DEFAULT_STYLE);
            selectedFeatureRef.current = null;
            map.renderSync(); // 强制立刻重绘清除选中状态
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
          
          if (hoveredFeatureRef.current && hoveredFeatureRef.current !== f) {
            hoveredFeatureRef.current.setStyle(DEFAULT_STYLE);
          }
          hoveredFeatureRef.current = null;

          // 立刻同步重绘，确保将高亮效果烘焙进当前层的缓存再开始飞入动画
          map.renderSync();

          setTimeout(() => {
            flyToFeature(f);
          }, 10);

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
      notifyReady();
    })();

    return () => {
      viewport.removeEventListener('pointerleave', handlePointerLeave);
      map.setTarget(undefined);
    };
  }, [loadProvincesData, flyToFeature, notifyReady, setActiveRegion]);

  // ==================== 图层可见性 ====================
  useEffect(() => {
    if (provincesLayerRef.current) {
      provincesLayerRef.current.setVisible(layers.admin);
    }
    const { cartoLight, cartoDark, tdtCva, satellite } = baseLayersRef.current;
    if (cartoLight && cartoDark && tdtCva && satellite) {
      cartoLight.setVisible(!layers.wms && theme === 'light');
      cartoDark.setVisible(!layers.wms && theme === 'dark');
      tdtCva.setVisible(!layers.wms);
      satellite.setVisible(layers.wms);
    }
  }, [layers, theme]);

  return (
    <div
      ref={mapElement}
      className={visible ? 'w-full h-full' : 'hidden'}
    />
  );
};

export default OpenLayersMap;
