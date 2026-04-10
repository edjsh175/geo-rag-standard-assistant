// 导出所有Cesium相关工具函数
const Cesium = window.Cesium;

// 加载天地图图层
export function loadTdtLayer(viewer, layerName) {
  const Cesium = window.Cesium;
  if (!Cesium) {
    console.error('loadTdtLayer: Cesium未加载');
    return null;
  }
  if (!viewer || !viewer.imageryLayers) {
    console.error('loadTdtLayer: viewer无效');
    return null;
  }
  const TIANDITU_KEY = '84f703f6eea246d74656847e194eeea8'; // 必须替换！
  const imageryProvider = new Cesium.UrlTemplateImageryProvider({
    url: `https://t{s}.tianditu.gov.cn/DataServer?T=${layerName}&x={x}&y={y}&l={z}&tk=${TIANDITU_KEY}`,
    subdomains: ['0', '1', '2', '3', '4', '5', '6', '7'], // 天地图子域名负载均衡
    maximumLevel: 18, // 最大缩放级别
    credit: new Cesium.Credit('天地图 <a href="https://www.tianditu.gov.cn/" target="_blank">www.tianditu.gov.cn</a>')
  });
  const layer = viewer.imageryLayers.addImageryProvider(imageryProvider);
  return layer;
}



// 添加单个要素
export function addSingleFeature(viewer, feature, index, styles) {
  if (!viewer || !viewer.entities) {
    console.error('addSingleFeature: viewer或viewer.entities为undefined');
    return null;
  }
  const { geometry, properties } = feature;
  if (!geometry) return null;

  const entityOptions = {
    id: `geojson-feature-${index}`,
    name: properties?.name || `geojson-feature-${index}`,
    properties: properties || {}, // 保留 GeoJSON 属性
    show: true
  };

  switch (geometry.type) {
    case 'Point':
      entityOptions.position = Cesium.Cartesian3.fromDegrees(
        geometry.coordinates[0],
        geometry.coordinates[1],
        geometry.coordinates[2] || 0
      );
      entityOptions.point = new Cesium.PointGraphics(styles.point);
      break;

    case 'MultiPoint':
      geometry.coordinates.forEach((coord, idx) => {
        viewer.entities.add({
          id: `geojson-multipoint-${index}-${idx}`,
          position: Cesium.Cartesian3.fromDegrees(coord[0], coord[1], coord[2] || 0),
          point: new Cesium.PointGraphics(styles.point),
          properties: properties || {},
          show: true
        });
      });
      return null;

    case 'LineString':
      entityOptions.polyline = new Cesium.PolylineGraphics({
        ...styles.polyline,
        positions: Cesium.Cartesian3.fromDegreesArrayHeights(
          geometry.coordinates.flatMap(coord => [coord[0], coord[1], coord[2] || 0])
        )
      });
      break;

    case 'MultiLineString':
      geometry.coordinates.forEach((lineCoord, idx) => {
        viewer.entities.add({
          id: `geojson-multilinestring-${index}-${idx}`,
          polyline: new Cesium.PolylineGraphics({
            ...styles.polyline,
            positions: Cesium.Cartesian3.fromDegreesArrayHeights(
              lineCoord.flatMap(coord => [coord[0], coord[1], coord[2] || 0])
            )
          }),
          properties: properties || {}
        });
      });
      return null;

    case 'Polygon':
      // 主体面
      entityOptions.polygon = new Cesium.PolygonGraphics({
        ...styles.polygon,
        hierarchy: new Cesium.PolygonHierarchy(
          Cesium.Cartesian3.fromDegreesArrayHeights(
            geometry.coordinates[0].flatMap(coord => [coord[0], coord[1], coord[2] || 0])
          )
        )
      });
      // 【新增】贴地时额外绘制polyline轮廓线
      let polygonOutlineEntity = null;
      if (styles.polygon.clampToGround) {
        polygonOutlineEntity = viewer.entities.add({
          id: `geojson-polygon-outline-${index}`,
          polyline: new Cesium.PolylineGraphics({
            positions: Cesium.Cartesian3.fromDegreesArrayHeights(
              geometry.coordinates[0].flatMap(coord => [coord[0], coord[1], coord[2] || 0])
            ),
            width: styles.polyline?.width || 2,
            material: styles.polygon.outlineColor || Cesium.Color.BLACK,
            clampToGround: true
          }),
          properties: properties || {}
        });
      }
      
      const polygonEntity = viewer.entities.add(entityOptions);
      if (polygonOutlineEntity) {
         polygonEntity._associatedOutlineEntity = polygonOutlineEntity;
         polygonOutlineEntity._associatedPolygonEntity = polygonEntity;
      }
      return polygonEntity;

    case 'MultiPolygon':
      geometry.coordinates.forEach((polyCoord, idx) => {
        // 主体面
        const multiPolyEntity = viewer.entities.add({
          id: `geojson-multipolygon-${index}-${idx}`,
          polygon: new Cesium.PolygonGraphics({
            ...styles.polygon,
            hierarchy: new Cesium.PolygonHierarchy(
              Cesium.Cartesian3.fromDegreesArrayHeights(
                polyCoord[0].flatMap(coord => [coord[0], coord[1], coord[2] || 0])
              )
            )
          }),
          properties: properties || {}
        });
        // 【新增】贴地时额外绘制polyline轮廓线
        if (styles.polygon.clampToGround) {
          const multiPolyOutlineEntity = viewer.entities.add({
            id: `geojson-multipolygon-outline-${index}-${idx}`,
            polyline: new Cesium.PolylineGraphics({
              positions: Cesium.Cartesian3.fromDegreesArrayHeights(
                polyCoord[0].flatMap(coord => [coord[0], coord[1], coord[2] || 0])
              ),
              width: styles.polyline?.width || 2,
              material: styles.polygon.outlineColor || Cesium.Color.BLACK,
              clampToGround: true
            }),
            properties: properties || {}
          });
          multiPolyEntity._associatedOutlineEntity = multiPolyOutlineEntity;
          multiPolyOutlineEntity._associatedPolygonEntity = multiPolyEntity;
        }
      });
      return null;

    default:
      console.warn(`不支持的几何类型：${geometry.type}`);
      return null;
  }

  return viewer.entities.add(entityOptions);
}

