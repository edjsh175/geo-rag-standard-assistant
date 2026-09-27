import { expect, test, type Page, type Request, type Response } from '@playwright/test';

type SseEvent = {
  event_type: string;
  session_id?: string;
  turn_id?: string;
  trace_id?: string;
  payload: Record<string, unknown>;
};

class RealAgentObserver {
  readonly events: SseEvent[] = [];
  readonly results: Array<Record<string, unknown>> = [];
  readonly streamRequests: Array<{ path: string; body: Record<string, unknown> }> = [];
  readonly traceReads: string[] = [];

  constructor(page: Page) {
    page.on('request', (request: Request) => {
      const url = new URL(request.url());
      if (request.method() === 'POST' && url.pathname === '/api/search/query/stream') {
        try { this.streamRequests.push({ path: url.pathname, body: request.postDataJSON() as Record<string, unknown> }); }
        catch { this.streamRequests.push({ path: url.pathname, body: {} }); }
      }
      if (request.method() === 'GET' && /\/api\/agent\/sessions\/[^/]+\/turns\/[^/]+$/.test(url.pathname)) {
        this.traceReads.push(url.pathname);
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
            if (eventType === 'result') this.results.push(parsed);
            else this.events.push({ event_type: eventType, ...parsed as Omit<SseEvent, 'event_type'> });
          }
          catch { /* The raw stream assertion below will report missing events. */ }
        }
      }).catch(() => undefined);
    });
  }

  async waitForTurn(turnStartIndex: number, resultStartIndex: number, timeoutMs = 180_000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const turnEvents = this.events.slice(turnStartIndex);
      const publication = [...turnEvents].reverse().find((event) => event.event_type === 'publication_completed');
      const finalResult = this.results.slice(resultStartIndex).some((result) => result.publication_state !== 'tool_execution_required');
      if (publication && finalResult) return turnEvents;
      await new Promise((resolve) => setTimeout(resolve, 200));
    }
    throw new Error('Timed out waiting for real Agent SSE publication events.');
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

const submitPrompt = async (page: Page, prompt: string) => {
  const input = page.getByPlaceholder('输入规划指令或搜索关键词...');
  await input.fill(prompt);
  await input.press('Enter');
};

const switchDimension = async (page: Page, dimension: '2d' | '3d') => {
  const context = () => page.evaluate(() => {
    const bridge = (window as Window & { __GEOAI_BROWSER_GIS__?: { getContext?: () => { dimension?: string; ready?: boolean } } }).__GEOAI_BROWSER_GIS__;
    return bridge?.getContext?.() ?? null;
  });
  if (dimension === '3d') await page.getByRole('button', { name: /3D 地球/ }).click();
  else await page.getByRole('button', { name: /2D 地图/ }).click();
  await expect.poll(async () => (await context())?.dimension, { timeout: 90_000 }).toBe(dimension);
  await expect.poll(async () => (await context())?.ready, { timeout: 90_000 }).toBe(true);
};

