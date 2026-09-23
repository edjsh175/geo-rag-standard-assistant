import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { test } from '@playwright/test';
import {
  SearchObserver,
  dependencyFailureResult,
  executeTask,
  loadManifest,
  orderScenarioTasks,
  type ExecutedTaskResult,
  type SearchExchange,
} from './geoaiHarness';

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(currentDir, '..', '..');
const resultDir = process.env.GEOAI_E2E_RESULT_DIR
  ? path.resolve(process.env.GEOAI_E2E_RESULT_DIR)
  : path.join(repoRoot, 'evals', 'results', 'latest');

test('executes the complete GeoAI manifest through the real browser application', async ({ browser, baseURL }) => {
  const manifest = loadManifest(repoRoot);
  const scenarios = new Map<string, typeof manifest>();
  for (const task of manifest) scenarios.set(task.scenario, [...(scenarios.get(task.scenario) ?? []), task]);

  const results: ExecutedTaskResult[] = [];
  const byId = new Map<string, ExecutedTaskResult>();
  fs.mkdirSync(resultDir, { recursive: true });

  for (const [scenarioName, scenarioTasks] of scenarios) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const observer = new SearchObserver(page);
    const scenarioExchanges: SearchExchange[] = [];
    await page.goto(baseURL ?? 'http://127.0.0.1:3000');

    for (const task of orderScenarioTasks(scenarioTasks)) {
      const failedDependency = task.depends_on.find((dependency) => byId.get(dependency)?.completed === false);
      let result: ExecutedTaskResult;
      if (failedDependency) {
        result = dependencyFailureResult(task, failedDependency);
      } else {
        const exchangeStart = observer.exchanges.length;
        try {
          result = await executeTask(page, observer, task, repoRoot, scenarioExchanges);
          scenarioExchanges.push(...observer.exchanges.slice(exchangeStart));
        } catch (error) {
          result = {
            ...dependencyFailureResult(task, 'execution_error'),
            failure_reason: error instanceof Error ? error.message : String(error),
          };
        }
      }
      const screenshot = path.join(resultDir, `${task.id}.png`);
      await page.screenshot({ path: screenshot, fullPage: true });
      result.artifacts = { screenshot };
      results.push(result);
      byId.set(task.id, result);
    }
    await context.close();
    void scenarioName;
  }

  fs.writeFileSync(path.join(resultDir, 'results.json'), JSON.stringify(results, null, 2), 'utf-8');
  test.expect(results).toHaveLength(36);
  test.expect(new Set(results.map((item) => item.id)).size).toBe(36);
  test.expect(results.every((item) => item.completed)).toBe(true);
});
