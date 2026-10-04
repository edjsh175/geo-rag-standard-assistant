import { expect, test, type Page, type Request, type Response } from '@playwright/test';

type SseEvent = {
  event_type: string;
  sequence: number;
  session_id?: string;
  turn_id?: string;
  trace_id?: string;
  payload: Record<string, unknown>;
};

type StreamRequest = {
  body: Record<string, any>;
};

class RegionScopeObserver {
  readonly events: SseEvent[] = [];
  readonly results: Array<Record<string, unknown>> = [];
  readonly streamRequests: StreamRequest[] = [];

  constructor(page: Page) {
    page.on('request', (request: Request) => {
      const url = new URL(request.url());
      if (request.method() !== 'POST' || url.pathname !== '/api/search/query/stream') return;
      try {
        this.streamRequests.push({ body: request.postDataJSON() as Record<string, any> });
      } catch {
        this.streamRequests.push({ body: {} });
      }
    });
    page.on('response', (response: Response) => {
      if (new URL(response.url()).pathname !== '/api/search/query/stream') return;
      void response.text().then((body) => {
        for (const frame of body.split(/\r?\n\r?\n/)) {
          const lines = frame.split(/\r?\n/);
          const eventType = lines.find((line) => line.startsWith('event:'))?.slice(6).trim();
          const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n');
          if (!eventType || !data) continue;
          try {
            const parsed = JSON.parse(data) as Record<string, unknown>;
            if (eventType === 'result') {
              this.results.push(parsed);
            } else {
              this.events.push({ event_type: eventType, ...parsed as Omit<SseEvent, 'event_type'> });
            }
          } catch {
            // Missing events are surfaced by the assertions below.
          }
        }
      }).catch(() => undefined);
    });
  }
}

const enterRealApplication = async (page: Page) => {
  await page.goto('/');
  const searchInput = page.getByPlaceholder('输入规划指令或搜索关键词...');
  const loginInput = page.getByPlaceholder('请输入管理员账号');
  const bootButton = page.locator('button[data-boot-action]');
  const initialState = await Promise.race([
    searchInput.waitFor({ state: 'visible', timeout: 30_000 }).then(() => 'ready'),
    loginInput.waitFor({ state: 'visible', timeout: 30_000 }).then(() => 'login'),
    bootButton.waitFor({ state: 'visible', timeout: 30_000 }).then(() => 'boot'),
  ]).catch(() => 'unknown');
  if (initialState === 'login' || await loginInput.isVisible().catch(() => false)) {
    await loginInput.fill(process.env.ADMIN_USERNAME || 'admin');
    await page.getByPlaceholder('请输入登录密码').fill(process.env.ADMIN_PASSWORD || 'admin');
    await page.locator('button[type="submit"]').click();
    await expect(bootButton).toBeVisible({ timeout: 30_000 });
  }
  if (await bootButton.isVisible().catch(() => false)) await bootButton.click();
  await expect(searchInput).toBeVisible({ timeout: 60_000 });
};

const browserContext = (page: Page) => page.evaluate(() => {
  const bridge = (window as Window & {
    __GEOAI_BROWSER_GIS__?: { getContext?: () => Record<string, any> };
  }).__GEOAI_BROWSER_GIS__;
  return bridge?.getContext?.() ?? null;
});

const switchDimension = async (page: Page, dimension: '2d' | '3d') => {
  if (dimension === '3d') await page.getByRole('button', { name: /3D 地球/ }).click();
  else await page.getByRole('button', { name: /2D 地图/ }).click();
  await expect.poll(async () => (await browserContext(page))?.dimension, { timeout: 90_000 }).toBe(dimension);
  await expect.poll(async () => (await browserContext(page))?.ready, { timeout: 90_000 }).toBe(true);
  await expect.poll(async () => (await browserContext(page))?.supported_tools?.includes('select_region'), { timeout: 90_000 }).toBe(true);
};

const submitPrompt = async (page: Page, prompt: string) => {
  const input = page.getByPlaceholder('输入规划指令或搜索关键词...');
  await input.fill(prompt);
  await input.press('Enter');
};

const runRegionCatalogueCase = async (page: Page, dimension: '2d' | '3d') => {
  test.setTimeout(420_000);
  const observer = new RegionScopeObserver(page);
  await enterRealApplication(page);
  await switchDimension(page, dimension);

  const eventStart = observer.events.length;
  const requestStart = observer.streamRequests.length;
  const resultStart = observer.results.length;
  await submitPrompt(page, '查一下四川有哪些标准。');

  await expect.poll(
    () => observer.events.slice(eventStart).some((event) => event.event_type === 'publication_completed'),
    { timeout: 240_000 },
  ).toBe(true);
  await expect.poll(
    () => observer.results.slice(resultStart).some((result) => result.publication_state !== 'tool_execution_required'),
    { timeout: 240_000 },
  ).toBe(true);

  const events = observer.events.slice(eventStart);
  const selectRequested = events.find(
    (event) => event.event_type === 'browser_tool_requested' && event.payload.tool_name === 'select_region',
  );
  const selectCompleted = events.find(
    (event) => event.event_type === 'browser_tool_completed' && event.payload.tool_name === 'select_region',
  );
  const catalogueStarted = events.find(
    (event) => event.event_type === 'tool_started' && event.payload.tool_name === 'list_applicable_standards',
  );

  expect(selectRequested, `${dimension} must request select_region`).toBeTruthy();
  expect(selectCompleted, `${dimension} must persist the select_region receipt`).toBeTruthy();
  expect(catalogueStarted, `${dimension} must use the catalogue tool for a list query`).toBeTruthy();
  expect(selectCompleted!.sequence).toBeLessThan(catalogueStarted!.sequence);

  const resumeRequest = observer.streamRequests.slice(requestStart).find((request) =>
    request.body?.browser_tool_receipt?.tool_name === 'select_region',
  );
  expect(resumeRequest, `${dimension} must resume from the real browser receipt`).toBeTruthy();
  expect(resumeRequest?.body?.map_context?.active_region?.adcode).toBe('510000');
  expect(resumeRequest?.body?.browser_tool_receipt?.map_context?.active_region?.adcode).toBe('510000');

  await expect.poll(async () => (await browserContext(page))?.active_region?.adcode, { timeout: 30_000 }).toBe('510000');
  await expect.poll(async () => (await browserContext(page))?.active_region?.name, { timeout: 30_000 }).toContain('四川');

  const finalResponse = [...observer.results.slice(resultStart)].reverse().find(
    (result) => result.publication_state !== 'tool_execution_required',
  );
  expect(finalResponse?.publication_state).toBe('published');
  expect(String(finalResponse?.generated_answer ?? '').trim().length).toBeGreaterThan(0);
};

for (const dimension of ['2d', '3d'] as const) {
  test(`real Agent selects Sichuan and uses scoped catalogue in ${dimension}`, async ({ page }) => {
    await runRegionCatalogueCase(page, dimension);
  });
}
