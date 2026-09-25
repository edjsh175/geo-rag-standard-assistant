import type Map from 'ol/Map';
import { createUserVectorCapabilities } from './userVectorCapabilities';
import { createMapContextReader } from './mapContext';
import { createFrontendExecutor } from './frontendExecutor';

export const createBrowserGisRuntime = (map: Map, getFitPadding: () => number[]) => {
  const capabilities = createUserVectorCapabilities(map, getFitPadding);
  const snapshot = createMapContextReader(map, capabilities.list);
  const executor = createFrontendExecutor({ map, capabilities, snapshot });
  return {
    ...executor,
    dispose: capabilities.dispose,
  };
};
