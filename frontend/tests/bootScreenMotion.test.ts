import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';

const packageJson = JSON.parse(readFileSync('package.json', 'utf-8'));
const bootScreenSource = readFileSync('src/components/BootScreen.tsx', 'utf-8');

assert.ok(packageJson.dependencies.gsap, 'gsap should be installed as a runtime dependency');
assert.ok(packageJson.dependencies['@gsap/react'], '@gsap/react should be installed as a runtime dependency');

assert.match(bootScreenSource, /from 'gsap'/, 'BootScreen should import gsap');
assert.match(bootScreenSource, /from '@gsap\/react'/, 'BootScreen should import useGSAP');
assert.match(bootScreenSource, /gsap\.registerPlugin\(useGSAP\)/, 'BootScreen should register useGSAP');
assert.match(bootScreenSource, /useGSAP\(/, 'BootScreen should configure scoped GSAP animations');
assert.match(bootScreenSource, /scope:\s*rootRef/, 'BootScreen GSAP selectors should be scoped to rootRef');
assert.match(bootScreenSource, /dependencies:\s*\[phase,\s*error,\s*theme\]/, 'BootScreen should resync animation when phase, error, or theme changes');
assert.match(bootScreenSource, /revertOnUpdate:\s*true/, 'BootScreen should clean up and rebuild animations on dependency changes');

assert.match(bootScreenSource, /data-boot-root/, 'BootScreen should expose a scoped root marker');
assert.match(bootScreenSource, /data-boot-card-shell/, 'BootScreen should expose the tilt card shell');
assert.match(bootScreenSource, /data-boot-ready-panel/, 'BootScreen should expose the READY panel');
assert.match(bootScreenSource, /data-boot-action-arrow/, 'BootScreen should expose the primary action arrow');

assert.match(bootScreenSource, /gsap\.matchMedia\(\)/, 'BootScreen should use gsap.matchMedia for motion preferences');
assert.match(bootScreenSource, /prefers-reduced-motion:\s*reduce/, 'BootScreen should honor reduced motion');
assert.match(bootScreenSource, /isDesktop:\s*'\(min-width:\s*1024px\)'/, 'BootScreen should only enable pointer tilt on desktop');

assert.match(bootScreenSource, /gsap\.quickTo\(cardShell,\s*'rotationX'/, 'BootScreen should quickTo card shell rotationX');
assert.match(bootScreenSource, /gsap\.quickTo\(cardShell,\s*'rotationY'/, 'BootScreen should quickTo card shell rotationY');
assert.match(bootScreenSource, /gsap\.quickTo\(cardShell,\s*'y'/, 'BootScreen should quickTo card shell y');
assert.match(bootScreenSource, /duration:\s*0\.7,\s*ease:\s*'power3\.out'/, 'BootScreen tilt should reuse the LoginPage quickTo feel');
assert.match(bootScreenSource, /centeredY \* -10\.5/, 'BootScreen rotationX should match LoginPage tilt amplitude');
assert.match(bootScreenSource, /centeredX \* 12\.75/, 'BootScreen rotationY should match LoginPage tilt amplitude');
assert.match(bootScreenSource, /centeredY \* 12/, 'BootScreen vertical parallax should match LoginPage amplitude');

assert.match(bootScreenSource, /gsap\.timeline\(/, 'BootScreen should use a GSAP timeline for ready entry');
assert.match(bootScreenSource, /autoAlpha:\s*0,\s*y:\s*10,\s*scale:\s*0\.985/, 'READY panel should enter from the planned GSAP state');
assert.match(bootScreenSource, /y:\s*-4,[\s\S]*duration:\s*4\.2,[\s\S]*repeat:\s*-1,[\s\S]*yoyo:\s*true,[\s\S]*ease:\s*'sine\.inOut'/, 'BootScreen should keep a subtle LoginPage-scale floating loop');
assert.match(bootScreenSource, /arrowXTo\(5\)/, 'BootScreen button hover should move the arrow like LoginPage');
assert.match(bootScreenSource, /buttonYTo\(-1\)/, 'BootScreen button hover should lift the button like LoginPage');

assert.doesNotMatch(bootScreenSource, /<motion\.div/, 'BootScreen primary animated nodes should be driven by GSAP instead of motion.div');

console.log('bootScreenMotion tests passed');
