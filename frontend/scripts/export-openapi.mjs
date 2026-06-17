import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { spawnSync } from 'node:child_process';

const frontendRoot = process.cwd();
const projectRoot = path.resolve(frontendRoot, '..');
const scriptPath = path.join(projectRoot, 'scripts', 'export_openapi.py');
const windowsVenvPython = path.join(projectRoot, 'Backend', '.venv', 'Scripts', 'python.exe');
const posixVenvPython = path.join(projectRoot, 'Backend', '.venv', 'bin', 'python');

const pythonExecutable = fs.existsSync(windowsVenvPython)
  ? windowsVenvPython
  : fs.existsSync(posixVenvPython)
    ? posixVenvPython
    : 'python';

const result = spawnSync(pythonExecutable, [scriptPath], {
  cwd: projectRoot,
  stdio: 'inherit',
  shell: false,
});

if (result.status !== 0) {
  process.exit(result.status ?? 1);
}
