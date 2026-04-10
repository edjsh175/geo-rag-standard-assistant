import React, { useEffect, useRef, useState } from 'react';
import { loadTdtLayer, loadGeoJsonWithQuerySupport, implementInteractionEffects } from './cesiumUtils';
import { initGlobalLayerManager } from './layerManager';
import Controls from './Controls';
import Sidebar from './Sidebar';
import './styles.css';

const CesiumViewer = () => {
  const cesiumContainer = useRef(null);
  const viewerRef = useRef(null);
  const [viewer, setViewer] = useState(null);
  const [layerManager, setLayerManager] = useState(null);

  // 初始化Cesium Viewer
  useEffect(() => {
    if (!cesiumContainer.current) return;

    const Cesium = window.Cesium;
    if (!Cesium) {
      console.error('Cesium未加载，请检查Cesium脚本是否已引入');
      return;
    }

    Cesium.Ion.defaultAccessToken = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJlOTFlNWMxMi0wNmI4LTQ4Y2UtYWVjNS05ODMzNTBjMzNkY2MiLCJpZCI6MzYyMDc0LCJpYXQiOjE3NjM2MjA5Mzd9.RGlJuqP5RIAlomb9lAzbG2UezOdEiiFqtNt3XXxyJWY';

    const viewer = new Cesium.Viewer(cesiumContainer.current, {
      baseLayerPicker: false,
      terrain: Cesium.Terrain.fromWorldTerrain(),
      navigation: false,
      fullscreenButton: false,
      vrButton: false,
      infoBox: false,
      sceneModePicker: false,
      timeline: false,
      animation: false,
      homeButton: false,
      geocoder: false,
      navigationHelpButton: false,
    });

    viewerRef.current = viewer;
    window._cesiumViewer = viewer;
    setViewer(viewer);

    // 初始化图层管理器（不依赖viewer就绪）
    initGlobalLayerManager();

    // 使用 requestAnimationFrame 确保 Viewer 已附加到 DOM 并初始化
    requestAnimationFrame(() => {
      // Check if viewer still exists and isn't destroyed, and scene is available
      if (!viewer || (viewer.isDestroyed && viewer.isDestroyed()) || !viewer.scene) {
        return;
      }

      try {
        console.log('Cesium Viewer初始化开始');

        // 设置初始视角
        if (viewer.camera) {
          viewer.camera.setView({
            destination: Cesium.Rectangle.fromDegrees(73.0, 15.0, 135.0, 53.0),
            orientation: {
              heading: Cesium.Math.toRadians(0),
              pitch: Cesium.Math.toRadians(-90),
              roll: 0
            }
          });
        }

        // 加载默认图层
        loadDefaultLayers(viewer);

        // 绑定鼠标悬浮和点击选中交互效果
        implementInteractionEffects(viewer);

        // 禁用Cesium默认右键菜单
        if (viewer.scene && viewer.scene.canvas) {
          viewer.scene.canvas.addEventListener('contextmenu', (e) => {
            e.preventDefault();
          });
        }

        console.log('Cesium Viewer初始化完成');
      } catch (error) {
        console.error('Cesium Viewer初始化失败:', error);
      }
    });

    // 清理函数
    return () => {
      if (viewer && !viewer.isDestroyed()) {
        viewer.destroy();
      }
    };
  }, []);

  const loadDefaultLayers = (viewer) => {
    // 加载天地图图层
    const vecLayer = loadTdtLayer(viewer, 'vec_w');
    const cvaLayer = loadTdtLayer(viewer, 'cva_w');
    if (window.layerManager) {
      window.layerManager.addLayer('tdtLayer_vec', '天地图矢量图层', vecLayer, true);
      window.layerManager.addLayer('tdtLayer_cva', '天地图注记图层', cvaLayer, true);
    }

    // 加载GeoJSON数据
    const options = {
      viewer: viewer,
      customColorRules: {
        default: {
          condition: () => true,
          polygonColor: window.Cesium.Color.ORANGE.withAlpha(0.4),
          outlineColor: window.Cesium.Color.ORANGE
        }
      },
      styleBase: {
        polygon: { outlineWidth: 2 },
        polyline: { width: 2 }
      }
    };
    loadGeoJsonWithQuerySupport(viewer, 'https://geo.datav.aliyun.com/areas_v3/bound/540400_full.json', options)
      .then(result => {
        if (window.layerManager && result.layers) {
          result.layers.forEach((layer, index) => {
            window.layerManager.addLayer('jsonLayer_' + index, 'GeoJSON数据图层', layer, true);
          });
        }
      })
      .catch(console.error);

  };

  const handleZoomIn = () => {
    if (viewer) {
      const cartographic = Cesium.Cartographic.fromCartesian(viewer.camera.position);
      const currentHeight = cartographic.height;
      const newHeight = Math.max(currentHeight * 0.7, 1000);
      const targetPosition = Cesium.Cartesian3.fromDegrees(
        viewer.camera.positionCartographic.longitude * (180 / Math.PI),
        viewer.camera.positionCartographic.latitude * (180 / Math.PI),
        newHeight
      );
      viewer.camera.flyTo({
        destination: targetPosition,
        orientation: {
          heading: viewer.camera.heading,
          pitch: viewer.camera.pitch,
          roll: viewer.camera.roll
        },
        duration: 0.8
      });
    }
  };

  const handleZoomOut = () => {
    if (viewer) {
      const cartographic = Cesium.Cartographic.fromCartesian(viewer.camera.position);
      const currentHeight = cartographic.height;
      const newHeight = Math.min(currentHeight * 1.5, 20000000);
      const targetPosition = Cesium.Cartesian3.fromDegrees(
        viewer.camera.positionCartographic.longitude * (180 / Math.PI),
        viewer.camera.positionCartographic.latitude * (180 / Math.PI),
        newHeight
      );
      viewer.camera.flyTo({
        destination: targetPosition,
        orientation: {
          heading: viewer.camera.heading,
          pitch: viewer.camera.pitch,
          roll: viewer.camera.roll
        },
        duration: 0.8
      });
    }
  };

  const handleResetView = () => {
    if (viewer) {
      viewer.camera.flyTo({
        destination: Cesium.Rectangle.fromDegrees(73.0, 15.0, 135.0, 53.0),
        orientation: {
          heading: Cesium.Math.toRadians(0),
          pitch: Cesium.Math.toRadians(-90),
          roll: 0
        }
      });
    }
  };

  const handleViewChange = (viewKey) => {
    if (!viewer) return;
    const viewPositions = {
      china: {
        destination: Cesium.Rectangle.fromDegrees(73.0, 15.0, 135.0, 53.0),
        orientation: { heading: Cesium.Math.toRadians(0), pitch: Cesium.Math.toRadians(-90), roll: 0 }
      },
      beijing: {
        destination: Cesium.Cartesian3.fromDegrees(116.40, 39.76, 15000),
        orientation: { heading: Cesium.Math.toRadians(0), pitch: Cesium.Math.toRadians(-40), roll: 0 }
      },
      shanghai: {
        destination: Cesium.Cartesian3.fromDegrees(121.47, 31.09, 15000),
        orientation: { heading: Cesium.Math.toRadians(0), pitch: Cesium.Math.toRadians(-40), roll: 0 }
      },
      global: {
        destination: Cesium.Cartesian3.fromDegrees(0, 0, 14000000),
        orientation: { heading: Cesium.Math.toRadians(0), pitch: Cesium.Math.toRadians(-90), roll: 0 }
      }
    };
    if (viewPositions[viewKey]) {
      viewer.camera.flyTo(viewPositions[viewKey]);
    }
  };

  const handleLayerToggle = (layerId, isVisible) => {
    if (window.layerManager) {
      window.layerManager.toggleLayer(layerId, isVisible);
    }
  };

  return (
    <div className="cesium-container">
      <div ref={cesiumContainer} className="cesium-viewer" />
      <Controls
        onZoomIn={handleZoomIn}
        onZoomOut={handleZoomOut}
        onResetView={handleResetView}
        onViewChange={handleViewChange}
      />
      <Sidebar
        onLayerToggle={handleLayerToggle}
      />
      <div id="coordDisplay" className="coord-display"></div>
      <div id="queryResult" className="result-panel"></div>
    </div>
  );
};

export default CesiumViewer;