test('real backend Agent events match the published process and survive reload without GIS replay', async ({ page }) => {
  test.setTimeout(900_000);
  const observer = new RealAgentObserver(page);
  await enterRealApplication(page);
  await switchDimension(page, '2d');

  const turns: Array<{ prompt: string; answer: string; sessionId: string; turnId: string; dimension?: string }> = [];

  const kbEventStart = observer.events.length;
  const kbResultStart = observer.results.length;
  const kbStreamStart = observer.streamRequests.length;
  await submitPrompt(page, '查询滑坡监测相关标准并给出引用。');
  await expect.poll(() => observer.streamRequests.length, { timeout: 60_000 }).toBeGreaterThan(kbStreamStart);
  await expect.poll(() => observer.events.slice(kbEventStart).some((event) => event.event_type === 'publication_completed'), { timeout: 180_000 }).toBe(true);
  await page.getByRole('button', { name: /Agent 执行流程/ }).last().click();
  const kbEvents = await observer.waitForTurn(kbEventStart, kbResultStart);
  const kbPublication = [...kbEvents].reverse().find((event) => event.event_type === 'publication_completed');
  const kbReview = [...kbEvents].reverse().find((event) => event.event_type === 'review_completed');
  expect(kbReview, 'KB answer must have a persisted completed grounding review').toBeTruthy();
  expect(kbPublication?.payload.state ?? kbPublication?.payload.publication_state).toBe('published');
  await expect(page.getByText('Grounding 审查')).toBeVisible();
  await expect(page.getByText(String(kbReview?.payload.verdict ?? ''), { exact: true })).toBeVisible();
  await expect(page.getByText('published', { exact: true })).toBeVisible();
  const kbFinalResponse = [...observer.results.slice(kbResultStart)].reverse().find((result) => result.publication_state !== 'tool_execution_required');
  const kbAnswer = String(kbFinalResponse?.generated_answer ?? '').trim();
  expect(kbAnswer.length, 'final backend result must carry the published answer').toBeGreaterThan(0);
  await expect(page.getByText(kbAnswer, { exact: false })).toBeVisible();
  const kbIdentity = observer.events.slice(kbEventStart).find((event) => event.event_type === 'publication_completed');
  expect(kbIdentity?.session_id).toBeTruthy();
  expect(kbIdentity?.turn_id).toBeTruthy();
  turns.push({ prompt: '查询滑坡监测相关标准并给出引用。', answer: kbAnswer, sessionId: kbIdentity!.session_id!, turnId: kbIdentity!.turn_id! });

  for (const dimension of ['2d', '3d'] as const) {
    await switchDimension(page, dimension);
    const eventStart = observer.events.length;
    const resultStart = observer.results.length;
    const streamStart = observer.streamRequests.length;
    const prompt = '定位到成都坐标并设置缩放级别。';
    await submitPrompt(page, prompt);
    await expect.poll(() => observer.streamRequests.length, { timeout: 60_000 }).toBeGreaterThan(streamStart);
    await expect.poll(() => observer.events.slice(eventStart).some((event) => event.event_type === 'publication_completed'), { timeout: 180_000 }).toBe(true);
    const events = await observer.waitForTurn(eventStart, resultStart);
    const started = events.filter((event) => event.event_type === 'browser_tool_requested' && event.payload.tool_name === 'locate_map');
    const completed = events.filter((event) => event.event_type === 'browser_tool_completed' && event.payload.tool_name === 'locate_map');
    const review = [...events].reverse().find((event) => event.event_type === 'review_completed');
    const publication = [...events].reverse().find((event) => event.event_type === 'publication_completed');
    expect(started, `${dimension} must request a locate_map tool`).toHaveLength(1);
    expect(completed, `${dimension} must persist exactly one browser receipt`).toHaveLength(1);
    const receipt = completed[0].payload.receipt as Record<string, unknown>;
    expect(receipt.map_dimension).toBe(dimension);
    expect(typeof receipt.state_revision).toBe('number');
    expect(review).toBeTruthy();
    expect(publication?.payload.state ?? publication?.payload.publication_state).toBe('published');
    const processToggle = page.getByRole('button', { name: /Agent 执行流程/ }).last();
    if (await processToggle.getAttribute('aria-expanded') === 'false') await processToggle.click();
    await expect(page.getByText('Grounding 审查')).toBeVisible();
    await expect(page.getByText('published', { exact: true })).toBeVisible();
    await expect(page.getByText(new RegExp(`Dimension: ${dimension}`))).toBeVisible();
    const turnIdentity = completed[0];
    expect(turnIdentity.session_id).toBeTruthy();
    expect(turnIdentity.turn_id).toBeTruthy();
    const finalResponse = [...observer.results.slice(resultStart)].reverse().find((result) => result.publication_state !== 'tool_execution_required');
    const answer = String(finalResponse?.generated_answer ?? '').trim();
    expect(answer.length, `${dimension} final backend answer`).toBeGreaterThan(0);
    await expect(page.getByText(answer, { exact: false })).toBeVisible();
    turns.push({ prompt, answer, sessionId: turnIdentity.session_id!, turnId: turnIdentity.turn_id!, dimension });
  }

  const streamsBeforeReload = observer.streamRequests.length;
  const eventsBeforeReload = observer.events.length;
  const traceReadsBeforeReload = observer.traceReads.length;
  await page.reload();
  const bootButton = page.locator('button[data-boot-action]');
  if (await bootButton.isVisible().catch(() => false)) await bootButton.click();
  await expect(page.getByPlaceholder('输入规划指令或搜索关键词...')).toBeVisible({ timeout: 90_000 });
  for (const turn of turns) {
    await expect(page.getByText(turn.prompt, { exact: true })).toBeVisible({ timeout: 60_000 });
    if (turn.dimension === undefined) {
      await expect(page.getByText(/滑坡监测/).last()).toBeVisible();
    } else {
      await expect(page.getByRole('button', { name: /Agent 执行流程/ })).toHaveCount(3);
    }
  }
  await expect.poll(() => observer.streamRequests.length).toBe(streamsBeforeReload);
  await expect.poll(() => observer.events.length).toBe(eventsBeforeReload);
  await expect.poll(() => observer.traceReads.length, { timeout: 60_000 }).toBeGreaterThan(traceReadsBeforeReload);

  const restoredProcesses = page.getByRole('button', { name: /Agent 执行流程/ });
  await expect(restoredProcesses).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    const process = restoredProcesses.nth(index);
    if (await process.getAttribute('aria-expanded') === 'false') await process.click();
  }
  await expect(page.getByText('Grounding 审查')).toHaveCount(3);
  await expect(page.getByText('published', { exact: true })).toHaveCount(3);
  await expect(page.getByText(/Dimension: 2d/)).toBeVisible();
  await expect(page.getByText(/Dimension: 3d/)).toBeVisible();
});
