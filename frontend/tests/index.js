function loadTdtLayer(viewer, layerName) {
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

async function loadArcGISLayer(viewer, layerName) {
  // 示例：使用 ArcGIS 官方示例服务（世界地形底图）
  const arcgisDynamicProvider = await Cesium.ArcGisMapServerImageryProvider.fromUrl(
    `https://sampleserver6.arcgisonline.com/arcgis/rest/services/${layerName}/MapServer`, {
    // token: "<ArcGIS Access Token>"
  });
  viewer.imageryLayers.addImageryProvider(arcgisDynamicProvider);
}

function loadAmapLayer(viewer, layerType, amapKey) {
  if (!amapKey) {
    console.error("加载高德地图失败：请提供有效的高德地图 Key。");
    return;
  }

  let urlTemplate = '';
  const subdomains = ['0', '1', '2', '3']; // 高德地图的子域名

  // 根据图层类型选择不同的 URL 模板
  switch (layerType) {
    case 'vec':
      // 矢量底图
      urlTemplate = `https://webst0{s}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}&lang=zh_cn&size=1&scale=1&`;
      break;
    case 'img':
      // 影像底图
      urlTemplate = `https://webst0{s}.is.autonavi.com/appmaptile?style=1&x={x}&y={y}&z={z}&lang=zh_cn&size=1&scale=1&key=${amapKey}`;
      break;
    case 'cva':
      // 矢量注记
      urlTemplate = `https://webst0{s}.is.autonavi.com/appmaptile?style=8&x={x}&y={y}&z={z}&lang=zh_cn&size=1&scale=1&key=${amapKey}`;
      break;
    case 'cva_img':
      // 影像注记
      urlTemplate = `https://webst0{s}.is.autonavi.com/appmaptile?style=7&x={x}&y={y}&z={z}&lang=zh_cn&size=1&scale=1&key=${amapKey}`;
      break;
    default:
      console.error(`不支持的图层类型: ${layerType}`);
      return;
  }

  const imageryProvider = new Cesium.UrlTemplateImageryProvider({
    url: urlTemplate,
    subdomains: subdomains,
    tilingScheme: new Cesium.WebMercatorTilingScheme(),
    maximumLevel: 18, // 高德地图支持的最大缩放级别
    reverseY: true, // 关键：高德地图瓦片Y轴需要翻转
    credit: new Cesium.Credit('高德地图 <a href="https://lbs.amap.com/" target="_blank">lbs.amap.com</a>')
  });

  viewer.imageryLayers.addImageryProvider(imageryProvider);
}

function loadWmsLayer(viewer, url, layers) {
  const wmsImageryProvider = new Cesium.WebMapServiceImageryProvider({
    url: url, // WMS 服务地址
    layers: layers, // 图层名称（需从 WMS GetCapabilities 中获取）
    parameters: {
      service: 'WMS',
      version: '1.1.0', // WMS 协议版本（常用 1.1.0/1.3.0）
      request: 'GetMap',
      format: 'image/png', // 图片格式（支持 png/jpeg 等）
      transparent: true, // 透明背景（避免遮挡底图）
      styles: '', // 图层样式（默认空，按服务配置）
      srs: 'EPSG:4326' // 空间参考系（WGS84，Cesium 原生支持）
    },
    tilingScheme: new Cesium.GeographicTilingScheme(),
    // 跨域配置（部分服务需开启 CORS，若出现跨域错误可开启代理）
    // useProxy: false,
    // proxy: new Cesium.DefaultProxy('/proxy/') // 如需代理，需自行部署代理服务
  });

  viewer.imageryLayers.addImageryProvider(wmsImageryProvider);
}

async function load3DTilesFromUrl(viewer, tilesetUrl) {
  // 加载3D Tiles数据集
  const tileset = await Cesium.Cesium3DTileset.fromUrl(tilesetUrl);
  // 添加到场景
  viewer.scene.primitives.add(tileset);
  viewer.zoomTo(tileset);
}

/**
 * 加载GLTF/GLB格式3D模型到Cesium场景
 * @param {Cesium.Viewer} viewer - Cesium实例
 * @param {string} modelUrl - 3D模型的URL路径
 */
function loadGLTFModel(viewer, modelUrl) {
  // 北京位置经纬度：116.40, 39.90，高度50米
  const position = Cesium.Cartesian3.fromDegrees(116.40, 39.90, 50);

  // 计算模型旋转：绕Y轴旋转45°（转换为弧度）
  const heading = Cesium.Math.toRadians(45);
  const pitch = 0;
  const roll = 0;
  const hpr = new Cesium.HeadingPitchRoll(heading, pitch, roll);
  const orientation = Cesium.Transforms.headingPitchRollQuaternion(position, hpr);

  // 加载3D模型
  const modelEntity = viewer.entities.add({
    name: '北京位置3D模型',
    position: position,
    orientation: orientation,
    model: {
      uri: modelUrl,
      scale: 10, // 设置缩放比例为10
      minimumPixelSize: 64, // 确保模型在远处也能显示
      maximumScale: 20000 // 最大缩放限制
    }
  });

  // 模型交互：鼠标点击时变色
  let originalColor = null;
  let flashInterval = null;

  // 绑定点击事件
  viewer.screenSpaceEventHandler.setInputAction((event) => {
    const pick = viewer.scene.pick(event.position);
    if (Cesium.defined(pick) && pick.id === modelEntity) {
      // 停止之前的闪烁效果（如果存在）
      if (flashInterval) {
        clearInterval(flashInterval);
        flashInterval = null;
        // 恢复原始颜色
        if (originalColor) {
          modelEntity.model.color = originalColor;
        }
      } else {
        // 保存原始颜色（首次点击时）
        if (!originalColor) {
          originalColor = modelEntity.model.color || Cesium.Color.WHITE;
        }
        // 添加闪烁效果（黄色和原始颜色交替）
        let isYellow = false;
        flashInterval = setInterval(() => {
          isYellow = !isYellow;
          modelEntity.model.color = isYellow ? Cesium.Color.YELLOW : originalColor;
        }, 500); // 500ms切换一次颜色
      }
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  // // 相机飞向模型
  // viewer.zoomTo(modelEntity, new Cesium.HeadingPitchRange(
  //     heading, // 保持和模型相同的朝向
  //     Cesium.Math.toRadians(-30), // 30°俯视角
  //     500 // 距离模型的距离
  // ));

  return modelEntity;
}


function loadImgByProvider(viewer, imageUrl, imageRectangle) {
  // 3. 创建SingleTileImageryProvider
  const singleTileProvider = new Cesium.SingleTileImageryProvider({
    url: imageUrl,
    rectangle: imageRectangle,
    transparent: true, // 若图片有透明背景，需设为true
    credit: '自定义图片' // 可选：显示版权信息
  });

  // 4. 将图片添加为Cesium的图层（可调整层级和透明度）
  const imageLayer = viewer.imageryLayers.addImageryProvider(singleTileProvider);
  imageLayer.alpha = 0.3; // 透明度（0-1，1为不透明）
  imageLayer.zIndex = 1; // 图层层级（值越大越靠上，默认底图为0）
}

async function loadGeoJsonLayer(viewer, geoJsonUrl, options = {}) {
  // 1. 默认配置（新手友好，样式美观）
  const defaultOptions = {
    fillColor: '#0080ff',    // 填充色（天蓝色）
    fillAlpha: 0.2,          // 填充透明度
    outlineColor: '#ffffff', // 轮廓色（白色）
    outlineWidth: 2,         // 轮廓宽度
    enableTooltip: true,     // 开启悬浮提示
    flyToLayer: true,        // 加载后飞到图层
    onLoad: (entities) => console.log(`GeoJSON图层加载成功，共创建${entities.length}个要素`),
    onError: (err) => console.error('GeoJSON图层加载失败：', err)
  };
  // 合并用户配置（用户配置覆盖默认）
  const config = { ...defaultOptions, ...options };

  // 存储创建的Entity（便于后续管理）
  const createdEntities = [];

  try {
    // 2. 请求GeoJSON数据（阿里云DataV的JSON支持跨域，直接请求）
    const response = await fetch(geoJsonUrl);
    if (!response.ok) {
      throw new Error(`请求失败：${response.status} ${response.statusText}`);
    }
    const geoJson = await response.json();

    // 3. 遍历GeoJSON的features（核心：解析边界坐标）
    for (const feature of geoJson.features) {
      // 跳过无几何信息的要素
      if (!feature.geometry) continue;

      // 4. 处理几何类型（阿里云DataV主要是Polygon/MultiPolygon）
      let positions = [];
      const geometryType = feature.geometry.type;

      // 处理单多边形（Polygon）
      if (geometryType === 'Polygon') {
        // 提取坐标：GeoJSON坐标是[lon, lat]，需转换为Cesium的Cartesian3
        positions = Cesium.Cartesian3.fromDegreesArray(
          // 扁平化坐标数组（[[lon1,lat1],[lon2,lat2]] → [lon1,lat1,lon2,lat2]）
          feature.geometry.coordinates[0].flat()
        );
      }
      // 处理多多边形（MultiPolygon，行政区划常用）
      else if (geometryType === 'MultiPolygon') {
        // 遍历每个子多边形，合并坐标
        const allCoords = [];
        feature.geometry.coordinates.forEach(polygon => {
          allCoords.push(...polygon[0].flat());
        });
        positions = Cesium.Cartesian3.fromDegreesArray(allCoords);
      }
      // 其他几何类型暂不支持（提示用户）
      else {
        console.warn(`暂不支持的几何类型：${geometryType}，跳过该要素`);
        continue;
      }

      // 5. 创建Cesium Entity（多边形要素）
      const polygonEntity = viewer.entities.add({
        // 要素名称（优先取name，无则取adcode）
        name: feature.properties?.name || feature.properties?.adcode || '未命名区域',
        // 多边形几何
        polygon: {
          hierarchy: new Cesium.PolygonHierarchy(positions),
          // 填充样式
          material: Cesium.Color.fromCssColorString(config.fillColor).withAlpha(config.fillAlpha),
          // 轮廓样式
          outline: true,
          outlineColor: Cesium.Color.fromCssColorString(config.outlineColor),
          outlineWidth: config.outlineWidth
        },
        // 存储原始属性（便于后续交互）
        properties: feature.properties
      });

      createdEntities.push(polygonEntity);

      // 6. 可选：开启鼠标悬浮提示
      if (config.enableTooltip) {
        // 绑定鼠标移动事件
        viewer.screenSpaceEventHandler.setInputAction((event) => {
          const pick = viewer.scene.pick(event.endPosition);
          if (Cesium.defined(pick) && pick.id === polygonEntity) {
            // 设置提示框内容（显示行政区名称）
            viewer.selectedEntity = polygonEntity;
          } else {
            viewer.selectedEntity = undefined;
          }
        }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
      }
    }

    // 7. 可选：加载后飞到图层位置
    if (config.flyToLayer && createdEntities.length > 0) {
      // 计算所有要素的包围盒，相机飞到该范围
      viewer.zoomTo(createdEntities, new Cesium.HeadingPitchRange(
        0, // 朝向正北
        Cesium.Math.toRadians(-30), // 俯视角30°
        5000 // 距离图层的高度（可根据区域大小调整）
      ));
    }

    // 8. 触发成功回调
    config.onLoad(createdEntities);
    return createdEntities;

  } catch (error) {
    // 9. 错误处理（新手友好提示）
    config.onError(error);
    alert(`GeoJSON图层加载失败：${error.message}\n请检查JSON地址是否正确`);
    return [];
  }
}

// 加载 GeoJSON 文件
function loadGeoJsonDataSource(viewer, url) {
  Cesium.GeoJsonDataSource.load(url, {
    // 自定义渲染样式（可选，优先使用 GeoJSON 中的自定义属性）
    // pointStyle: function (feature) {
    //     return new Cesium.PointStyle({
    //         color: Cesium.Color.fromCssColorString(feature.properties.color || '#FF0000'),
    //         pixelSize: 8
    //     });
    // },
    // polylineStyle: function (feature) {
    //     return new Cesium.PolylineStyle({
    //         color: Cesium.Color.fromCssColorString(feature.properties.color || '#0000FF'),
    //         width: feature.properties.lineWidth || 2
    //     });
    // },
    // polygonStyle: function (feature) {
    //     return new Cesium.PolygonStyle({
    //         fillColor: Cesium.Color.fromCssColorString(feature.properties.color || '#00FF00')
    //             .withAlpha(feature.properties.opacity || 0.5),
    //         outlineColor: Cesium.Color.BLACK,
    //         outlineWidth: 1
    //     });
    // },
    stroke: Cesium.Color.RED,
    fill: Cesium.Color.PINK.withAlpha(0),
    strokeWidth: 3,
    fillAlpha: 0.2,
    markerSymbol: '?'
  }).then(function (dataSource) {
    viewer.dataSources.add(dataSource);
  });
}

/**
 * Cesium加载SHP Zip包核心函数（对齐博客逻辑）
 * @param {Cesium.Viewer} viewer - Cesium实例
 * @param {string} shpZipUrl - SHP Zip包地址
 * @param {Object} style - 自定义样式（可选）
 */
async function loadShpZipToCesium(viewer, shpZipUrl, style = {}) {
  // 默认样式（红色边界线，低透明度填充）
  const defaultStyle = {
    lineColor: Cesium.Color.RED,
    lineWidth: 2, // Cesium最大支持2px
    fillColor: Cesium.Color.GREEN.withAlpha(0.05)
  };
  const finalStyle = { ...defaultStyle, ...style };

  try {
    // 步骤1：用shpjs解析Zip包（博客核心调用方式）
    console.log("[SHP加载] 开始解析Zip包：", shpZipUrl);
    const rawGeoJson = await shp(shpZipUrl);
    loadGeoJsonDataSource(viewer, rawGeoJson);
    // if (!rawGeoJson || !rawGeoJson.features || rawGeoJson.features.length === 0) {
    //   throw new Error("Zip包解析结果为空，请检查包内是否有SHP核心文件");
    // }

    // // 步骤2：OpenLayers标准化GeoJSON（博客关键步骤，解决格式/投影问题）
    // console.log("[SHP加载] OpenLayers标准化GeoJSON");
    // const olGeoJsonFormat = new ol.format.GeoJSON();
    // // 博客核心：指定投影为EPSG:3857（Web墨卡托）
    // const olFeatures = olGeoJsonFormat.readFeatures(rawGeoJson, {
    //   featureProjection: 'EPSG:3857'
    // });
    // // 验证解析结果（获取四至范围，和博客一致）
    // const olSource = new ol.source.Vector({ features: olFeatures });
    // const extent = olSource.getExtent();
    // if (!extent || extent.length === 0) {
    //   throw new Error("OpenLayers无法解析要素范围，Zip包格式异常");
    // }
    // console.log("[SHP加载] SHP四至范围：", extent);

    // // 步骤3：遍历要素，转换坐标到Cesium兼容的WGS84
    // const entities = [];
    // olFeatures.forEach(olFeature => {
    //   const geometry = olFeature.getGeometry();
    //   if (!geometry) return;

    //   // 适配Polygon/MultiPolygon（省级边界主要类型）
    //   let coords = [];
    //   if (geometry.getType() === 'Polygon') {
    //     coords = [geometry.getCoordinates()[0]];
    //   } else if (geometry.getType() === 'MultiPolygon') {
    //     coords = geometry.getCoordinates();
    //   } else {
    //     console.warn("[SHP加载] 跳过非面要素：", geometry.getType());
    //     return;
    //   }

    //   // 坐标转换：EPSG:3857 → WGS84（Cesium原生支持）
    //   const positions = [];
    //   coords.forEach(poly => {
    //     poly.forEach(coord => {
    //       // OpenLayers投影转换：3857 → 4326（经纬度）
    //       const wgs84Coord = ol.proj.transform(coord, 'EPSG:3857', 'EPSG:4326');
    //       // 转Cesium笛卡尔坐标
    //       positions.push(Cesium.Cartesian3.fromDegrees(
    //         wgs84Coord[0], // 经度
    //         wgs84Coord[1], // 纬度
    //         0              // 高程（贴地）
    //       ));
    //     });
    //   });

    //   // 步骤4：创建Cesium Entity（渲染边界）
    //   entities.push({
    //     name: olFeature.get('name') || olFeature.get('adcode') || "省级边界",
    //     polygon: {
    //       hierarchy: new Cesium.PolygonHierarchy(positions),
    //       material: finalStyle.fillColor,
    //       outline: true,
    //       outlineColor: finalStyle.lineColor,
    //       outlineWidth: finalStyle.lineWidth,
    //       clampToGround: true // 贴地渲染，和博客底图贴合逻辑一致
    //     },
    //     properties: olFeature.getProperties() // 保留原始属性，便于交互
    //   });
    // });

    // // 步骤5：批量添加到Cesium场景（提升性能）
    // entities.forEach(entity => viewer.entities.add(entity));
    // console.log("[SHP加载] 成功加载", entities.length, "个省级边界要素");

  } catch (error) {
    console.error("[SHP加载失败]", error);
    alert(`SHP Zip包加载失败：${error.message}\n排查步骤：\n1. Zip包用Windows默认压缩，含.shp/.shx/.dbf/.prj\n2. IIS已配置.zip的MIME类型为application/zip\n3. 关闭IIS的动态/静态压缩`);
  }
}


function addSingleFeature(viewer, feature, index, styles) {
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
      if (styles.polygon.clampToGround) {
        viewer.entities.add({
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
      break;

    case 'MultiPolygon':
      geometry.coordinates.forEach((polyCoord, idx) => {
        // 主体面
        viewer.entities.add({
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
          viewer.entities.add({
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
        }
      });
      return null;

    default:
      console.warn(`不支持的几何类型：${geometry.type}`);
      return null;
  }

  return viewer.entities.add(entityOptions);
}

function getDynamicStyles(properties, customColorRules = {}, styleBase = {}) {
  let polygonColor, outlineColor;

  // 新增：支持"random"关键字自动启用随机颜色
  if (customColorRules === 'random') {
    const randomNum = getRandomNum();
    polygonColor = getRandomColorByNum(randomNum).polygonColor;
    outlineColor = getRandomColorByNum(randomNum).outlineColor;
  } else if (Object.keys(customColorRules).length > 0) {
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

async function single_loadDatavGeoJSON(urlOrGeoJson, options = {}) {
  const {
    customColorRules = {},
    styleBase = {},
    filter = (feature) => true,
    viewer
  } = options;

  if (!viewer || !viewer.entities) {
    throw new Error('options.viewer 必须传入有效的Cesium.Viewer实例！');
  }

  try {
    // 新增：支持直接传入GeoJSON对象（如SHP解析结果）
    const geoJson = typeof urlOrGeoJson === 'string'
      ? await (await fetch(urlOrGeoJson)).json()
      : urlOrGeoJson;

    console.log('GeoJSON数据加载成功：', geoJson);

    const createdEntities = [];
    
    geoJson.features.forEach((feature, index) => {
      if (!filter(feature)) return;
      const styles = getDynamicStyles(feature.properties, customColorRules, styleBase);
      const entity = addSingleFeature(viewer, feature, index, styles);
      if (entity) {
        createdEntities.push(entity);
      }
    });
    
    console.log('所有要素渲染完成！');
    return createdEntities;
  } catch (error) {
    console.error('GeoJSON加载/渲染失败：', error);
    alert(`数据加载失败：${error.message}`);
    return [];
  }
}

//生成1-10的随机整数
function getRandomNum() {
  return Math.floor(Math.random() * 10) + 1;
}

//根据随机数生成随机Cesium颜色（10种可选，带透明度）
function getRandomColorByNum(num) {
  const colorMap = [
    Cesium.Color.RED, Cesium.Color.ORANGE, Cesium.Color.YELLOW,
    Cesium.Color.GREEN, Cesium.Color.CYAN, Cesium.Color.BLUE,
    Cesium.Color.PURPLE, Cesium.Color.PINK, Cesium.Color.BROWN,
    Cesium.Color.GRAY
  ];
  return {
    polygonColor: colorMap[num - 1].withAlpha(0.4),
    outlineColor: colorMap[num - 1]
  };
}

// 多边形绘制功能核心函数
function initPolygonDraw(viewer, options = {}) {
  // 配置项默认值
  const { coordDisplayId = 'coordDisplay' } = options;
  let coordEl = document.getElementById(coordDisplayId);
  if (!coordEl) {
    console.warn('未找到坐标显示容器，已自动创建');
    // 自动创建坐标显示容器（防止html中未定义）
    let div = document.createElement('div');
    div.id = coordDisplayId;
    div.style.position = 'absolute';
    div.style.top = '20px';
    div.style.left = '20px';
    div.style.background = 'rgba(0,0,0,0.7)';
    div.style.color = '#fff';
    div.style.padding = '10px';
    div.style.borderRadius = '5px';
    div.style.zIndex = '999';
    div.style.fontSize = '12px';
    document.body.appendChild(div);
    coordEl = div;
  }

  // 屏幕坐标转地理坐标核心函数（内部封装，避免全局暴露）
  function screenToGeo(viewer, x, y) {
    const screenCoord = new Cesium.Cartesian2(x, y);
    let cartesian = viewer.scene.pickPosition(screenCoord) || viewer.camera.pickEllipsoid(screenCoord, viewer.scene.globe.ellipsoid);
    if (!cartesian) return null;
    const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
    return {
      lon: Cesium.Math.toDegrees(cartographic.longitude).toFixed(6),
      lat: Cesium.Math.toDegrees(cartographic.latitude).toFixed(6),
      cartesian: cartesian
    };
  }

  // 绘制状态变量（函数内部作用域，避免全局冲突）
  let isDrawing = false,
    points = [],
    tempLine,
    tempPolygon,
    finalPolygon;
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

  // 鼠标移动：实时显示坐标 + 预览多边形
  handler.setInputAction((e) => {
    const geo = screenToGeo(viewer, e.endPosition.x, e.endPosition.y);
    coordEl.innerHTML = geo ? `当前：${geo.lon}°, ${geo.lat}°` : '超出范围';
    if (isDrawing && points.length > 0 && geo) {
      const tempPos = [...points.map(p => p.cartesian), geo.cartesian];
      tempLine && (tempLine.polyline.positions = tempPos);
      tempPolygon && (tempPolygon.polygon.hierarchy = new Cesium.PolygonHierarchy(tempPos));
    }
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

  // 左键点击：添加顶点
  handler.setInputAction((e) => {
    if (!isDrawing) return;
    const geo = screenToGeo(viewer, e.position.x, e.position.y);
    if (!geo) return;
    points.push(geo);
    coordEl.innerHTML += `<br>顶点${points.length}：${geo.lon}°, ${geo.lat}°`;
    const pos = points.map(p => p.cartesian);
    tempLine.polyline.positions = pos;
    tempPolygon.polygon.hierarchy = new Cesium.PolygonHierarchy(pos);
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

  // 左键双击：结束绘制，生成最终多边形
  handler.setInputAction(() => {
    // 只有在绘制模式下才处理双击事件
    if (isDrawing) {
      document.getElementById('operation').textContent = "按下“z”开始绘制多边形";
      if (points.length < 3) {
        alert("至少3个顶点");
        reset();
        return;
      }
      const closedPos = [...points.map(p => p.cartesian), points[0].cartesian];
      // 删除旧多边形，创建新的
      finalPolygon && viewer.entities.remove(finalPolygon);
      finalPolygon = viewer.entities.add({
        polygon: {
          hierarchy: closedPos,
          material: Cesium.Color.RED.withAlpha(0.5),
          outline: true,
        },
        isUserDrawn: true  // 添加手动绘制标识
      });
      // 结束绘制模式，但不清除最终多边形
      isDrawing = false;
      points = [];
      tempLine && viewer.entities.remove(tempLine);
      tempPolygon && viewer.entities.remove(tempPolygon);
      tempLine = tempPolygon = null;
      coordEl.innerHTML = "已完成绘制";
    }
  }, Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);

  // 键盘事件：Z键开启绘制，ESC取消
  function bindKeydown() {
    // 先解绑旧事件（避免重复绑定）
    document.removeEventListener('keydown', handleKeydown);
    document.addEventListener('keydown', handleKeydown);
  }

  function handleKeydown(e) {
    // Z键开启绘制
    if (e.key.toLowerCase() === 'z' && !isDrawing) {
      document.getElementById('operation').textContent = "正在绘制，双击结束";
      // 删除旧多边形
      finalPolygon && viewer.entities.remove(finalPolygon);
      isDrawing = true;
      points = [];
      // 创建临时线/面
      tempLine = viewer.entities.add({
        polyline: {
          positions: [],
          width: 2,
          material: Cesium.Color.WHITE
        }
      });
      tempPolygon = viewer.entities.add({
        polygon: {
          hierarchy: [],
          material: Cesium.Color.RED.withAlpha(0.3),
          outline: true
        }
      });
      coordEl.innerHTML = "已开启绘制：左键单击加点，双击结束";
    }
    // ESC取消绘制
    if (e.key === 'Escape') reset();
  }

  // 重置绘制状态
  function reset() {
    // 清理临时线/面
    tempLine && viewer.entities.remove(tempLine);
    tempPolygon && viewer.entities.remove(tempPolygon);
    // 清理最终多边形
    finalPolygon && viewer.entities.remove(finalPolygon);
    // 重置变量
    isDrawing = false;
    points = [];
    tempLine = tempPolygon = finalPolygon = null;
    coordEl.innerHTML = "已退出绘制模式";
  }

  // 初始化绑定事件
  bindKeydown();

  // 返回销毁方法（可选，用于清理资源）
  return {
    destroy: () => {
      handler.destroy(); // 销毁事件处理器
      document.removeEventListener('keydown', handleKeydown); // 解绑键盘事件
      reset(); // 清理绘制状态
    },
    reset: reset // 暴露reset方法
  };
}

// 多边形删除功能核心函数 - 只删除最新绘制的多边形
function deletepolygon() {
  const viewer = window._cesiumViewer;
  if (!viewer) {
    console.warn("未找到Cesium Viewer实例");
    return;
  }

  // 从后往前遍历，找到第一个用户绘制的多边形并删除（只删除最新的一个）
  const entities = viewer.entities.values;
  let deletedCount = 0;
  
  for (let i = entities.length - 1; i >= 0; i--) {
    const entity = entities[i];
    // 仅删除有polygon属性且是用户绘制的实体
    if (entity.polygon && entity.isUserDrawn) {
      viewer.entities.remove(entity);
      deletedCount++;
      console.log(`已删除最新绘制的多边形`);
      break; // 只删除最新的一个，删除后立即退出循环
    }
  }
  
  if (deletedCount === 0) {
    console.log("没有找到可删除的用户绘制多边形");
  }

  // 重置绘制状态
  if (window.polygonDraw && typeof window.polygonDraw.reset === 'function') {
    window.polygonDraw.reset();
  }
}

// 加载风场数据并显示风场图层
function loadWind(viewer, windDataUrl) {
  const windOptions = {
    colorScale: [
      "rgb(36,104, 180)",
      "rgb(60,157, 194)",
      "rgb(128,205,193 )",
      "rgb(151,218,168 )",
      "rgb(198,231,181)",
      "rgb(238,247,217)",
      "rgb(255,238,159)",
      "rgb(252,217,125)",
      "rgb(255,182,100)",
      "rgb(252,150,75)",
      "rgb(250,112,52)",
      "rgb(245,64,32)",
      "rgb(237,45,28)",
      "rgb(220,24,32)",
      "rgb(180,0,35)",
    ],
    frameRate: 16,
    maxAge: 60,
    globalAlpha: 0.9,
    velocityScale: 1 / 30,
    paths: 2000,
  };
  // 2. 加载风场数据
  fetch(windDataUrl)
    .then(response => response.json())
    .then(windData => {
      // 3. 创建风场粒子系统
      const windLayer = new CesiumWind.WindLayer(windData, windOptions);

      // 4. 将风场图层添加到场景
      windLayer.addTo(viewer);
      
      // 5. 将风图层添加到图层管理器
      if (window.layerManager) {
        window.layerManager.addLayer('windLayer', windLayer);
      }

      // 可选：控制风场的显示/隐藏
      // windLayer.show = false;
    })
    .catch(error => {
      console.error('加载风场数据失败：', error);
    });
}

// 初始化地图控制功能
function initMapControls(viewer) {
  // 定义各视角参数（经纬度、高度、方向）
  const viewPositions = {
    china: {
      destination: Cesium.Cartesian3.fromDegrees(105, 30, 7000000), // 中国中心点
      orientation: {
        heading: Cesium.Math.toRadians(0),
        pitch: Cesium.Math.toRadians(-90),
        roll: 0
      }
    },
    beijing: {
      destination: Cesium.Cartesian3.fromDegrees(116.40, 39.76, 15000), // 北京
      orientation: {
        heading: Cesium.Math.toRadians(0),
        pitch: Cesium.Math.toRadians(-40),
        roll: 0
      }
    },
    shanghai: {
      destination: Cesium.Cartesian3.fromDegrees(121.47, 31.09, 15000), // 上海
      orientation: {
        heading: Cesium.Math.toRadians(0),
        pitch: Cesium.Math.toRadians(-40),
        roll: 0
      }
    },
    global: {
      destination: Cesium.Cartesian3.fromDegrees(0, 0, 14000000), // 全球
      orientation: {
        heading: Cesium.Math.toRadians(0),
        pitch: Cesium.Math.toRadians(-90),
        roll: 0
      }
    }
  };

  // 记录当前相机高度（初始值使用中国区域高度）
  let currentHeight = 7000000;

  // 获取当前相机位置并更新高度记录
  function updateCurrentHeight() {
    const cartographic = Cesium.Cartographic.fromCartesian(viewer.camera.position);
    currentHeight = cartographic.height;
  }

  // 放大功能（使用flyTo平滑过渡）
  document.getElementById('zoomIn').addEventListener('click', () => {
    updateCurrentHeight();
    // 每次放大到当前高度的70%（可调整比例控制缩放幅度）
    const newHeight = Math.max(currentHeight * 0.7, 1000); // 最小高度限制
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
      duration: 0.8 // 动画持续时间（秒），控制丝滑程度
    });
  });

  // 缩小功能（使用flyTo平滑过渡）
  document.getElementById('zoomOut').addEventListener('click', () => {
    updateCurrentHeight();
    // 每次缩小到当前高度的1.5倍（可调整比例控制缩放幅度）
    const newHeight = Math.min(currentHeight * 1.5, 20000000); // 最大高度限制
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
      duration: 0.8 // 动画持续时间（秒）
    });
  });

  // 复位到初始视角（中国区域）
  document.getElementById('resetView').addEventListener('click', () => {
    viewer.camera.flyTo(viewPositions.china);
    currentHeight = 7000000; // 重置高度记录
  });

  // 视角切换功能
  document.getElementById('viewSwitcher').addEventListener('change', (e) => {
    const viewKey = e.target.value;
    if (viewPositions[viewKey]) {
      viewer.camera.flyTo(viewPositions[viewKey]);
      // 更新高度记录为目标视角高度
      const cartographic = Cesium.Cartographic.fromCartesian(viewPositions[viewKey].destination);
      currentHeight = cartographic.height;
    }
  });

  // 禁用Cesium默认右键菜单
  viewer.scene.canvas.addEventListener('contextmenu', (e) => {
    e.preventDefault();
  });
}

// 利用现有addSingleFeature()添加城市地标点
function addCityLandmarksWithExistingFunction(viewer) {
  // 1. 定义城市数据（包含名称和经纬度）
  const cities = [
    { name: "北京", lon: 116.40, lat: 39.90 },
    { name: "上海", lon: 121.47, lat: 31.23 },
    { name: "广州", lon: 113.23, lat: 23.16 }
  ];

  // 2. 自定义点要素样式（适配addSingleFeature()的styles格式）
  const landmarkStyles = {
    point: {
      // 使用红色圆形（通过材质指定颜色，大小30px）
      color: Cesium.Color.RED,
      pixelSize: 30,
      outlineColor: Cesium.Color.MAROON, // 边框增强辨识度
      outlineWidth: 2
    },
    // 其他几何类型样式可留空（当前只需要点要素）
    polyline: {},
    polygon: {}
  };

  // 3. 遍历城市，构造GeoJSON点要素并调用addSingleFeature()
  cities.forEach((city, index) => {
    // 构造符合GeoJSON规范的点要素
    const pointFeature = {
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [city.lon, city.lat, 0] // 经纬度+高程（0表示贴地）
      },
      properties: {
        name: city.name, // 城市名称（用于标签和点击事件）
        longitude: city.lon, // 存储经度
        latitude: city.lat // 存储纬度
      }
    };

    // 调用现有函数添加点要素
    addSingleFeature(viewer, pointFeature, `landmark-${index}`, landmarkStyles);

    // 4. 为点要素添加文字标签（基于实体ID关联）
    const entity = viewer.entities.getById(`geojson-feature-landmark-${index}`);
    if (entity) {
      // 添加Label标签
      entity.label = new Cesium.LabelGraphics({
        text: city.name,
        font: "14px sans-serif",
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 1,
        verticalOrigin: Cesium.VerticalOrigin.TOP, // 标签在点的上方
        horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE, // 显式指定“填充+轮廓”模式
        pixelOffset: new Cesium.Cartesian2(0, 20) // 偏移15px避免遮挡
      });
    }
  });

  // 5. 绑定点击事件（通过全局事件监听）
  bindLandmarkClickEvent(viewer);
}

// 绑定地标点点击事件
function bindLandmarkClickEvent(viewer) {
  // 先移除旧事件避免重复绑定
  viewer.screenSpaceEventHandler.removeInputAction(Cesium.ScreenSpaceEventType.LEFT_CLICK);

  // 注册点击事件
  viewer.screenSpaceEventHandler.setInputAction((event) => {
    const pick = viewer.scene.pick(event.position);
    if (Cesium.defined(pick) && pick.id) {
      const entity = pick.id;
      // 判断是否为地标点（通过ID前缀和属性判断）
      if (
        entity.id.startsWith("geojson-feature-landmark-") &&
        entity.properties?.name
      ) {
        const name = entity.properties.name.getValue();
        const lon = entity.properties.longitude.getValue();
        const lat = entity.properties.latitude.getValue();
        // 控制台输出信息
        console.log(`城市: ${name}`);
        console.log(`经纬度: ${lon}, ${lat}`);
        console.log("---------------------");
      }
    }
  }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
}

// 添加城市连线（北京、上海、广州）
function addCityLine(viewer) {
  // 城市经纬度坐标
  const beijing = [116.404, 39.915];
  const shanghai = [121.4737, 31.2304];
  const guangzhou = [113.2644, 23.1291];

  // 创建线要素
  const cityLine = viewer.entities.add({
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArray([
        ...beijing,
        ...shanghai,
        ...guangzhou
      ]),
      width: 5,
      material: Cesium.Color.RED,
      // 存储原始样式用于高亮恢复
      _originalWidth: 5,
      _originalMaterial: Cesium.Color.BLUE
    }
  });

  return cityLine;
}

// 1. 定义中国东部区域多边形GeoJSON数据
const eastChinaPolygon = {
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": {
        "name": "中国东部区域"
      },
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [118.0, 39.0],   // 北京附近
            [122.0, 38.0],   // 山东半岛
            [123.0, 32.0],   // 长江口附近
            [114.0, 28.0],   // 湖南东部
            [110.0, 35.0],   // 山西南部
            [118.0, 39.0]    // 闭合点
          ]
        ]
      }
    }
  ]
};

// 2. 加载多边形并设置初始样式
async function loadEastChinaPolygon(viewer) {
  // 初始样式配置
  const styleBase = {
    polyline: {
      width: 2  // 初始轮廓宽度
    }
  };

  // 自定义颜色规则
  const customColorRules = {
    default: {
      condition: () => true,  // 匹配所有要素
      polygonColor: Cesium.Color.GREEN.withAlpha(0.4),  // 半透明绿色填充
      outlineColor: Cesium.Color.BLACK  // 黑色轮廓
    }
  };

  // 使用现有函数加载要素
  const createdEntities = await single_loadDatavGeoJSON(eastChinaPolygon, {
    viewer,
    customColorRules,
    styleBase,
    filter: () => true
  });

  // 3. 实现高亮效果（鼠标悬浮）
  implementHighlightEffect(viewer);
  
  return createdEntities;
}

// 实现高亮效果的核心函数
function implementHighlightEffect(viewer) {
  let currentEntity = null;
  let originalStyles = {};  // 存储原始样式

  // 鼠标移动事件监听
  const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
  handler.setInputAction((movement) => {
    // 获取鼠标指向的实体
    const pick = viewer.scene.pick(movement.endPosition);
    const entity = pick ? pick.id : null;

    // 处理实体切换
    if (entity !== currentEntity) {
      // 恢复上一个实体的样式
      if (currentEntity && originalStyles[currentEntity.id]) {
        const styles = originalStyles[currentEntity.id];
        if (currentEntity.polygon) {
          currentEntity.polygon.material = styles.polygonColor;
        }
        if (currentEntity.polyline) {
          currentEntity.polyline.width = styles.lineWidth;
          currentEntity.polyline.material = styles.lineColor;
        }
        delete originalStyles[currentEntity.id];
      }

      // 设置新实体的高亮样式
      if (entity) {
        currentEntity = entity;
        originalStyles[entity.id] = {};
        
        // 处理面要素
        if (entity.polygon) {
          // 保存原始样式
          originalStyles[entity.id].polygonColor = entity.polygon.material;
          
          // 应用高亮样式：降低透明度
          entity.polygon.material = Cesium.Color.GREEN.withAlpha(0.6);
        }
        
        // 处理线要素
        if (entity.polyline) {
          // 保存原始样式
          originalStyles[entity.id].lineWidth = entity.polyline.width;
          originalStyles[entity.id].lineColor = entity.polyline.material;
          
          // 应用高亮样式：线宽变为8px
          entity.polyline.width = 8.0;
        }
      } else {
        currentEntity = null;
      }
    }
  }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);
}

// 调用方式：在初始化Cesium Viewer后执行
// loadEastChinaPolygon(viewer);

/**
 * 加载GeoJSON数据并支持空间查询
 * @param {Cesium.Viewer} viewer - Cesium Viewer实例
 * @param {string|Object} geoJsonUrlOrData - GeoJSON数据URL或对象
 * @param {Object} options - 配置选项
 * @returns {Promise<Array>} - 加载的实体数组
 */
async function loadGeoJsonWithQuerySupport(viewer, geoJsonUrlOrData, options = {}) {
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

// 多边形查询功能：查询指定多边形范围内的所有实体
function queryEntitiesInPolygon() {
  const viewer = window._cesiumViewer;
  if (!viewer) {
    console.warn("未找到Cesium Viewer实例");
    return;
  }

  // 获取手动绘制的多边形（之前添加了isUserDrawn标识的）
  const userPolygon = viewer.entities.values.find(
    entity => entity.polygon && entity.isUserDrawn
  );

  if (!userPolygon) {
    alert("请先绘制查询多边形");
    return;
  }

  // 获取多边形的地理坐标（经纬度）
  const polygonHierarchy = userPolygon.polygon.hierarchy.getValue(Cesium.JulianDate.now());
  const polygonPositions = polygonHierarchy.positions;
  const polygonCartographics = polygonPositions.map(
    pos => Cesium.Cartographic.fromCartesian(pos)
  );
  const polygonCoordinates = polygonCartographics.map(
    carto => [Cesium.Math.toDegrees(carto.longitude), Cesium.Math.toDegrees(carto.latitude)]
  );

  // 存储查询结果
  const resultEntities = [];

  // 遍历所有实体，判断是否在多边形内
  viewer.entities.values.forEach(entity => {
    // 跳过查询多边形本身
    if (entity === userPolygon) return;

    // 获取实体的位置（点要素）
    if (entity.position) {
      const position = entity.position.getValue(Cesium.JulianDate.now());
      if (position) {
        const carto = Cesium.Cartographic.fromCartesian(position);
        const lon = Cesium.Math.toDegrees(carto.longitude);
        const lat = Cesium.Math.toDegrees(carto.latitude);

        // 判断点是否在多边形内
        if (isPointInPolygon([lon, lat], polygonCoordinates)) {
          resultEntities.push(entity);
          console.log('查询到点要素:', entity.name || '未命名', [lon, lat]);
        }
      }
    }

    // 处理面要素的中心点判断（可选）
    if (entity.polygon && !entity.isUserDrawn) {
      const hierarchy = entity.polygon.hierarchy.getValue(Cesium.JulianDate.now());
      if (hierarchy && hierarchy.positions && hierarchy.positions.length > 0) {
        // 计算面要素的中心点
        const center = calculatePolygonCenter(hierarchy.positions);
        const carto = Cesium.Cartographic.fromCartesian(center);
        const lon = Cesium.Math.toDegrees(carto.longitude);
        const lat = Cesium.Math.toDegrees(carto.latitude);

        if (isPointInPolygon([lon, lat], polygonCoordinates)) {
          resultEntities.push(entity);
          console.log('查询到面要素:', entity.name || '未命名', [lon, lat]);
        }
      }
    }
  });

  // 显示查询结果
  console.log('查询结果:', resultEntities);
  console.log('查询结果数量:', resultEntities.length);
  
  // 获取查询结果显示框
  const resultEl = document.getElementById('queryResult');
  if (resultEl) {
    if (resultEntities.length === 0) {
      resultEl.innerHTML = '<div style="padding:10px;">未查询到任何实体</div>';
    } else {
      let html = `<div style="padding:10px;"><h4 style="margin:0 0 10px 0;">共查询到 ${resultEntities.length} 个实体：</h4><ul style="margin:0;padding-left:20px;">`;
      resultEntities.forEach(entity => {
        const name = entity.name || '未命名实体';
        html += `<li>${name}</li>`;
      });
      html += '</ul></div>';
      resultEl.innerHTML = html;
    }
    // 确保显示框可见
    resultEl.style.display = 'block';
    resultEl.style.visibility = 'visible';
    resultEl.style.opacity = '1';
  } else {
    console.error('查询结果显示框未找到');
  }
  
  return resultEntities;
}

// 点是否在多边形内的判断算法（射线法）
function isPointInPolygon(point, polygon) {
  let inside = false;
  const x = point[0], y = point[1];

  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i][0], yi = polygon[i][1];
    const xj = polygon[j][0], yj = polygon[j][1];

    const intersect = ((yi > y) !== (yj > y))
      && (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
    if (intersect) inside = !inside;
  }

  return inside;
}

// 计算多边形中心点
function calculatePolygonCenter(positions) {
  let x = 0, y = 0, z = 0;
  positions.forEach(pos => {
    x += pos.x;
    y += pos.y;
    z += pos.z;
  });
  return new Cesium.Cartesian3(x / positions.length, y / positions.length, z / positions.length);
}

// 显示查询结果
function displayQueryResult(entities) {
  const resultEl = document.getElementById('queryResult');
  if (!resultEl) {
    // 如果没有结果容器，只在控制台显示
    console.log('=== 空间查询结果 ===');
    console.log(`共查询到 ${entities.length} 个实体`);
    entities.forEach((entity, index) => {
      console.log(`实体 ${index + 1}:`, entity.name || '未命名实体');
      if (entity.properties) {
        console.log(`属性:`, entity.properties.getValue());
      }
    });
    return;
  }

  if (entities.length === 0) {
    resultEl.innerHTML = "<p>未查询到任何实体</p>";
    return;
  }

  let html = `<p>共查询到 ${entities.length} 个实体：</p><ul>`;
  entities.forEach(entity => {
    const name = entity.name || '未命名实体';
    html += `<li>${name}</li>`;
  });
  html += "</ul>";
  resultEl.innerHTML = html;
}