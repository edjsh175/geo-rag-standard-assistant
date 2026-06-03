import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';

const appSource = readFileSync('src/App.tsx', 'utf-8');

const titleMatch = appSource.match(
  /<h2 className="([^"]*)">\{selectedDocument\.metadata\.title\}<\/h2>/
);

assert.ok(titleMatch, 'document detail drawer should render the selected document title');
assert.match(
  titleMatch[1],
  /\btext-on-background(?:\/\d+)?\b/,
  'document detail title should use the theme-aware on-background text token'
);
assert.doesNotMatch(
  titleMatch[1],
  /text-\[#f0f0f0\]/,
  'document detail title should not use a hard-coded dark-mode text color'
);

console.log('documentDetailTheme tests passed');
