import { describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

describe('frontend authority contract', () => {
  it('does not infer map region from natural-language chat before Controller execution', () => {
    const appSource = fs.readFileSync(path.resolve(process.cwd(), 'src/App.tsx'), 'utf8');

    expect(appSource).not.toContain('extractRegionFromQuery');
    expect(appSource).not.toContain('regionFromQuery');
    expect(appSource).toContain('const regionContext = activeRegion;');
  });
});
