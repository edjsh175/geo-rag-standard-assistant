/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_TIANDITU_TK: string;
  readonly VITE_CESIUM_BASE_URL: string;
  readonly VITE_HOST: string;
  readonly VITE_PORT: string;
  readonly VITE_DISABLE_HMR: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
