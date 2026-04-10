import React, { useState } from 'react';

const Controls = ({ onZoomIn, onZoomOut, onResetView, onViewChange }) => {
  const [selectedView, setSelectedView] = useState('china');

  const handleViewChange = (e) => {
    const viewKey = e.target.value;
    setSelectedView(viewKey);
    onViewChange(viewKey);
  };

  return (
    <div id="mainControls" className="main-controls">
      <div className="control-group">
        <button id="zoomIn" className="control-btn" onClick={onZoomIn}>放大</button>
        <button id="zoomOut" className="control-btn" onClick={onZoomOut}>缩小</button>
        <button id="resetView" className="control-btn" onClick={onResetView}>复位</button>
      </div>

      <div className="control-group">
        <select id="viewSwitcher" className="control-select" value={selectedView} onChange={handleViewChange}>
          <option value="china">中国区域</option>
          <option value="beijing">北京视角</option>
          <option value="shanghai">上海视角</option>
          <option value="global">全球视角</option>
        </select>
      </div>
    </div>
  );
};

export default Controls;