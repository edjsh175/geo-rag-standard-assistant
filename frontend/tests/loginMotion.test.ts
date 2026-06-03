import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';

const packageJson = JSON.parse(readFileSync('package.json', 'utf-8'));
const loginPageSource = readFileSync('src/pages/LoginPage.tsx', 'utf-8');

assert.ok(packageJson.dependencies.gsap, 'gsap should be installed as a runtime dependency');
assert.ok(packageJson.dependencies['@gsap/react'], '@gsap/react should be installed as a runtime dependency');

assert.match(loginPageSource, /from 'gsap'/, 'LoginPage should import gsap');
assert.match(loginPageSource, /from '@gsap\/react'/, 'LoginPage should import useGSAP');
assert.match(loginPageSource, /gsap\.registerPlugin\(useGSAP\)/, 'LoginPage should register useGSAP');
assert.match(loginPageSource, /useGSAP\(/, 'LoginPage should configure scoped GSAP animations');
assert.match(loginPageSource, /scope:\s*rootRef/, 'LoginPage GSAP selectors should be scoped to rootRef');
assert.match(loginPageSource, /gsap\.matchMedia\(\)/, 'LoginPage should use gsap.matchMedia for motion preferences');
assert.match(loginPageSource, /prefers-reduced-motion:\s*reduce/, 'LoginPage should honor reduced motion');
assert.match(loginPageSource, /gsap\.quickTo\(/, 'LoginPage should use quickTo for pointer-driven motion');
assert.match(loginPageSource, /data-login-card-shell/, 'LoginPage should animate a card wrapper rather than the glass card');
assert.match(loginPageSource, /data-login-motion-layer/, 'LoginPage should expose decorative motion layers');
assert.match(loginPageSource, /data-login-brand-halo-ring/, 'LoginPage should animate a separate brand halo ring');
assert.doesNotMatch(loginPageSource, /data-login-pointer-glow/, 'LoginPage should not render a rectangular pointer glow layer');
assert.doesNotMatch(loginPageSource, /\bpointerLight\b/, 'LoginPage should not keep pointer glow animation code');
assert.doesNotMatch(loginPageSource, /gsap\.quickTo\(pointerLight,/, 'LoginPage should not quickTo a pointer glow layer');
assert.match(loginPageSource, /gsap\.to\(brandHaloRing,/, 'LoginPage should animate the brand halo ring');
assert.doesNotMatch(loginPageSource, /gsap\.to\(brandHalo,/, 'LoginPage should not scale the brand icon container directly');
assert.match(loginPageSource, /data-login-top-ambient/, 'LoginPage should expose an animated top-left ambient light');
assert.match(loginPageSource, /data-login-right-ambient/, 'LoginPage should expose an animated right-bottom ambient light');
assert.doesNotMatch(loginPageSource, /data-login-scanline/, 'LoginPage should remove the left-to-right scan beam');
assert.doesNotMatch(loginPageSource, /\bscanLine\b/, 'LoginPage should not keep scan beam animation code');
assert.doesNotMatch(loginPageSource, /x:\s*'185vw'/, 'LoginPage should not keep the old scan beam travel');
assert.doesNotMatch(loginPageSource, /gsap\.timeline\(/, 'LoginPage should not keep the old scan beam timeline');
assert.match(loginPageSource, /gsap\.ticker\.add/, 'LoginPage should use the GSAP ticker for ambient orbit motion');
assert.match(loginPageSource, /gsap\.ticker\.remove/, 'LoginPage should clean up the ambient orbit ticker');
assert.match(loginPageSource, /Math\.sin/, 'LoginPage should use sine functions for non-linear orbit timing');
assert.match(loginPageSource, /Math\.cos/, 'LoginPage should use cosine functions for elliptical orbit positions');
assert.match(loginPageSource, /t \* 0\.22/, 'ambient orbit should include the base angular speed');
assert.match(loginPageSource, /Math\.sin\(t \* 0\.47\) \* 0\.28/, 'ambient orbit should include a faster speed modulation wave');
assert.match(loginPageSource, /Math\.sin\(t \* 0\.13\) \* 0\.18/, 'ambient orbit should include a slower speed modulation wave');
assert.match(loginPageSource, /xPercent:\s*-50/, 'ambient lights should be center-anchored for orbit motion');
assert.match(loginPageSource, /yPercent:\s*-50/, 'ambient lights should be center-anchored for orbit motion');
assert.match(loginPageSource, /Math\.PI \* 1\.25/, 'top ambient light should start near the top-left orbit position');
assert.match(loginPageSource, /Math\.PI \* 0\.25/, 'right ambient light should start near the right-bottom orbit position');
assert.match(loginPageSource, /centeredY \* -10\.5/, 'card rotationX should use the amplified tilt amplitude');
assert.match(loginPageSource, /centeredX \* 12\.75/, 'card rotationY should use the amplified tilt amplitude');
assert.match(loginPageSource, /centeredY \* 12/, 'card vertical parallax should use the amplified tilt amplitude');

console.log('loginMotion tests passed');
