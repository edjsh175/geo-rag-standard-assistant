import * as Cesium from 'cesium';

export function initMeasurement(viewer, updateMeasureResultCallback) {
  let measureMode = null; // 'distance', 'area', or null
  let measurePoints = [];
  let measureEntities = [];
  let measureHandler = null;

  // 切换测量模式
  function toggleMeasureMode(mode) {
    // 如果当前已经是该模式，则退出
    if (measureMode === mode) {
      clearMeasurement();
      return;
    }

    // 清除之前的测量
    clearMeasurement();

    // 设置当前模式
    measureMode = mode;

    // 初始化测量
    initMeasurement();
  }

  // 初始化测量
  function initMeasurement() {
    // 创建屏幕空间事件处理器
    measureHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

    // 设置鼠标点击事件
    measureHandler.setInputAction(function(click) {
      // 获取点击位置的地理坐标
      const cartesian = viewer.scene.pickPosition(click.position);
      if (!cartesian) return;

      // 添加测量点
      addMeasurePoint(cartesian);

      // 更新测量结果
      updateMeasurement();
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    // 设置鼠标移动事件（用于绘制临时线/面）
    measureHandler.setInputAction(function(movement) {
      if (measurePoints.length === 0) return;

      // 获取鼠标位置的地理坐标
      const cartesian = viewer.scene.pickPosition(movement.endPosition);
      if (!cartesian) return;

      // 更新临时测量结果
      updateTempMeasurement(cartesian);
    }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
  }

  // 添加测量点
  function addMeasurePoint(cartesian) {
    // 添加点到数组
    measurePoints.push(cartesian);

    // 创建点实体
    const pointEntity = viewer.entities.add({
      position: cartesian,
      point: {
        pixelSize: 8,
        color: Cesium.Color.RED,
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2
      }
    });

    // 添加到测量实体数组
    measureEntities.push(pointEntity);
  }

  // 更新临时测量结果
  function updateTempMeasurement(cartesian) {
    // 清除之前的临时实体
    if (measureEntities.length > measurePoints.length) {
      viewer.entities.remove(measureEntities[measureEntities.length - 1]);
      measureEntities.pop();
    }

    // 创建临时点数组
    const tempPoints = [...measurePoints, cartesian];

    // 根据测量模式创建临时线或面
    if (measureMode === 'distance') {
      // 创建临时线
      const polylineEntity = viewer.entities.add({
        polyline: {
          positions: tempPoints,
          width: 2,
          material: Cesium.Color.YELLOW
        }
      });
      measureEntities.push(polylineEntity);

      // 计算临时距离
      const distance = calculateDistance(tempPoints);
      updateMeasureResultCallback(distance, tempPoints.length - 1);
    } else if (measureMode === 'area') {
      // 创建临时面
      const polygonEntity = viewer.entities.add({
        polygon: {
          hierarchy: new Cesium.PolygonHierarchy(tempPoints),
          material: Cesium.Color.YELLOW.withAlpha(0.2),
          outline: true,
          outlineColor: Cesium.Color.YELLOW,
          outlineWidth: 2
        }
      });
      measureEntities.push(polygonEntity);

      // 计算临时面积
      const area = calculateArea(tempPoints);
      updateMeasureResultCallback(area, tempPoints.length - 1);
    }
  }

  // 更新测量结果
  function updateMeasurement() {
    // 清除之前的非点实体
    while (measureEntities.length > measurePoints.length) {
      viewer.entities.remove(measureEntities[measurePoints.length]);
      measureEntities.splice(measurePoints.length, 1);
    }

    // 如果点数量不足，不绘制
    if (measurePoints.length < 2) {
      return;
    }

    // 根据测量模式创建线或面
    if (measureMode === 'distance') {
      // 创建线
      const polylineEntity = viewer.entities.add({
        polyline: {
          positions: measurePoints,
          width: 2,
          material: Cesium.Color.YELLOW
        }
      });
      measureEntities.push(polylineEntity);

      // 计算距离
      const distance = calculateDistance(measurePoints);
      updateMeasureResultCallback(distance, measurePoints.length - 1);
    } else if (measureMode === 'area' && measurePoints.length >= 3) {
      // 创建面
      const polygonEntity = viewer.entities.add({
        polygon: {
          hierarchy: new Cesium.PolygonHierarchy(measurePoints),
          material: Cesium.Color.YELLOW.withAlpha(0.2),
          outline: true,
          outlineColor: Cesium.Color.YELLOW,
          outlineWidth: 2
        }
      });
      measureEntities.push(polygonEntity);

      // 计算面积
      const area = calculateArea(measurePoints);
      updateMeasureResultCallback(area, measurePoints.length - 1);
    }
  }

  // 计算距离
  function calculateDistance(points) {
    let totalDistance = 0;
    const distances = [];

    for (let i = 0; i < points.length - 1; i++) {
      const distance = Cesium.Cartesian3.distance(points[i], points[i + 1]);
      distances.push(distance);
      totalDistance += distance;
    }

    return {
      total: totalDistance,
      segments: distances
    };
  }

  // 计算面积
  function calculateArea(points) {
    if (points.length < 3) return 0;

    // 使用多边形面积计算算法
    let area = 0;

    // 将Cartesian3转换为经纬度
    const positions = points.map(point => {
      const cartographic = Cesium.Cartographic.fromCartesian(point);
      return {
        lon: Cesium.Math.toDegrees(cartographic.longitude),
        lat: Cesium.Math.toDegrees(cartographic.latitude),
        alt: cartographic.height
      };
    });

    // 计算多边形面积（使用球面多边形面积算法）
    const R = 6371000; // 地球半径，单位米

    for (let i = 0; i < positions.length; i++) {
      const j = (i + 1) % positions.length;
      const lon1 = Cesium.Math.toRadians(positions[i].lon);
      const lon2 = Cesium.Math.toRadians(positions[j].lon);
      const lat1 = Cesium.Math.toRadians(positions[i].lat);
      const lat2 = Cesium.Math.toRadians(positions[j].lat);

      const dlon = lon2 - lon1;
      const dlat = lat2 - lat1;

      const a = Math.sin(dlat/2) * Math.sin(dlat/2) +
              Math.cos(lat1) * Math.cos(lat2) *
              Math.sin(dlon/2) * Math.sin(dlon/2);
      const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
      const d = R * c;

      // 累加面积
      area += (lon2 - lon1) * Math.sin((lat1 + lat2) / 2);
    }

    area = Math.abs(area) * R * R;

    return {
      total: area,
      segments: []
    };
  }

  // 格式化距离显示
  function formatDistance(distance) {
    if (distance < 1000) {
      return distance.toFixed(2) + ' 米';
    } else {
      return (distance / 1000).toFixed(2) + ' 千米';
    }
  }

  // 格式化面积显示
  function formatArea(area) {
    if (area < 1000000) {
      return area.toLocaleString() + ' 平方米';
    } else {
      return (area / 1000000).toFixed(2) + ' 平方千米';
    }
  }

  // 清除测量
  function clearMeasurement() {
    // 重置测量模式
    measureMode = null;

    // 清除测量点
    measurePoints = [];

    // 移除测量实体
    measureEntities.forEach(entity => {
      viewer.entities.remove(entity);
    });
    measureEntities = [];

    // 移除事件处理器
    if (measureHandler) {
      measureHandler.destroy();
      measureHandler = null;
    }

    // 清空测量结果
    updateMeasureResultCallback(null, 0);
  }

  // 返回公共方法
  return {
    toggleMeasureMode,
    clearMeasurement,
    getMeasureMode: () => measureMode
  };
}