// 获取动态样式
export function getDynamicStyles(properties, customColorRules = {}, styleBase = {}) {
  let polygonColor, outlineColor;

  if (Object.keys(customColorRules).length > 0) {
    // 原有自定义规则逻辑
    const matchRule = Object.entries(customColorRules).find(([_, rule]) => {
      return rule.condition(properties);
    });
    if (matchRule) {
      polygonColor = matchRule[1].polygonColor;
      outlineColor = matchRule[1].outlineColor;
    } else {
      polygonColor = Cesium.Color.CYAN.withAlpha(0.2);
      outlineColor = Cesium.Color.CYAN;
    }
  } else {
    // 原有默认配色逻辑
    if (properties?.name?.includes('卡若区')) {
      polygonColor = Cesium.Color.ORANGE.withAlpha(0.3);
      outlineColor = Cesium.Color.ORANGE;
    } else if (properties?.adcode?.startsWith('5404')) {
      polygonColor = Cesium.Color.PURPLE.withAlpha(0.2);
      outlineColor = Cesium.Color.PURPLE;
    } else {
      polygonColor = Cesium.Color.CYAN.withAlpha(0.2);
      outlineColor = Cesium.Color.CYAN;
    }
  }

  // 基础样式合并
  const defaultPoint = { color: Cesium.Color.YELLOW, pixelSize: 10, outlineColor: Cesium.Color.BLACK };
  const defaultPolyline = { width: 4, clampToGround: true };
  // 【修改】去除outlineWidth，Cesium PolygonGraphics不支持自定义宽度
  const defaultPolygon = { outline: true, clampToGround: true }; // 【修改】

  return {
    point: { ...defaultPoint, ...styleBase.point },
    polyline: { ...defaultPolyline, color: outlineColor, ...styleBase.polyline },
    polygon: {
      ...defaultPolygon,
      material: polygonColor,
      outlineColor: outlineColor,
      ...styleBase.polygon
    }
  };
}

