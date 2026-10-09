import { useState, useEffect, useRef, useCallback } from 'react';
import { useMapStore, zoomToHeight, heightToZoom } from '../store/useMapStore';
import { setActiveBrowserGisRuntime } from '../gis/browserBridge';
import { getChatPanelWidth, type MapLayoutMode } from '../lib/mapViewport';

export interface MapViewerLayers {
  admin: boolean;
  wms: boolean;
}

export function useMapViewerState() {
  const viewMode = useMapStore((s) => s.viewMode);
  const setViewMode = useMapStore((s) => s.setViewMode);
  const activeRegion = useMapStore((s) => s.activeRegion);
  const setActiveRegion = useMapStore((s) => s.setActiveRegion);
  const setViewState = useMapStore((s) => s.setViewState);
  const resetView = useMapStore((s) => s.resetView);

  const [layers, setLayers] = useState<MapViewerLayers>({
    admin: true,
    wms: false,
  });

  const [chatExpanded, setChatExpanded] = useState(false);
  const [viewportWidth, setViewportWidth] = useState(
    () => (typeof window === 'undefined' ? 1920 : window.innerWidth)
  );

  const [mapReady, setMapReady] = useState<{ '2D': boolean; '3D': boolean }>({
    '2D': false,
    '3D': false,
  });

  const olContainerRef = useRef<HTMLDivElement>(null);
  const cesiumContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleResize = () => setViewportWidth(window.innerWidth);
    handleResize();
    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    setActiveBrowserGisRuntime(viewMode === '3D' ? '3d' : '2d');
  }, [viewMode]);

  const markMapReady = useCallback((mode: '2D' | '3D') => {
    setMapReady((prev) => (prev[mode] ? prev : { ...prev, [mode]: true }));
  }, []);

  const handleMapReady2D = useCallback(() => {
    markMapReady('2D');
  }, [markMapReady]);

  const handleMapReady3D = useCallback(() => {
    markMapReady('3D');
  }, [markMapReady]);

  const handleViewModeSwitch = useCallback((targetMode: '2D' | '3D') => {
    if (targetMode === viewMode) return;

    if (viewMode === '3D' && targetMode === '2D') {
      const cesiumEl = document.getElementById('cesiumContainer');
      if (cesiumEl && (cesiumEl as any).__snapshotView) {
        (cesiumEl as any).__snapshotView();
      }
      const { height, center } = useMapStore.getState().viewState;
      const zoom = heightToZoom(height, center[1]);
      setViewState({ zoom, center });
    } else {
      const olEl = olContainerRef.current?.querySelector('div[class]') ?? olContainerRef.current;
      const mapSection = document.querySelector('[data-ol-map]');
      if (mapSection && (mapSection as any).__snapshotView) {
        (mapSection as any).__snapshotView();
      } else {
        document.querySelectorAll('.w-full.h-full').forEach((el) => {
          if ((el as any).__snapshotView) (el as any).__snapshotView();
        });
      }
      const { zoom, center } = useMapStore.getState().viewState;
      const height = zoomToHeight(zoom, center[1]);
      setViewState({ height, center });
    }

    setViewMode(targetMode);
  }, [viewMode, setViewMode, setViewState]);

  const handleAgentLayerVisibilityChange = useCallback((layerRef: string, visible: boolean) => {
    if (layerRef === 'system:provinces') {
      setLayers((prev) => ({ ...prev, admin: visible }));
      return;
    }
    if (layerRef === 'base:satellite') {
      setLayers((prev) => ({ ...prev, wms: visible }));
      return;
    }
    if (layerRef === 'base:vector') {
      setLayers((prev) => ({ ...prev, wms: !visible }));
    }
  }, []);

  const toggleLayer = useCallback((layer: keyof MapViewerLayers) => {
    setLayers((prev) => ({ ...prev, [layer]: !prev[layer] }));
  }, []);

  const mapLayoutMode: MapLayoutMode = chatExpanded ? 'chatExpanded' : 'standard';
  const chatPanelWidth = getChatPanelWidth(mapLayoutMode, viewportWidth);

  return {
    viewMode,
    setViewMode,
    activeRegion,
    setActiveRegion,
    resetView,
    layers,
    setLayers,
    toggleLayer,
    mapReady,
    handleMapReady2D,
    handleMapReady3D,
    handleViewModeSwitch,
    handleAgentLayerVisibilityChange,
    olContainerRef,
    cesiumContainerRef,
    chatExpanded,
    setChatExpanded,
    viewportWidth,
    mapLayoutMode,
    chatPanelWidth,
  };
}
