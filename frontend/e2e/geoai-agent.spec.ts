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
  const targetIds = process.env.GEOAI_TASK_IDS
    ? new Set(process.env.GEOAI_TASK_IDS.split(',').map((s) => s.trim()))
    : null;
  const targetScenario = process.env.GEOAI_SCENARIO?.trim();
  const effectiveManifest = manifest.filter((t) => {
    if (targetIds && !targetIds.has(t.id)) return false;
    if (targetScenario && t.scenario !== targetScenario) return false;
    return true;
  });
  const scenarios = new Map<string, typeof manifest>();
  for (const task of effectiveManifest) scenarios.set(task.scenario, [...(scenarios.get(task.scenario) ?? []), task]);

  const results: ExecutedTaskResult[] = [];
  const byId = new Map<string, ExecutedTaskResult>();
  fs.mkdirSync(resultDir, { recursive: true });

  for (const [scenarioName, scenarioTasks] of scenarios) {
    const context = await browser.newContext();
    const page = await context.newPage();
    const observer = new SearchObserver(page);
    const scenarioExchanges: SearchExchange[] = [];
    await page.goto(baseURL ?? 'http://127.0.0.1:3000');

    // Wait for search interface, boot screen, or login page to appear
    const searchInput = page.getByPlaceholder('输入规划指令或搜索关键词...');
    const loginInput = page.getByPlaceholder('请输入管理员账号');
    const bootButton = page.locator('button[data-boot-action]');

    const matched = await Promise.race([
      searchInput.waitFor({ state: 'visible', timeout: 20_000 }).then(() => 'search'),
      loginInput.waitFor({ state: 'visible', timeout: 20_000 }).then(() => 'login'),
      bootButton.waitFor({ state: 'visible', timeout: 20_000 }).then(() => 'boot'),
    ]).catch(() => null);

    if (matched === 'login' || await loginInput.isVisible().catch(() => false)) {
      await loginInput.fill(process.env.ADMIN_USERNAME || 'admin');
      await page.getByPlaceholder('请输入登录密码').fill(process.env.ADMIN_PASSWORD || 'admin');
      await page.locator('button[type="submit"]').click();
    }

    // Dismiss boot screen if present
    try {
      await bootButton.waitFor({ state: 'visible', timeout: 15_000 });
      await bootButton.click();
      await page.waitForTimeout(600);
    } catch {
      // Boot screen might have already been bypassed or dismissed
    }

    await searchInput.waitFor({ state: 'visible', timeout: 30_000 });

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
      try {
        await page.screenshot({ path: screenshot, fullPage: true });
        result.artifacts = { screenshot };
      } catch {
        // Screenshot failure should not fail the evaluation
      }
      results.push(result);
      byId.set(task.id, result);
      // Persist results progressively so incremental progress is never lost
      fs.writeFileSync(path.join(resultDir, 'results.json'), JSON.stringify(results, null, 2), 'utf-8');
    }
    await context.close();
    void scenarioName;
  }

  fs.writeFileSync(path.join(resultDir, 'results.json'), JSON.stringify(results, null, 2), 'utf-8');
  test.expect(results).toHaveLength(effectiveManifest.length);
  test.expect(new Set(results.map((item) => item.id)).size).toBe(effectiveManifest.length);
  test.expect(results.every((item) => item.completed)).toBe(true);
});