// 实现地理区域悬浮与点击交互的统一核心函数
export function implementInteractionEffects(viewer) {
  const Cesium = window.Cesium;
  if (!Cesium) {
    console.error('implementInteractionEffects: Cesium未加载');
    return;
  }
  if (!viewer || !viewer.scene) {
    console.error('implementInteractionEffects: viewer无效');
    return;
  }
  
  let hoveredEntity = null;
  let clickedEntity = null;
  let originalStyles = {};

  const isSameGroup = (e1, e2) => {
    if (!e1 || !e2) return false;
    if (e1 === e2) return true;
    // 把互相绑定的面和边线视为同一组
    const p1 = e1.polygon ? e1 : e1._associatedPolygonEntity;
    const p2 = e2.polygon ? e2 : e2._associatedPolygonEntity;
    if (p1 && p2 && p1 === p2) return true;
    return false;
  };

  const getOriginalStyle = (entity) => {
    if (!originalStyles[entity.id]) {
      originalStyles[entity.id] = {
        polygonColor: entity.polygon ? entity.polygon.material : null,
        lineWidth: entity.polyline ? entity.polyline.width : null,
        lineColor: entity.polyline ? entity.polyline.material : null
      };
    }
    return originalStyles[entity.id];
  };

  const applyStyle = (baseEntity) => {
    if (!baseEntity) return;
    
    let polyEntity = baseEntity.polygon ? baseEntity : baseEntity._associatedPolygonEntity;
    let outlineEntity = baseEntity.polyline ? baseEntity : baseEntity._associatedOutlineEntity;

    const isClicked = isSameGroup(baseEntity, clickedEntity);
    const isHovered = isSameGroup(baseEntity, hoveredEntity);

    if (polyEntity) {
      const orig = getOriginalStyle(polyEntity);
      if (isClicked) {
        polyEntity.polygon.material = Cesium.Color.ORANGE.withAlpha(0.8);
      } else if (isHovered) {
        polyEntity.polygon.material = Cesium.Color.ORANGE.withAlpha(0.6);
      } else {
        if (orig.polygonColor) polyEntity.polygon.material = orig.polygonColor;
      }
    }

    if (outlineEntity) {
      const orig = getOriginalStyle(outlineEntity);
      if (isClicked) {
        outlineEntity.polyline.width = 8.0;
        outlineEntity.polyline.material = Cesium.Color.ORANGE;
      } else if (isHovered) {
        outlineEntity.polyline.width = orig.lineWidth || 2.0;
        outlineEntity.polyline.material = orig.lineColor || Cesium.Color.ORANGE;
      } else {
        if (orig.lineWidth) outlineEntity.polyline.width = orig.lineWidth;
        if (orig.lineColor) outlineEntity.polyline.material = orig.lineColor;
      }
    }
  };

  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

  // 1. 鼠标悬浮事件 (只改变填充色，不改边框粗细)
  handler.setInputAction((movement) => {
    const pick = viewer.scene.pick(movement.endPosition);
    const entity = pick ? pick.id : null;
    
    // 只有悬浮到了不同的区域才刷新
    if (!isSameGroup(entity, hoveredEntity)) {
      const prevHover = hoveredEntity;
      hoveredEntity = entity;
      applyStyle(prevHover);
      applyStyle(hoveredEntity);
    }
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

  // 2. 鼠标点击事件 (选中高亮加粗边框和加深填充色，并伴随视角飞跃)
  handler.setInputAction((movement) => {
    const pick = viewer.scene.pick(movement.position);
    const entity = pick ? pick.id : null;
    
    // 如果点击了不同的实体，并且不在同一个组内
    if (entity !== clickedEntity && !isSameGroup(entity, clickedEntity)) {
      const prevClick = clickedEntity;
      clickedEntity = entity;
      applyStyle(prevClick);
      applyStyle(clickedEntity);
      
      if (clickedEntity) {
        // 选中了新的区域，聚焦到该区域
        viewer.flyTo(clickedEntity, {
          duration: 0.8
        });
      } else {
        // 点击到了空白处，取消之前的选中，并恢复到中国视角
        viewer.camera.flyTo({
          destination: Cesium.Rectangle.fromDegrees(73.0, 15.0, 135.0, 53.0),
          orientation: {
            heading: Cesium.Math.toRadians(0),
            pitch: Cesium.Math.toRadians(-90),
            roll: 0
          },
          duration: 0.8
        });
      }
    } else if (entity && isSameGroup(entity, clickedEntity)) {
      // 点击了当前已经选中的同一个区域（或者它的附属边线），则取消选中
      const prevClick = clickedEntity;
      clickedEntity = null;
      applyStyle(prevClick);
      
      // 恢复视角到中国视角
      viewer.camera.flyTo({
        destination: Cesium.Rectangle.fromDegrees(73.0, 15.0, 135.0, 53.0),
        orientation: {
          heading: Cesium.Math.toRadians(0),
          pitch: Cesium.Math.toRadians(-90),
          roll: 0
        },
        duration: 0.8
      });
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
}

// 加载GeoJSON数据并支持空间查询
export async function loadGeoJsonWithQuerySupport(viewer, geoJsonUrlOrData, options = {}) {
  const Cesium = window.Cesium;
  if (!Cesium) {
    console.error('loadGeoJsonWithQuerySupport: Cesium未加载');
    return null;
  }
  if (!viewer || !viewer.entities) {
    console.error('loadGeoJsonWithQuerySupport: viewer无效');
    return null;
  }
  // 合并默认配置
  const config = {
    customColorRules: {},
    styleBase: {},
    filter: () => true,
    ...options
  };

  try {
    // 加载GeoJSON数据
    const geoJsonData = typeof geoJsonUrlOrData === 'string'
      ? await (await fetch(geoJsonUrlOrData)).json()
      : geoJsonUrlOrData;

    console.log('GeoJSON数据加载成功:', geoJsonData);

    // 输出属性到控制台
    console.log('=== GeoJSON要素属性表 ===');
    const loadedEntities = [];
    const geoJsonLayers = [];

    // 遍历并加载每个要素
    for (let i = 0; i < geoJsonData.features.length; i++) {
      const feature = geoJsonData.features[i];

      // 输出属性到控制台
      console.log(`\n要素 ${i + 1}:`);
      console.log(`  ID: ${feature.id || '无ID'}`);
      console.log(`  类型: ${feature.geometry.type}`);
      console.log(`  属性:`, feature.properties);

      // 过滤要素
      if (config.filter(feature)) {
        // 获取动态样式
        const styles = getDynamicStyles(feature.properties, config.customColorRules, config.styleBase);
        // 添加要素到场景
        addSingleFeature(viewer, feature, i, styles);
        loadedEntities.push(feature);
        // 获取刚添加的实体
        const entity = viewer.entities.getById(`geojson-feature-${i}`);
        if (entity) {
          geoJsonLayers.push(entity);
        }
      }
    }

    console.log(`\n=== 加载完成 ===`);
    console.log(`共加载 ${loadedEntities.length} 个要素`);
    console.log(`原始数据共 ${geoJsonData.features.length} 个要素`);

    return {
      features: loadedEntities,
      layers: geoJsonLayers
    };
  } catch (error) {
    console.error('GeoJSON加载失败:', error);
    throw error;
  }
}

