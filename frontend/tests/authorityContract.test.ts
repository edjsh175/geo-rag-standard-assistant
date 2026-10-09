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

  it('does not persist plaintext tokens in localStorage to prevent XSS credential exfiltration', () => {
    const authSource = fs.readFileSync(path.resolve(process.cwd(), 'src/services/authService.ts'), 'utf8');
    const configSource = fs.readFileSync(path.resolve(process.cwd(), 'src/lib/api/config.ts'), 'utf8');
    const sseSource = fs.readFileSync(path.resolve(process.cwd(), 'src/lib/api/contractClient.ts'), 'utf8');

    expect(authSource).not.toContain("localStorage.setItem('geoai_token'");
    expect(configSource).not.toContain("localStorage.getItem('geoai_token'");
    expect(sseSource).not.toContain("localStorage.getItem('geoai_token'");
  });
});
