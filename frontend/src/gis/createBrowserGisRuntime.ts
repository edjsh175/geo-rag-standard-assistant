import type Map from 'ol/Map';
import { createUserVectorCapabilities } from './userVectorCapabilities';
import { createMapContextReader } from './mapContext';
import { createFrontendExecutor } from './frontendExecutor';

export const createBrowserGisRuntime = (
  map: Map,
  getFitPadding: () => number[],
  onLayerVisibilityChange?: (layerRef: string, visible: boolean) => void,
  selectRegion?: (region: { adcode: string; name: string }) => Promise<Record<string, unknown>>,
) => {
  const capabilities = createUserVectorCapabilities(map, getFitPadding);
  const snapshot = createMapContextReader(map, capabilities.list);
  const executor = createFrontendExecutor({
    map,
    capabilities,
    snapshot,
    onLayerVisibilityChange,
    selectRegion: selectRegion ?? (async () => { throw new Error('region selection unavailable'); }),
  });
  return {
    ...executor,
    dispose: capabilities.dispose,
  };
};
