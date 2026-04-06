import React, { useEffect, useRef, useCallback } from 'react';
import * as Cesium from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { useMapStore, INITIAL_VIEW } from '../store/useMapStore';

// ============================================================
//  Cesium 3D 地球引擎 - 分离渲染架构
//  参考原生Cesium源码，实现填充与边框完全剥离渲染
//  订阅 useMapStore.activeRegion → 高亮同步 + flyTo
//  切换到 2D 前由 App 读取此引擎的相机参数写入 Store
// ============================================================

// 扩展 Cesium.Entity，附加 adcode 属性
declare module 'cesium' {
  interface Entity {
    adcode?: string;
    regionName?: string;
    /** 指向对应的轮廓实体（填充实体时）或填充实体（轮廓实体时） */
    pairId?: string;
  }
}

interface CesiumGlobeProps {
  visible: boolean;
  layers: {
    admin: boolean;
    standards: boolean;
    wms: boolean;
  };
}

// ==================== 三态样式配置 ====================

const DEFAULT_FILL = Cesium.Color.fromCssColorString('rgba(255, 120, 0, 0.04)');
const DEFAULT_OUTLINE = Cesium.Color.fromCssColorString('rgba(255, 120, 0, 0.35)');
const DEFAULT_OUTLINE_WIDTH = 1.0;

const HOVER_FILL = Cesium.Color.fromCssColorString('rgba(255, 140, 40, 0.28)');

// 高亮：金橙色边框 + 半透明填充（与 OL 视觉一致）
const SELECTED_FILL = Cesium.Color.fromCssColorString('rgba(255, 160, 40, 0.35)');
const SELECTED_OUTLINE = Cesium.Color.fromCssColorString('rgba(255, 180, 60, 0.95)');
const SELECTED_OUTLINE_WIDTH = 3;

/**
 * 一个行政区划的面+线实体对（分离渲染核心）
 */
interface RegionEntityPair {
  /** 填充多边形实体 */
  fillEntity: Cesium.Entity;
  /** 外轮廓折线实体 */
  outlineEntity: Cesium.Entity;
  /** 行政区划代码 */
  adcode: string;
  /** 区域名称 */
  name: string;
}

/**
 * 应用三态样式 - 分离渲染法
 * 填充多边形负责纯净的透明填充，外挂折线负责边框渲染
 * 参考原生Cesium源码，彻底消除alpha叠加脏块
 */
const applyRegionStyle = (pair: RegionEntityPair, style: 'default' | 'hover' | 'selected') => {
  const { fillEntity, outlineEntity } = pair;

  // 填充色
  const fillColor = style === 'selected' ? SELECTED_FILL
                  : style === 'hover'    ? HOVER_FILL
                  :                        DEFAULT_FILL;

  // 轮廓色与宽度
  const outlineColor = style === 'selected' ? SELECTED_OUTLINE : DEFAULT_OUTLINE;
  const outlineWidth = style === 'selected' ? SELECTED_OUTLINE_WIDTH : DEFAULT_OUTLINE_WIDTH;

  // ── 更新填充多边形 ──
  if (fillEntity.polygon) {
    fillEntity.polygon.material = new Cesium.ColorMaterialProperty(fillColor);
    // 关键：关闭多边形自带的描边，彻底避免脏块
    fillEntity.polygon.outline = new Cesium.ConstantProperty(false);
    fillEntity.polygon.outlineColor = new Cesium.ConstantProperty(Cesium.Color.TRANSPARENT);
    fillEntity.polygon.outlineWidth = new Cesium.ConstantProperty(0);

    // 统一高度 + 测地线弧
    fillEntity.polygon.height = new Cesium.ConstantProperty(0);
    fillEntity.polygon.arcType = new Cesium.ConstantProperty(Cesium.ArcType.GEODESIC);
    fillEntity.polygon.granularity = new Cesium.ConstantProperty(
      Cesium.Math.RADIANS_PER_DEGREE
    );
  }

  // ── 更新外挂轮廓折线 ──
  if (outlineEntity.polyline) {
    outlineEntity.polyline.material = new Cesium.ColorMaterialProperty(outlineColor);
    outlineEntity.polyline.width = new Cesium.ConstantProperty(outlineWidth);
    // 折线贴地，使用独立渲染路径
    outlineEntity.polyline.clampToGround = new Cesium.ConstantProperty(true);
  }
};

// ==================== 主组件 ====================

