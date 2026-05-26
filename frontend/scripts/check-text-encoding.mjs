import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, '..', '..');

const textExtensions = new Set([
  '.css',
  '.html',
  '.js',
  '.jsx',
  '.json',
  '.md',
  '.py',
  '.toml',
  '.ts',
  '.tsx',
  '.txt',
  '.yml',
  '.yaml',
]);

const textFileNames = new Set(['.editorconfig', '.gitattributes', '.gitignore']);

const mojibakePatterns = [
  { label: 'replacement character', regex: /�/u },
  { label: 'UTF-8-as-GBK mojibake: 鍖', regex: /鍖/u },
  { label: 'UTF-8-as-GBK mojibake: 绌', regex: /绌/u },
  { label: 'UTF-8-as-GBK mojibake: 鐪', regex: /鐪/u },
  { label: 'truncated mojibake quote: €?', regex: /€\?/u },
];

const candidateFiles = execFileSync(
  'git',
  ['ls-files', '--cached', '--others', '--exclude-standard'],
  {
    cwd: repoRoot,
    encoding: 'utf8',
  },
)
  .split(/\r?\n/)
  .filter(Boolean)
  .filter((filePath) => {
    const fileName = path.basename(filePath);
    return textFileNames.has(fileName) || textExtensions.has(path.extname(filePath).toLowerCase());
  });

const failures = [];

for (const relativePath of candidateFiles) {
  const absolutePath = path.join(repoRoot, relativePath);
  const bytes = readFileSync(absolutePath);
  if (bytes.length >= 3 && bytes[0] === 0xef && bytes[1] === 0xbb && bytes[2] === 0xbf) {
    failures.push(`${relativePath}: UTF-8 BOM detected`);
  }

  const text = bytes.toString('utf8');
  const lines = text.split(/\r?\n/);

  for (const { label, regex } of mojibakePatterns) {
    const lineIndex = lines.findIndex((line) => regex.test(line));
    if (lineIndex !== -1) {
      failures.push(`${relativePath}:${lineIndex + 1}: ${label}`);
      break;
    }
  }
}

if (failures.length > 0) {
  console.error('Text encoding check failed:');
  for (const failure of failures) {
    console.error(`- ${failure}`);
  }
  process.exit(1);
}

console.log(`Text encoding check passed (${candidateFiles.length} files scanned).`);
