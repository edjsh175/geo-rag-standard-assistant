import React, { useEffect, useRef, useCallback } from 'react';
import * as Cesium from 'cesium';
import 'cesium/Build/Cesium/Widgets/widgets.css';
import { useMapStore, INITIAL_VIEW } from '../store/useMapStore';

// ============================================================
//  Cesium 3D 地球引擎 — 性能优化版
//  核心优化：
//  1. requestRenderMode — 仅在需要时渲染
//  2. 移除 clampToGround polyline（最大性能杀手）
//  3. 节流 MOUSE_MOVE pick 操作
//  4. 点击时才创建加粗边框线（按需渲染）
// ============================================================

declare module 'cesium' {
  interface Entity {
    adcode?: string;
    regionName?: string;
    _associatedPolygonEntity?: Cesium.Entity;
    _associatedOutlineEntity?: Cesium.Entity;
  }
}

interface CesiumGlobeProps {
  visible: boolean;
  theme?: 'light' | 'dark';
  layers: {
    admin: boolean;
    wms: boolean;
  };
}

// ==================== 样式常量 ====================
const TECH_ORANGE = Cesium.Color.fromCssColorString('#f07040');
const STYLE_DEFAULT = {
  material: TECH_ORANGE.withAlpha(0.08),
  outlineColor: TECH_ORANGE.withAlpha(0.35),
  outlineWidth: 1.2,
};
const STYLE_HOVER = {
  material: TECH_ORANGE.withAlpha(0.25),
  outlineColor: TECH_ORANGE.withAlpha(0.85),
  outlineWidth: 2.2,
};
const STYLE_CLICKED = {
  material: TECH_ORANGE.withAlpha(0.4),
  outlineColor: TECH_ORANGE.withAlpha(1.0),
  outlineWidth: 4.0,
};

// 中国全境矩形范围
const CHINA_RECTANGLE = Cesium.Rectangle.fromDegrees(73.0, 12.0, 135.0, 54.0);

