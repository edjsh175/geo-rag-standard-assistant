import React, { useState, useEffect } from 'react';

const Sidebar = ({ onLayerToggle }) => {
  const [collapsed, setCollapsed] = useState(false);
  const [layerStates, setLayerStates] = useState({
    jsonLayer: true,
    tdtLayer: true,
  });

  // 从本地存储加载图层状态
  useEffect(() => {
    try {
      const savedStates = localStorage.getItem('cesiumLayerStates');
      if (savedStates) {
        const states = JSON.parse(savedStates);
        // 映射到我们的layerStates键
        const newStates = {
          jsonLayer: states.jsonLayer !== false,
          tdtLayer: states.tdtLayer !== false,
        };
        setLayerStates(newStates);
        // 通知父组件更新图层可见性
        Object.entries(newStates).forEach(([layerId, isVisible]) => {
          onLayerToggle(layerId, isVisible);
        });
      }
    } catch (error) {
      console.error('加载图层状态失败:', error);
    }
  }, []);

  const toggleSidebar = () => {
    setCollapsed(!collapsed);
  };

  const handleLayerToggle = (layerId) => {
    const newState = !layerStates[layerId];
    setLayerStates({ ...layerStates, [layerId]: newState });
    onLayerToggle(layerId, newState);
  };

  return (
    <div id="sidebar" className={`sidebar ${collapsed ? 'collapsed' : ''}`}>
      <div className="sidebar-header">
        <div className="sidebar-title">功能面板</div>
        <button id="sidebarToggle" className="sidebar-toggle" onClick={toggleSidebar}>
          {collapsed ? '▶' : '◀'}
        </button>
      </div>

      <div className="sidebar-content">
        <div className="sidebar-section">
          <div className="section-title">图层管理</div>

          <div className="layer-item">
            <span className="item-text">JSON数据图层</span>
            <label className="toggle-switch">
              <input type="checkbox" id="jsonLayerToggle" checked={layerStates.jsonLayer} onChange={() => handleLayerToggle('jsonLayer')} />
              <span className="toggle-slider"></span>
            </label>
          </div>

          <div className="layer-item">
            <span className="item-text">天地图图层</span>
            <label className="toggle-switch">
              <input type="checkbox" id="tdtLayerToggle" checked={layerStates.tdtLayer} onChange={() => handleLayerToggle('tdtLayer')} />
              <span className="toggle-slider"></span>
            </label>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Sidebar;