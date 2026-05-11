import fs from 'node:fs';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const cesiumSourceDir = path.join(projectRoot, 'node_modules', 'cesium', 'Build', 'Cesium');
const cesiumPublicDir = path.join(projectRoot, 'public', 'cesium');
const staticDirs = ['Assets', 'ThirdParty', 'Workers', 'Widgets'];

function syncWithPowerShell() {
  const scriptPath = path.join(__dirname, 'sync-cesium-assets.ps1');
  execFileSync(
    'powershell',
    ['-ExecutionPolicy', 'Bypass', '-File', scriptPath],
    { cwd: projectRoot, stdio: 'inherit' }
  );
}

function syncWithFs() {
  fs.mkdirSync(cesiumPublicDir, { recursive: true });

  for (const dir of staticDirs) {
    fs.cpSync(
      path.join(cesiumSourceDir, dir),
      path.join(cesiumPublicDir, dir),
      { recursive: true, force: true }
    );
  }

  console.log(`Synced Cesium assets to ${cesiumPublicDir}`);
}

if (process.platform === 'win32') {
  syncWithPowerShell();
} else {
  syncWithFs();
}
