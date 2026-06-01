import { strict as assert } from 'node:assert';

import {
  expandBoundsForPadding,
  getChatPanelWidth,
  getMapFitPadding,
} from '../src/lib/mapViewport';

const nearlyEqual = (actual: number, expected: number, epsilon = 0.001) => {
  assert.ok(
    Math.abs(actual - expected) <= epsilon,
    `expected ${actual} to be within ${epsilon} of ${expected}`
  );
};

const standardPadding = getMapFitPadding('standard', 1920);
const expandedPadding = getMapFitPadding('chatExpanded', 1920);

assert.equal(getChatPanelWidth('standard', 1920), 420);
assert.equal(getChatPanelWidth('chatExpanded', 1920), 780);
assert.equal(standardPadding[1], 484);
assert.equal(expandedPadding[1], 844);
assert.ok(
  expandedPadding[1] > standardPadding[1],
  'expanded chat layout should reserve more right-side map padding'
);

const expandedBounds = expandBoundsForPadding(
  [100, 20, 110, 30],
  expandedPadding,
  [1920, 1080]
);

assert.ok(expandedBounds[0] < 100, 'west edge should expand for left padding');
assert.ok(expandedBounds[2] > 110, 'east edge should expand for right padding');
assert.ok(
  expandedBounds[2] - 110 > 100 - expandedBounds[0],
  'right-side overlay should expand the east side more than the west side'
);
nearlyEqual(expandedBounds[0], 99.614);
nearlyEqual(expandedBounds[2], 118.147);

console.log('mapViewport tests passed');