const CesiumGlobe: React.FC<CesiumGlobeProps> = ({ visible, layers }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);

  // 分离渲染核心存储
  const regionPairsRef = useRef<RegionEntityPair[]>([]);
  const entitiesRef = useRef<Cesium.Entity[]>([]);
  const geoJsonCache = useRef<any>(null);
  const eventHandlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);

  // 交互状态 - 存储RegionEntityPair引用
  const hoveredPairRef = useRef<RegionEntityPair | null>(null);
  const selectedPairRef = useRef<RegionEntityPair | null>(null);
  const suppressStoreSync = useRef(false);

  // MOUSE_MOVE 节流：全程 useRef，零 React 重渲染
  const lastPickTimeRef = useRef(0);
  const PICK_THROTTLE_MS = 50;

  // ==================== Store 引用 ====================
  const setActiveRegion = useMapStore((s) => s.setActiveRegion);
  const setViewState = useMapStore((s) => s.setViewState);

  // ==================== 数据加载与分离渲染构建 ====================
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
      console.error('Cesium: 加载行政区划数据失败:', error);
      const empty = { type: 'FeatureCollection', features: [] };
      geoJsonCache.current = empty;
      return empty;
    }
  }, []);

  /**
   * 从GeoJSON创建分离渲染的实体对
   * 参考原生Cesium源码，每个多边形生成填充实体+轮廓折线实体
   */
  const createRegionEntitiesFromGeoJson = useCallback((geoJson: any): RegionEntityPair[] => {
    if (!geoJson || geoJson.features?.length === 0) return [];

    const pairs: RegionEntityPair[] = [];

    geoJson.features.forEach((feature: any) => {
      const adcode = feature.properties?.adcode;
      const name = feature.properties?.region_name ||
                   feature.properties?.name ||
                   feature.properties?.NAME_ZH ||
                   feature.properties?.province ||
                   '';

      if (!adcode || !feature.geometry) return;

      const geometry = feature.geometry;
      const coordinates = geometry.coordinates;

      // 为每个多边形（或多多边形）创建实体对
      if (geometry.type === 'Polygon') {
        createPolygonEntityPair(coordinates, adcode, name, pairs);
      } else if (geometry.type === 'MultiPolygon') {
        coordinates.forEach((polygonCoords: any[][]) => {
          createPolygonEntityPair(polygonCoords, adcode, name, pairs);
        });
      }
    });

    return pairs;
  }, []);

  /**
   * 创建单个多边形的填充+轮廓实体对
   */
  const createPolygonEntityPair = (
    polygonCoords: any[][],
    adcode: string,
    name: string,
    pairs: RegionEntityPair[]
  ) => {
    const pairId = `pair-${adcode}-${pairs.length}`;

    // 创建填充多边形实体
    const fillEntity = new Cesium.Entity({
      id: `fill-${pairId}`,
      polygon: {
        hierarchy: new Cesium.ConstantProperty(Cesium.Cartesian3.fromDegreesArrayHeights(
          polygonCoords[0].flatMap(([lon, lat]) => [lon, lat, 0])
        )),
        material: new Cesium.ColorMaterialProperty(DEFAULT_FILL),
        outline: new Cesium.ConstantProperty(false), // 关键：禁用自带描边
        outlineColor: new Cesium.ConstantProperty(Cesium.Color.TRANSPARENT),
        outlineWidth: new Cesium.ConstantProperty(0),
        height: new Cesium.ConstantProperty(0),
        arcType: Cesium.ArcType.GEODESIC,
        granularity: Cesium.Math.RADIANS_PER_DEGREE,
      }
    });

    fillEntity.adcode = adcode;
    fillEntity.regionName = name;
    fillEntity.pairId = pairId;

    // 创建外挂轮廓折线实体
    const outlineEntity = new Cesium.Entity({
      id: `outline-${pairId}`,
      polyline: {
        positions: new Cesium.ConstantProperty(Cesium.Cartesian3.fromDegreesArrayHeights(
          polygonCoords[0].flatMap(([lon, lat]) => [lon, lat, 0])
        )),
        material: new Cesium.ColorMaterialProperty(DEFAULT_OUTLINE),
        width: new Cesium.ConstantProperty(DEFAULT_OUTLINE_WIDTH),
        clampToGround: new Cesium.ConstantProperty(true),
      }
    });

    outlineEntity.adcode = adcode;
    outlineEntity.regionName = name;
    outlineEntity.pairId = pairId;

    pairs.push({ fillEntity, outlineEntity, adcode, name });
  };

  // ==================== 交互事件处理 ====================
  const setupScreenSpaceEventHandler = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;

    if (eventHandlerRef.current) eventHandlerRef.current.destroy();

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    eventHandlerRef.current = handler;

    // ── MOUSE_MOVE: 原生防抖拦截 + 实体短路 ──
    handler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.MotionEvent) => {
      if (!viewer) return;

      // 节流：距上次 pick 不足 PICK_THROTTLE_MS 则跳过
      const now = performance.now();
      if (now - lastPickTimeRef.current < PICK_THROTTLE_MS) return;
      lastPickTimeRef.current = now;

      const picked = viewer.scene.pick(movement.endPosition);

      // 鼠标移出所有实体
      if (!picked || !picked.id) {
        if (hoveredPairRef.current && hoveredPairRef.current !== selectedPairRef.current) {
          applyRegionStyle(hoveredPairRef.current, 'default');
          hoveredPairRef.current = null;
        }
        viewer.canvas.style.cursor = 'default';
        return;
      }

      const entity = picked.id as Cesium.Entity;
      if (!entity.polygon || !entity.adcode) return;

      viewer.canvas.style.cursor = 'pointer';

      // 获取对应的实体对
      const pair = regionPairsRef.current.find(p => p.fillEntity === entity);
      if (!pair) return;

      // ── 短路：同一实体对不重复处理（核心防卡顿） ──
      if (pair === hoveredPairRef.current) return;
      // 已选中的实体对不覆盖为 hover 样式
      if (pair === selectedPairRef.current) return;

      // 清除上一个 hover
      if (hoveredPairRef.current && hoveredPairRef.current !== selectedPairRef.current) {
        applyRegionStyle(hoveredPairRef.current, 'default');
      }

      applyRegionStyle(pair, 'hover');
      hoveredPairRef.current = pair;
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    // ── CLICK → 写入全局 Store ──
    handler.setInputAction((click: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      if (!viewer) return;

      const picked = viewer.scene.pick(click.position);
      if (!picked || !picked.id) return;

      const entity = picked.id as Cesium.Entity;
      if (!entity.polygon || !entity.adcode) return;

      const pair = regionPairsRef.current.find(p => p.fillEntity === entity);
      if (!pair) return;

      const { adcode, name } = pair;

      // Toggle：点击已选中 → 取消
      if (pair === selectedPairRef.current) {
        applyRegionStyle(pair, 'default');
        selectedPairRef.current = null;
        suppressStoreSync.current = true;
        setActiveRegion(null);
        return;
      }

      // 清除之前选中
      if (selectedPairRef.current) {
        applyRegionStyle(selectedPairRef.current, 'default');
      }

      applyRegionStyle(pair, 'selected');
      selectedPairRef.current = pair;
      hoveredPairRef.current = null;

      // flyTo 动画（飞到填充实体）
      viewer.flyTo(pair.fillEntity, {
        duration: 1.8,
        offset: new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-35), 0),
        maximumHeight: 2500000,
      }).catch(() => {});

      suppressStoreSync.current = true;
      setActiveRegion({ adcode, name });
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
  }, [setActiveRegion]);

  // ==================== 数据加载与分离渲染初始化 ====================
  const loadAndRenderProvinces = useCallback(async () => {
    const viewer = viewerRef.current;
    if (!viewer || !viewer.entities) return;

    const geoJson = await loadProvincesData();
    if (!geoJson || geoJson.features?.length === 0) return;

    try {
      // 清空现有实体
      entitiesRef.current.forEach(entity => viewer.entities.remove(entity));
      regionPairsRef.current = [];
      entitiesRef.current = [];

      // 创建分离渲染实体对
      const pairs = createRegionEntitiesFromGeoJson(geoJson);
      regionPairsRef.current = pairs;

      // 添加到 Viewer
      pairs.forEach(pair => {
        viewer.entities.add(pair.fillEntity);
        viewer.entities.add(pair.outlineEntity);
        entitiesRef.current.push(pair.fillEntity, pair.outlineEntity);

        // 初始应用默认样式
        applyRegionStyle(pair, 'default');
      });

      setupScreenSpaceEventHandler();
    } catch (error) {
      console.error('Cesium: 分离渲染初始化失败:', error);
    }
  }, [loadProvincesData, createRegionEntitiesFromGeoJson, setupScreenSpaceEventHandler]);

  // ==================== 高亮同步 ====================
  const syncHighlight = useCallback((adcode: string | null) => {
    const pairs = regionPairsRef.current;
    if (!pairs.length) return;

    // 清除旧选中
    if (selectedPairRef.current) {
      applyRegionStyle(selectedPairRef.current, 'default');
      selectedPairRef.current = null;
    }
    if (!adcode) return;

    const viewer = viewerRef.current;

    for (const pair of pairs) {
      if (pair.adcode === adcode) {
        applyRegionStyle(pair, 'selected');
        selectedPairRef.current = pair;

        // flyTo
        if (viewer) {
          viewer.flyTo(pair.fillEntity, {
            duration: 1.8,
            offset: new Cesium.HeadingPitchRange(0, Cesium.Math.toRadians(-35), 0),
            maximumHeight: 2500000,
          }).catch(() => {});
        }
        break;
      }
    }
  }, []);

  // ==================== 暴露视角快照方法 ====================
  const snapshotViewToStore = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;

    const pos = viewer.camera.positionCartographic;
    const lon = Cesium.Math.toDegrees(pos.longitude);
    const lat = Cesium.Math.toDegrees(pos.latitude);
    const height = pos.height;

    setViewState({ center: [lon, lat], height });
  }, [setViewState]);

  useEffect(() => {
    const el = containerRef.current;
    if (el) {
      (el as any).__snapshotView = snapshotViewToStore;
    }
  }, [snapshotViewToStore]);

  // ==================== 订阅 Store: activeRegion 变化 ====================
  useEffect(() => {
    const unsub = useMapStore.subscribe(
      (state, prev) => {
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
          const viewer = viewerRef.current;
          if (viewer) {
            viewer.camera.flyTo({
              destination: Cesium.Cartesian3.fromDegrees(
                INITIAL_VIEW.center[0],
                INITIAL_VIEW.center[1],
                INITIAL_VIEW.height
              ),
              orientation: {
                heading: Cesium.Math.toRadians(0),
                pitch: Cesium.Math.toRadians(-45),
                roll: 0.0,
              },
              duration: 1.8,
            });
          }
        }
      }
    );
    return unsub;
  }, [visible, syncHighlight]);

  // ==================== 从 Store 恢复视角（3D 切入时）====================
  useEffect(() => {
    if (!visible) return;
    const viewer = viewerRef.current;
    if (!viewer) return;

    const { center, height } = useMapStore.getState().viewState;

    // 无动画直接设定（"视觉欺骗"核心）
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(center[0], center[1], height),
      orientation: {
        heading: Cesium.Math.toRadians(0),
        pitch: Cesium.Math.toRadians(-45),
        roll: 0.0,
      },
    });

    // 恢复高亮
    const region = useMapStore.getState().activeRegion;
    if (region) {
      requestAnimationFrame(() => syncHighlight(region.adcode));
    }
  }, [visible, syncHighlight]);

  // ==================== 初始化 Viewer ====================
  useEffect(() => {
    if (!containerRef.current) return;

    const viewer = new Cesium.Viewer(containerRef.current, {
      terrain: Cesium.Terrain.fromWorldTerrain(),
      animation: false,
      baseLayerPicker: false,
      fullscreenButton: false,
      geocoder: false,
      homeButton: false,
      infoBox: false,
      sceneModePicker: false,
      selectionIndicator: false,
      timeline: false,
      navigationHelpButton: false,
      navigationInstructionsInitiallyVisible: false,
      scene3DOnly: true,
    });

    viewerRef.current = viewer;

    // 初始视角
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(
        INITIAL_VIEW.center[0],
        INITIAL_VIEW.center[1],
        INITIAL_VIEW.height
      ),
      orientation: {
        heading: Cesium.Math.toRadians(0),
        pitch: Cesium.Math.toRadians(-45),
        roll: 0.0,
      },
    });

    return () => {
      if (eventHandlerRef.current) {
        eventHandlerRef.current.destroy();
        eventHandlerRef.current = null;
      }
      if (viewerRef.current) {
        viewerRef.current.destroy();
        viewerRef.current = null;
      }
      regionPairsRef.current = [];
      entitiesRef.current = [];
      hoveredPairRef.current = null;
      selectedPairRef.current = null;
    };
  }, []);

  // 加载数据
  useEffect(() => {
    if (!viewerRef.current) return;
    const timer = setTimeout(() => loadAndRenderProvinces(), 500);
    return () => clearTimeout(timer);
  }, [loadAndRenderProvinces]);

  // 图层可见性
  useEffect(() => {
    if (!viewerRef.current || !entitiesRef.current.length) return;

    const isVisible = layers.admin;
    entitiesRef.current.forEach(entity => {
      (entity as any).show = new Cesium.ConstantProperty(isVisible);
    });
  }, [layers]);

  return (
    <div
      id="cesiumContainer"
      ref={containerRef}
      className={visible ? 'block' : 'hidden'}
      style={{ width: '100%', height: '100%', position: 'relative', pointerEvents: 'auto' }}
    />
  );
};

export default CesiumGlobe;
