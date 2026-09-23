import { describe, expect, it } from 'vitest';
import { dependencyFailureResult, evaluateAssertions, orderScenarioTasks, type EvalTask } from '../e2e/geoaiHarness';

const task = (id: string, depends_on: string[] = []): EvalTask => ({
  id,
  category: 'test',
  scenario: 'scenario',
  depends_on,
  prompt: id,
  assertions: [{ type: 'published_answer_present' }],
});

describe('GeoAI E2E harness', () => {
  it('orders dependencies before dependent tasks', () => {
    expect(orderScenarioTasks([task('B', ['A']), task('A')]).map((item) => item.id)).toEqual(['A', 'B']);
  });

  it('derives completion evidence from real exchange payloads', () => {
    const assertions = evaluateAssertions(task('A'), [{ request: {}, response: { generated_answer: 'ok', publication_state: 'published' } }], []);
    expect(assertions).toEqual([expect.objectContaining({ type: 'published_answer_present', passed: true })]);
  });

  it('records dependency failures as failed evidence rather than skipping', () => {
    const result = dependencyFailureResult(task('B', ['A']), 'A');
    expect(result.completed).toBe(false);
    expect(result.failure_reason).toBe('dependency_failed:A');
    expect(result.assertions.every((item) => item.passed === false)).toBe(true);
  });
});
