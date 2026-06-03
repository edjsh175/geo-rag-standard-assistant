import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, loadEnv} from 'vite';

const CESIUM_DIST_DIR = 'cesium';

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, '.', '');
  return {
    plugins: [react(), tailwindcss()],
    define: {
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
      CESIUM_BASE_URL: JSON.stringify(`/${CESIUM_DIST_DIR}/`),
    },
    resolve: {
      dedupe: ['react', 'react-dom'],
      alias: [
        { find: '@', replacement: path.resolve(__dirname, './src') },
        { find: /^react$/, replacement: path.resolve(__dirname, './node_modules/react') },
        { find: /^react\/jsx-runtime$/, replacement: path.resolve(__dirname, './node_modules/react/jsx-runtime.js') },
        { find: /^react\/jsx-dev-runtime$/, replacement: path.resolve(__dirname, './node_modules/react/jsx-dev-runtime.js') },
        { find: /^react-dom$/, replacement: path.resolve(__dirname, './node_modules/react-dom') },
        { find: /^react-dom\/client$/, replacement: path.resolve(__dirname, './node_modules/react-dom/client.js') },
      ],
    },
    optimizeDeps: {
      entries: ['index.html'],
    },
    server: {
      port: 3000,
      host: '0.0.0.0',
      hmr: process.env.DISABLE_HMR !== 'true',
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/api/, '/api'),
        },
        '/tianditu': {
          target: 'https://t0.tianditu.gov.cn',
          changeOrigin: true,
          rewrite: (path) => path.replace(/^\/tianditu/, ''),
        },
      },
    },
  };
});
