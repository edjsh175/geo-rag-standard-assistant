import fs from 'fs';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, loadEnv} from 'vite';

const CESIUM_DIST_DIR = 'cesium';
const CESIUM_SOURCE_DIR = path.resolve(__dirname, './node_modules/cesium/Build/Cesium');

const MIME_TYPES: Record<string, string> = {
  '.css': 'text/css; charset=utf-8',
  '.gif': 'image/gif',
  '.glb': 'model/gltf-binary',
  '.html': 'text/html; charset=utf-8',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.js': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.ktx2': 'image/ktx2',
  '.mjs': 'application/javascript; charset=utf-8',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
  '.wasm': 'application/wasm',
  '.xml': 'application/xml; charset=utf-8',
};

function serveCesiumAsset(url: string | undefined, res: NodeJS.WritableStream & { statusCode?: number; setHeader(name: string, value: string): void; end(chunk?: string): void; }) {
  if (!url || !url.startsWith(`/${CESIUM_DIST_DIR}/`)) {
    return false;
  }

  const relativePath = decodeURIComponent(url.split('?')[0].slice(`/${CESIUM_DIST_DIR}/`.length));
  const assetPath = path.resolve(CESIUM_SOURCE_DIR, relativePath);

  if (!assetPath.startsWith(CESIUM_SOURCE_DIR) || !fs.existsSync(assetPath) || fs.statSync(assetPath).isDirectory()) {
    res.statusCode = 404;
    res.end('Not Found');
    return true;
  }

  const extension = path.extname(assetPath).toLowerCase();
  res.setHeader('Content-Type', MIME_TYPES[extension] ?? 'application/octet-stream');
  fs.createReadStream(assetPath).pipe(res);
  return true;
}

function cesiumDevServerPlugin() {
  return {
    name: 'serve-cesium-assets',
    configureServer(server: {
      middlewares: {
        use(handler: (req: { method?: string; url?: string }, res: NodeJS.WritableStream & { statusCode?: number; setHeader(name: string, value: string): void; end(chunk?: string): void; }, next: () => void) => void): void;
      };
    }) {
      server.middlewares.use((req, res, next) => {
        if (req.method !== 'GET' && req.method !== 'HEAD') {
          next();
          return;
        }

        if (!serveCesiumAsset(req.url, res)) {
          next();
        }
      });
    },
  };
}

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, '.', '');
  return {
    plugins: [react(), tailwindcss(), cesiumDevServerPlugin()],
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
          secure: true,
          headers: {
            Referer: 'http://localhost:3000/',
            'User-Agent': 'Mozilla/5.0',
          },
          rewrite: (path) => path.replace(/^\/tianditu/, ''),
        },
      },
    },
  };
});