const CesiumGlobe: React.FC<CesiumGlobeProps> = ({ visible, theme = 'dark', layers }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<Cesium.Viewer | null>(null);

  const entitiesRef = useRef<Cesium.Entity[]>([]);
  const geoJsonCache = useRef<any>(null);
  const eventHandlerRef = useRef<Cesium.ScreenSpaceEventHandler | null>(null);

  // 交互追踪
  const hoveredEntityRef = useRef<Cesium.Entity | null>(null);
  const clickedEntityRef = useRef<Cesium.Entity | null>(null);

  // O(1) 查找：adcode → 该 adcode 下的所有 polygon 实体
  const entityByAdcodeRef = useRef<Map<string, Cesium.Entity[]>>(new Map());
  // 缓存每个省份扩大后的 Bounding Rectangle，用于精准同频放缩
  const regionRectanglesRef = useRef<Map<string, Cesium.Rectangle>>(new Map());
  const baseLayersRef = useRef<{ cartoLight?: Cesium.ImageryLayer, cartoDark?: Cesium.ImageryLayer, tdtCva?: Cesium.ImageryLayer, satellite?: Cesium.ImageryLayer }>({});
  const suppressStoreSync = useRef(false);

  // 鼠标节流标记
  const pickPending = useRef(false);

  // Store
  const setActiveRegion = useMapStore((s) => s.setActiveRegion);
  const setViewState = useMapStore((s) => s.setViewState);

  // ==================== 请求重绘（requestRenderMode 下必须手动触发） ====================
  const requestRender = useCallback(() => {
    viewerRef.current?.scene.requestRender();
  }, []);

  // ==================== 数据加载 ====================

  const loadProvincesData = useCallback(async () => {
    if (geoJsonCache.current) return geoJsonCache.current;
    try {
      const response = await fetch('/data/china-provinces.json');
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

  // ==================== 要素生成 — 只创建 Polygon 实体（不再给每个面配随行线） ====================

  const createRegionEntitiesFromGeoJson = useCallback((geoJson: any) => {
    const viewer = viewerRef.current;
    if (!viewer || !geoJson || geoJson.features?.length === 0) return;

    geoJson.features.forEach((feature: any, index: number) => {
      const adcode = feature.properties?.adcode != null
        ? String(feature.properties.adcode)
        : undefined;
      const name = feature.properties?.name ||
                   feature.properties?.region_name ||
                   feature.properties?.NAME_ZH ||
                   feature.properties?.province ||
                   '';

      if (!adcode || !feature.geometry) return;

      const geometry = feature.geometry;
      const coordinates = geometry.coordinates;

      // 用于计算整个省的 bounding box
      let minLon = 180, maxLon = -180, minLat = 90, maxLat = -90;
      const updateBounds = (coord: any[]) => {
        minLon = Math.min(minLon, coord[0]);
        maxLon = Math.max(maxLon, coord[0]);
        minLat = Math.min(minLat, coord[1]);
        maxLat = Math.max(maxLat, coord[1]);
      };

      const createPolygon = (polyCoord: any[][], polyIndex: number) => {
        const positions = Cesium.Cartesian3.fromDegreesArray(
          polyCoord[0].flatMap((coord: any[]) => {
            updateBounds(coord);
            return [coord[0], coord[1]];
          })
        );

        const polygonEntity = viewer.entities.add({
          id: `geojson-polygon-${adcode}-${index}-${polyIndex}`,
          name: name,
          polygon: new Cesium.PolygonGraphics({
            hierarchy: new Cesium.PolygonHierarchy(positions),
            material: STYLE_DEFAULT.material,
            // polygon 自带 outline 只能 1px，用伴随 polyline 代替
            outline: false,
          }),
          show: true
        });

        polygonEntity.adcode = adcode;
        polygonEntity.regionName = name;
        entitiesRef.current.push(polygonEntity);

        if (!entityByAdcodeRef.current.has(adcode)) entityByAdcodeRef.current.set(adcode, []);
        entityByAdcodeRef.current.get(adcode)!.push(polygonEntity);

        // 伴随边界线实体（clampToGround 在无地形的 EllipsoidTerrainProvider 上开销极低）
        const outlineEntity = viewer.entities.add({
          id: `geojson-outline-${adcode}-${index}-${polyIndex}`,
          polyline: new Cesium.PolylineGraphics({
            positions: [...positions, positions[0]], // 闭合
            width: STYLE_DEFAULT.outlineWidth,
            material: STYLE_DEFAULT.outlineColor,
            // 关闭 clampToGround 获取最高性能，因为我们在用平面椭球体
          }),
          show: true,
        });

        outlineEntity.adcode = adcode;
        outlineEntity.regionName = name;

        // 面-线互相绑定
        polygonEntity._associatedOutlineEntity = outlineEntity;
        outlineEntity._associatedPolygonEntity = polygonEntity;

        entitiesRef.current.push(outlineEntity);
      };

      if (geometry.type === 'Polygon') {
        createPolygon(coordinates, 0);
      } else if (geometry.type === 'MultiPolygon') {
        coordinates.forEach((polyCoord: any[][], idx: number) => {
          createPolygon(polyCoord, idx);
        });
      }

      // 计算扩展后的全省视角包围盒（宽和高外扩 30% 代表视角减小一档）
      if (minLon < maxLon && minLat < maxLat) {
        const width = maxLon - minLon;
        const height = maxLat - minLat;
        const expandedRect = Cesium.Rectangle.fromDegrees(
          Math.max(-180, minLon - width * 0.3),
          Math.max(-90, minLat - height * 0.3),
          Math.min(180, maxLon + width * 0.3),
          Math.min(90, maxLat + height * 0.3)
        );
        regionRectanglesRef.current.set(adcode, expandedRect);
      }
    });

    requestRender();
  }, [requestRender]);

  // ==================== 样式管理 — 同时处理面填充和伴随边界线 ====================

  const applyEntityStyle = useCallback((entity: Cesium.Entity | null, style: 'default' | 'hover' | 'clicked') => {
    if (!entity) return;

    // 处理多边形填充
    if (entity.polygon) {
      switch (style) {
        case 'clicked':
          (entity.polygon as any).material = STYLE_CLICKED.material;
          break;
        case 'hover':
          (entity.polygon as any).material = STYLE_HOVER.material;
          break;
        default:
          (entity.polygon as any).material = STYLE_DEFAULT.material;
          break;
      }
      // 同步修改伴随边界线
      const outline = entity._associatedOutlineEntity;
      if (outline?.polyline) {
        switch (style) {
          case 'clicked':
            (outline.polyline as any).width = STYLE_CLICKED.outlineWidth;
            (outline.polyline as any).material = STYLE_CLICKED.outlineColor;
            break;
          case 'hover':
            (outline.polyline as any).width = STYLE_HOVER.outlineWidth;
            (outline.polyline as any).material = STYLE_HOVER.outlineColor;
            break;
          default:
            (outline.polyline as any).width = STYLE_DEFAULT.outlineWidth;
            (outline.polyline as any).material = STYLE_DEFAULT.outlineColor;
            break;
        }
      }
    }
  }, []);

  /** 对某 adcode 下所有 polygon 实体（及其伴随线）应用样式 */
  const applyStyleByAdcode = useCallback((adcode: string | undefined, style: 'default' | 'hover' | 'clicked') => {
    if (!adcode) return;
    const entities = entityByAdcodeRef.current.get(adcode);
    if (!entities) return;
    // 只对 polygon 实体调用（它会通过 _associatedOutlineEntity 联动线实体）
    entities.forEach(e => { if (e.polygon) applyEntityStyle(e, style); });
  }, [applyEntityStyle]);

  // ==================== 交互事件 ====================

  const setupScreenSpaceEventHandler = useCallback(() => {
    const viewer = viewerRef.current;
    if (!viewer) return;

    if (eventHandlerRef.current) eventHandlerRef.current.destroy();

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    eventHandlerRef.current = handler;

    // 1. 鼠标悬浮 — RAF 节流，不再每像素都 pick
    handler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.MotionEvent) => {
      if (pickPending.current) return;
      pickPending.current = true;

      requestAnimationFrame(() => {
        pickPending.current = false;
        if (!viewerRef.current) return;

        const pick = viewer.scene.pick(movement.endPosition);
        const entity = (pick?.id instanceof Cesium.Entity) ? pick.id as Cesium.Entity : null;
        // 只关注我们创建的 polygon 实体
        const hoverTarget = entity?.polygon ? entity : null;

        viewer.canvas.style.cursor = hoverTarget ? 'pointer' : 'default';

        const prevAdcode = hoveredEntityRef.current?.adcode;
        const newAdcode = hoverTarget?.adcode;

        if (prevAdcode !== newAdcode) {
          // 恢复旧 hover（但不覆盖 clicked 状态）
          if (prevAdcode && prevAdcode !== clickedEntityRef.current?.adcode) {
            applyStyleByAdcode(prevAdcode, 'default');
          }
          hoveredEntityRef.current = hoverTarget;
          // 应用新 hover（但不覆盖 clicked 状态）
          if (newAdcode && newAdcode !== clickedEntityRef.current?.adcode) {
            applyStyleByAdcode(newAdcode, 'hover');
          }
          requestRender();
        }
      });
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

    // 1.5 鼠标移出画布（即移动到上层UI上方）时，清除悬浮状态避免卡滞
    const handlePointerLeave = () => {
      const prevAdcode = hoveredEntityRef.current?.adcode;
      if (prevAdcode && prevAdcode !== clickedEntityRef.current?.adcode) {
        applyStyleByAdcode(prevAdcode, 'default');
      }
      hoveredEntityRef.current = null;
      viewer.scene.canvas.style.cursor = 'default';
      requestRender();
    };
    viewer.scene.canvas.addEventListener('pointerleave', handlePointerLeave);
    (handler as any)._cleanupPointerLeave = () => {
      viewer.scene.canvas.removeEventListener('pointerleave', handlePointerLeave);
    };

    // 2. 鼠标点击
    handler.setInputAction((movement: Cesium.ScreenSpaceEventHandler.PositionedEvent) => {
      const pick = viewer.scene.pick(movement.position);
      const entity = (pick?.id instanceof Cesium.Entity) ? pick.id as Cesium.Entity : null;
      const clickTarget = entity?.polygon ? entity : null;

      const prevAdcode = clickedEntityRef.current?.adcode;
      const newAdcode = clickTarget?.adcode;

      // —— 点击同一个省（toggle 取消选择）——
      if (newAdcode && newAdcode === prevAdcode) {
        applyStyleByAdcode(prevAdcode, 'default');
        clickedEntityRef.current = null;
        hoveredEntityRef.current = null;

        suppressStoreSync.current = true;
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(INITIAL_VIEW.center[0], INITIAL_VIEW.center[1], INITIAL_VIEW.height),
          orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
          duration: 0.8,
        });
        setActiveRegion(null);
        requestRender();
        return;
      }

      // —— 清除旧选中 ——
      if (prevAdcode) {
        applyStyleByAdcode(prevAdcode, 'default');
      }

      // —— 选中新省份 ——
      if (clickTarget && newAdcode) {
        clickedEntityRef.current = clickTarget;
        applyStyleByAdcode(newAdcode, 'clicked');

        suppressStoreSync.current = true;
        const rect = regionRectanglesRef.current.get(newAdcode);
        if (rect) {
          viewer.camera.flyTo({
            destination: rect,
            duration: 0.8,
            orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 }
          });
        }
        setActiveRegion({
          adcode: newAdcode,
          name: clickTarget.regionName || '',
        });
      } else {
        // —— 点击空白 ——
        clickedEntityRef.current = null;
        suppressStoreSync.current = true;
        viewer.camera.flyTo({
          destination: Cesium.Cartesian3.fromDegrees(INITIAL_VIEW.center[0], INITIAL_VIEW.center[1], INITIAL_VIEW.height),
          orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
          duration: 0.8,
        });
        setActiveRegion(null);
      }

      requestRender();
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    // 禁用右键默认
    viewer.scene.canvas.addEventListener('contextmenu', (e) => e.preventDefault());

  }, [applyStyleByAdcode, setActiveRegion, requestRender]);

  // ==================== 从外部 Store 同步高亮 ====================

  const syncHighlight = useCallback((adcode: string | null, shouldFly = true) => {
    const prevAdcode = clickedEntityRef.current?.adcode;

    if (prevAdcode && prevAdcode !== adcode) {
      applyStyleByAdcode(prevAdcode, 'default');
    }

    if (!adcode) {
      clickedEntityRef.current = null;
      requestRender();
      return;
    }

    const regions = entityByAdcodeRef.current.get(adcode);
    if (!regions || regions.length === 0) return;

    clickedEntityRef.current = regions[0];
    applyStyleByAdcode(adcode, 'clicked');

    if (shouldFly) {
      const viewer = viewerRef.current;
      const rect = regionRectanglesRef.current.get(adcode);
      if (viewer && rect) {
        viewer.camera.flyTo({
          destination: rect,
          duration: 0.8,
          orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 }
        });
      }
    }

    requestRender();
  }, [applyStyleByAdcode, requestRender]);


  const loadAndRenderProvinces = useCallback(async () => {
    const viewer = viewerRef.current;
    if (!viewer || !viewer.entities) return;

    const geoJson = await loadProvincesData();
    if (!geoJson || geoJson.features?.length === 0) return;

    try {
      entitiesRef.current.forEach(entity => viewer.entities.remove(entity));
      entitiesRef.current = [];
      entityByAdcodeRef.current.clear();
      hoveredEntityRef.current = null;
      clickedEntityRef.current = null;

      createRegionEntitiesFromGeoJson(geoJson);
      setupScreenSpaceEventHandler();
    } catch (error) {
      console.error('Cesium: 初始化实体时出错:', error);
    }
  }, [loadProvincesData, createRegionEntitiesFromGeoJson, setupScreenSpaceEventHandler]);

  // ==================== 暴露视角快照 ====================

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

  // ==================== 监听外部 Store 状态变化 ====================

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
          syncHighlight(null);
          const viewer = viewerRef.current;
          if (viewer) {
            viewer.camera.flyTo({
              destination: Cesium.Cartesian3.fromDegrees(INITIAL_VIEW.center[0], INITIAL_VIEW.center[1], INITIAL_VIEW.height),
              orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
              duration: 1.8,
            });
          }
        }
      }
    );
    return unsub;
  }, [visible, syncHighlight]);

  useEffect(() => {
    if (!visible) return;
    const viewer = viewerRef.current;
    if (!viewer) return;

    const { center, height } = useMapStore.getState().viewState;

    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(center[0], center[1], height),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
    });

    const region = useMapStore.getState().activeRegion;
    requestAnimationFrame(() => syncHighlight(region?.adcode ?? null, false));
  }, [visible, syncHighlight]);


  // ==================== Viewer 初始化与卸载 ====================

  useEffect(() => {
    if (!containerRef.current) return;

    const viewer = new Cesium.Viewer(containerRef.current, {
      // ★ 取消地形起伏，使用平面椭球体（省级展示不需要地形，省大量 GPU 和网络开销）
      terrainProvider: new Cesium.EllipsoidTerrainProvider(),
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
      // ★ 性能关键：按需渲染模式，不再 60fps 空转
      requestRenderMode: true,
      maximumRenderTimeChange: Infinity,
      // 禁用默认的版权信息，解决 cdn.jsdelivr.net 的 Tracking Prevention 报错以及加载缓慢
      creditContainer: document.createElement('div'),
    });

    viewerRef.current = viewer;

    // ★ 性能优化：降低后处理开销
    viewer.scene.fog.enabled = false;
    viewer.scene.globe.showGroundAtmosphere = false;
    viewer.scene.skyAtmosphere.show = false;

    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(INITIAL_VIEW.center[0], INITIAL_VIEW.center[1], INITIAL_VIEW.height),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 },
    });

    // 相机运动时自动请求渲染
    viewer.camera.changed.addEventListener(() => {
      viewer.scene.requestRender();
    });
    viewer.camera.percentageChanged = 0.01;

    // ========== 初始化双底图 ==========
    // 获取 Cesium 默认自带的卫星影像地图（作为第一层）
    const defaultSatelliteLayer = viewer.imageryLayers.get(0);

    const TDT_TK = import.meta.env.VITE_TIANDITU_TK || '';
    
    // CartoDB 极简底图（使用 Fastly 全球加速节点，实测不会被代理或墙阻断）
    const cartoLightProvider = new Cesium.UrlTemplateImageryProvider({
      url: 'https://cartodb-basemaps-{s}.global.ssl.fastly.net/light_nolabels/{z}/{x}/{y}.png',
      subdomains: ['a', 'b', 'c', 'd']
    });
    // CartoDB 深色/蓝黑-夜间
    const cartoDarkProvider = new Cesium.UrlTemplateImageryProvider({
      url: 'https://cartodb-basemaps-{s}.global.ssl.fastly.net/dark_nolabels/{z}/{x}/{y}.png',
      subdomains: ['a', 'b', 'c', 'd']
    });

    // 天地图中文注记（透明叠加层）
    const tdtCvaProvider = new Cesium.UrlTemplateImageryProvider({
      url: `/tianditu/DataServer?T=cva_w&x={x}&y={y}&l={z}&tk=${TDT_TK}`,
    });

    // 添加图层
    const cartoLightLayer = viewer.imageryLayers.addImageryProvider(cartoLightProvider);
    const cartoDarkLayer = viewer.imageryLayers.addImageryProvider(cartoDarkProvider);
    const tdtCvaLayer = viewer.imageryLayers.addImageryProvider(tdtCvaProvider);

    // 初始状态 (wms === false 时同时渲染日夜底图，通过透明度控制显示，实现无缝秒切)
    cartoLightLayer.show = !layers.wms;
    cartoLightLayer.alpha = theme === 'light' ? 1.0 : 0.01;
    
    cartoDarkLayer.show = !layers.wms;
    cartoDarkLayer.alpha = theme === 'dark' ? 1.0 : 0.01;
    
    tdtCvaLayer.show = !layers.wms; // 注记层仅在非卫星图下显示，或者都显示，按照原逻辑是!layers.wms
    if (defaultSatelliteLayer) defaultSatelliteLayer.show = layers.wms;

    baseLayersRef.current = { cartoLight: cartoLightLayer, cartoDark: cartoDarkLayer, tdtCva: tdtCvaLayer, satellite: defaultSatelliteLayer };
    // ===================================

    return () => {
      if (eventHandlerRef.current) {
        if ((eventHandlerRef.current as any)._cleanupPointerLeave) {
          (eventHandlerRef.current as any)._cleanupPointerLeave();
        }
        eventHandlerRef.current.destroy();
        eventHandlerRef.current = null;
      }
      if (viewerRef.current) {
        viewerRef.current.destroy();
        viewerRef.current = null;
      }
      entitiesRef.current = [];
      entityByAdcodeRef.current.clear();
      hoveredEntityRef.current = null;
      clickedEntityRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!viewerRef.current) return;
    const timer = setTimeout(() => loadAndRenderProvinces(), 500);
    return () => clearTimeout(timer);
  }, [loadAndRenderProvinces]);

  useEffect(() => {
    if (!viewerRef.current) return;
    
    // 切换行政区划可见性
    if (entitiesRef.current.length > 0) {
      const isVisible = layers.admin;
      entitiesRef.current.forEach(entity => {
        entity.show = isVisible;
      });
    }

    // 切换卫星底图与 Carto 极简底图（使用双加载+透明度切换，避免重新请求闪白）
    const { cartoLight, cartoDark, tdtCva, satellite } = baseLayersRef.current;
    if (cartoLight) {
      cartoLight.show = !layers.wms;
      // 当非激活状态时，设置0.01极小透明度，强制Cesium在后台同步加载此图层，实现切题秒开
      cartoLight.alpha = theme === 'light' ? 1.0 : 0.01;
    }
    if (cartoDark) {
      cartoDark.show = !layers.wms;
      cartoDark.alpha = theme === 'dark' ? 1.0 : 0.01;
    }
    
    if (tdtCva) tdtCva.show = true; // 注记始终保持在上面 (或者 !layers.wms，其实天地图字更清楚，咱们保持它存在，无论模式)
    // 如果用户希望保留原有逻辑(wms下没字)：
    if (tdtCva) tdtCva.show = !layers.wms;

    if (satellite) satellite.show = layers.wms;

    requestRender();
  }, [layers, theme, requestRender]);

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
