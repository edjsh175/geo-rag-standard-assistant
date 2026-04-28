import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import RootApp from './RootApp.tsx';
import './index.css';

(globalThis as typeof globalThis & { CESIUM_BASE_URL?: string }).CESIUM_BASE_URL =
  import.meta.env.VITE_CESIUM_BASE_URL || '/cesium/';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RootApp />
  </StrictMode>,
);
