// 图层实例管理系统 - 重构为统一的图层集合数组
let layers = [];

// 图层ID常量定义
export const LAYER_IDS = {
  TDT_LAYER: 'tdtLayer',
  WIND_LAYER: 'windLayer',
  MODEL_LAYER: 'modelLayer',
  JSON_LAYER: 'jsonLayer',
  ENTITY_LAYER: 'entityLayer',
  EAST_CHINA_POLYGON: 'eastChinaPolygon',
  CITY_LINE: 'cityLine'
};

// 图层管理器重构实现
export const layerManager = {
  // 初始化图层管理器
  init: function() {
    // 加载保存的图层状态
    this.loadLayerStates();
    // 设置开关初始状态
    this.updateToggleStates();
    // 添加开关事件监听器
    this.addToggleListeners();
  },

  // 获取图层状态
  getLayerState: function(layerId) {
    return this.loadLayerStates()[layerId] || true;
  },

  // 加载保存的图层状态
  loadLayerStates: function() {
    try {
      const savedStates = localStorage.getItem('cesiumLayerStates');
      return savedStates ? JSON.parse(savedStates) : {
        [LAYER_IDS.TDT_LAYER]: true,
        [LAYER_IDS.WIND_LAYER]: false,
        [LAYER_IDS.MODEL_LAYER]: true,
        [LAYER_IDS.JSON_LAYER]: true,
        [LAYER_IDS.ENTITY_LAYER]: true,
        [LAYER_IDS.EAST_CHINA_POLYGON]: true,
        [LAYER_IDS.CITY_LINE]: true
      };
    } catch (error) {
      console.error('加载图层状态失败:', error);
      return {};
    }
  },

  // 保存图层状态到本地存储
  saveLayerStates: function() {
    try {
      const states = {};
      layers.forEach(layer => {
        states[layer.id] = layer.visible;
      });
      localStorage.setItem('cesiumLayerStates', JSON.stringify(states));
    } catch (error) {
      console.error('保存图层状态失败:', error);
    }
  },

  // 更新开关初始状态
  updateToggleStates: function() {
    const states = this.loadLayerStates();
    // 这些DOM元素可能不存在于React中，因此我们仅在需要时调用
    const tdtToggle = document.getElementById('tdtLayerToggle');
    const windToggle = document.getElementById('windLayerToggle');
    const modelToggle = document.getElementById('modelLayerToggle');
    const jsonToggle = document.getElementById('jsonLayerToggle');
    const entityToggle = document.getElementById('entityLayerToggle');

    if (tdtToggle) tdtToggle.checked = states[LAYER_IDS.TDT_LAYER] !== false;
    if (windToggle) windToggle.checked = states[LAYER_IDS.WIND_LAYER] === true;
    if (modelToggle) modelToggle.checked = states[LAYER_IDS.MODEL_LAYER] !== false;
    if (jsonToggle) jsonToggle.checked = states[LAYER_IDS.JSON_LAYER] !== false;
    if (entityToggle) entityToggle.checked = states[LAYER_IDS.ENTITY_LAYER] !== false;
  },

  // 添加开关事件监听器
  addToggleListeners: function() {
    // 统一的事件处理函数
    const handleLayerToggle = (layerId) => {
      return function(e) {
        const isVisible = e.target.checked;
        layerManager.toggleLayer(layerId, isVisible);
      };
    };

    // 天地图图层开关
    const tdtToggle = document.getElementById('tdtLayerToggle');
    if (tdtToggle) {
      tdtToggle.addEventListener('change', handleLayerToggle(LAYER_IDS.TDT_LAYER));
    }

    // 风效果图层开关
    const windToggle = document.getElementById('windLayerToggle');
    if (windToggle) {
      windToggle.addEventListener('change', handleLayerToggle(LAYER_IDS.WIND_LAYER));
    }

    // 模型图层开关
    const modelToggle = document.getElementById('modelLayerToggle');
    if (modelToggle) {
      modelToggle.addEventListener('change', handleLayerToggle(LAYER_IDS.MODEL_LAYER));
    }

    // JSON数据图层开关
    const jsonToggle = document.getElementById('jsonLayerToggle');
    if (jsonToggle) {
      jsonToggle.addEventListener('change', handleLayerToggle(LAYER_IDS.JSON_LAYER));
    }

    // 实体要素图层开关
    const entityToggle = document.getElementById('entityLayerToggle');
    if (entityToggle) {
      entityToggle.addEventListener('change', handleLayerToggle(LAYER_IDS.ENTITY_LAYER));
    }
  },

  // 添加图层到管理器
  addLayer: function(layerId, name, instance, visible = true) {
    // 检查是否已存在该图层
    const existingIndex = layers.findIndex(layer => layer.id === layerId);

    if (existingIndex !== -1) {
      // 更新现有图层
      layers[existingIndex] = {
        id: layerId,
        name: name,
        instance: instance,
        visible: visible
      };
    } else {
      // 添加新图层
      layers.push({
        id: layerId,
        name: name,
        instance: instance,
        visible: visible
      });
    }

    // 设置初始可见性
    this.setLayerVisibility(instance, visible);
  },

  // 切换图层显示/隐藏
  toggleLayer: function(layerId, isVisible) {
    const layer = layers.find(l => l.id === layerId);
    if (layer) {
      // 更新图层可见性
      this.setLayerVisibility(layer.instance, isVisible);
      // 更新图层状态
      layer.visible = isVisible;
      // 保存状态
      this.saveLayerStates();
    } else {
      // 处理特殊情况：如果是天地图图层，可能有多个实例
      if (layerId === LAYER_IDS.TDT_LAYER) {
        // 切换所有天地图图层
        layers.filter(l => l.id.startsWith(LAYER_IDS.TDT_LAYER)).forEach(l => {
          this.setLayerVisibility(l.instance, isVisible);
          l.visible = isVisible;
        });
        // 保存状态
        this.saveLayerStates();
      } else if (layerId === LAYER_IDS.JSON_LAYER) {
        // 切换所有JSON图层
        layers.filter(l => l.id.startsWith(LAYER_IDS.JSON_LAYER)).forEach(l => {
          this.setLayerVisibility(l.instance, isVisible);
          l.visible = isVisible;
        });
        // 保存状态
        this.saveLayerStates();
      }
    }
  },

  // 设置单个图层的可见性
  setLayerVisibility: function(layerInstance, isVisible) {
    if (!layerInstance) return;

    try {
      if (layerInstance.show !== undefined) {
        // ImageryLayer类型、实体类型或CesiumWind.WindLayer类型
        layerInstance.show = isVisible;
      } else if (layerInstance.primitiveType !== undefined || layerInstance._primitiveType !== undefined) {
        // Primitive类型
        layerInstance.show = isVisible;
      } else if (layerInstance.tileset !== undefined) {
        // Tileset类型
        layerInstance.tileset.show = isVisible;
      } else if (layerInstance.isDataSource !== undefined) {
        // DataSource类型
        layerInstance.isDataSource = isVisible;
      } else if (layerInstance.polygon || layerInstance.polyline || layerInstance.point) {
        // 实体要素类型
        layerInstance.show = isVisible;
      } else if (typeof layerInstance.setWindVisibility === 'function') {
        // CesiumWind.WindLayer类型（自定义方法）
        layerInstance.setWindVisibility(isVisible);
      } else if (typeof layerInstance.setVisible === 'function') {
        // 支持setVisible方法的图层类型
        layerInstance.setVisible(isVisible);
      } else {
        // 尝试直接设置show属性
        layerInstance.show = isVisible;
      }
    } catch (error) {
      console.error('设置图层可见性失败:', error, layerInstance);
    }
  },

  // 移除图层
  removeLayer: function(layerId) {
    layers = layers.filter(layer => layer.id !== layerId);
    this.saveLayerStates();
  },

  // 获取图层列表
  getLayers: function() {
    return layers;
  },

  // 根据ID获取图层
  getLayerById: function(layerId) {
    return layers.find(layer => layer.id === layerId);
  }
};

// 初始化图层管理器并暴露到全局
export function initGlobalLayerManager() {
  if (typeof window !== 'undefined') {
    window.layerManager = layerManager;
    window.layers = layers;
    window.LAYER_IDS = LAYER_IDS;
  }
  layerManager.init();
}