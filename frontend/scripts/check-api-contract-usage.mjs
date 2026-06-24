import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const projectRoot = process.cwd();
const servicesDir = path.join(projectRoot, 'src', 'services');
const generatedSchema = path.join(projectRoot, 'src', 'lib', 'api', 'generated', 'schema.d.ts');
const appEntry = path.join(projectRoot, 'src', 'App.tsx');

const failures = [];

if (!fs.existsSync(generatedSchema)) {
  failures.push(`Missing generated OpenAPI schema: ${path.relative(projectRoot, generatedSchema)}`);
}

for (const entry of fs.readdirSync(servicesDir, { withFileTypes: true })) {
  if (!entry.isFile() || !entry.name.endsWith('.ts')) continue;
  const filePath = path.join(servicesDir, entry.name);
  const source = fs.readFileSync(filePath, 'utf8');

  if (source.includes("from '../lib/api/config'") || source.includes('from "../lib/api/config"')) {
    failures.push(`${path.relative(projectRoot, filePath)} imports legacy apiClient directly`);
  }

  if (source.includes("from '../types/api'") || source.includes('from "../types/api"')) {
    failures.push(`${path.relative(projectRoot, filePath)} imports hand-written API DTOs directly`);
  }
}

if (fs.existsSync(appEntry)) {
  const appSource = fs.readFileSync(appEntry, 'utf8');
  if (/role\s*:\s*['"]system['"]/.test(appSource)) {
    failures.push('src/App.tsx still constructs a client-side system role message');
  }
}

if (failures.length > 0) {
  console.error('API contract usage check failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log('API contract usage check passed.');
