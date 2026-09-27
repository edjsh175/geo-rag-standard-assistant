import { expect, test, type Page } from '@playwright/test';

const SESSION_ID = 'session-agent-full-process';
const TURN_ID = 'turn-agent-full-process';
const TRACE_ID = 'trace-agent-full-process';

const setupApplication = async (page: Page) => {
  await page.route('**/api/auth/me', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ username: 'alice', role: 'admin' }),
  }));
  await page.route('**/health', (route) => route.fulfill({ status: 200, body: 'ok' }));
  await page.route('**/api/search/query/cancel', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ ok: true }),
  }));
  await page.route('**/data/china-provinces.json', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ type: 'FeatureCollection', features: [] }),
  }));
  await page.route('**/tianditu/**', (route) => route.abort());

  // Mock only the Agent stream. The application, BrowserBridge, and GIS engines stay real.
  await page.addInitScript(() => {
    const nativeFetch = window.fetch.bind(window);
    const state = { streamCalls: 0 };
    Object.defineProperty(window, '__agentStreamMock', { value: state, configurable: false });
    window.fetch = async (input, init) => {
      const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
      if (!url.includes('/api/search/query/stream')) return nativeFetch(input, init);
      const request = JSON.parse(String(init?.body ?? '{}'));
      state.streamCalls += 1;
      const holdForStop = request.query === '请求稍后停止';
      const continuation = Boolean(request.continuation_token);
      const events = continuation
        ? [
            ['browser_tool_completed', {
              tool_call_id: 'call-locate-1', tool_name: 'locate_map', status: 'succeeded',
              receipt: {
                effect_status: request.browser_tool_receipt?.effect?.status,
                map_dimension: request.browser_tool_receipt?.map_context?.dimension,
                state_revision: request.browser_tool_receipt?.effect?.state_revision,
              },
            }],
            ['review_started', { review_id: 'review-1', attempt: 1 }],
            ['answer_generated', { citations: [] }],
            ['review_completed', { review_id: 'review-1', verdict: 'PASS' }],
            ['publication_completed', { state: 'published' }],
            ['result', {
              session_id: 'session-agent-full-process', trace_id: 'trace-agent-full-process',
              generated_answer: '最终答案：地图已定位，审查通过并正式发布。', results: [], publication_state: 'published',
            }],
          ]
        : holdForStop
          ? [
              ['controller_decision', { tool_name: 'retrieve_kb', decision_summary: '正在检索依据' }],
              ['tool_started', { tool_call_id: 'call-held-1', tool_name: 'retrieve_kb', arguments: { query: '规划规范' } }],
            ]
          : [
            ['controller_decision', { tool_name: 'locate_map', decision_summary: '按用户请求定位地图' }],
            ['tool_started', { tool_call_id: 'call-locate-1', tool_name: 'locate_map', arguments: { latitude: 39.9, longitude: 116.4 } }],
            ['browser_tool_requested', { tool_call_id: 'call-locate-1', tool_name: 'locate_map', arguments: { latitude: 39.9, longitude: 116.4 } }],
            ['result', {
              session_id: 'session-agent-full-process', trace_id: 'trace-agent-full-process',
              turn_id: 'turn-agent-full-process', publication_state: 'tool_execution_required',
              pending_tool_call_id: 'call-locate-1', continuation_token: 'continue-agent-full-process',
              map_action: { type: 'locate_map', target: 'active_map', payload: { latitude: 39.9, longitude: 116.4, zoom: 8 } },
            }],
          ];
      const encoder = new TextEncoder();
      let index = 0;
      const body = new ReadableStream({
        async pull(controller) {
          if (index >= events.length) {
            if (holdForStop) {
              await new Promise<void>((resolve) => init?.signal?.addEventListener('abort', () => resolve(), { once: true }));
            }
            controller.close();
            return;
          }
          const [event, payload] = events[index++];
          await new Promise((resolve) => setTimeout(resolve, 180));
          const data = event === 'result' ? payload : {
            session_id: 'session-agent-full-process', turn_id: 'turn-agent-full-process',
            trace_id: 'trace-agent-full-process', event_id: `event-${state.streamCalls}-${index}`,
            sequence: index, payload,
          };
          controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`));
        },
      });
      return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } });
    };
  });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  await expect(page.locator('[data-boot-action]')).toBeVisible({ timeout: 60_000 });
  await page.locator('[data-boot-action]').click();
  await expect(page.getByPlaceholder('输入规划指令或搜索关键词...')).toBeVisible({ timeout: 30_000 });
};

for (const dimension of ['2d', '3d'] as const) {
  test(`streams GIS execution, review, and publication in ${dimension.toUpperCase()}`, async ({ page }) => {
    await setupApplication(page);
    if (dimension === '3d') {
      await page.getByRole('button', { name: /3D 地球/ }).click();
      await expect.poll(() => page.evaluate(() =>
        (window as Window & { __GEOAI_BROWSER_GIS__?: { getContext: () => { dimension?: string; ready?: boolean } } })
          .__GEOAI_BROWSER_GIS__?.getContext()?.dimension,
      ), { timeout: 60_000 }).toBe('3d');
    }

    await page.getByPlaceholder('输入规划指令或搜索关键词...').fill('定位到北京');
    await page.getByPlaceholder('输入规划指令或搜索关键词...').press('Enter');

    const processToggle = page.getByRole('button', { name: /Agent 执行流程/ });
    await expect(processToggle).toBeVisible();
    await expect(page.getByRole('button', { name: /地图视角定位/ })).toBeVisible();
    await expect(page.getByText('最终答案：地图已定位，审查通过并正式发布。')).toHaveCount(0);
    await expect(page.getByText('Grounding 审查')).toBeVisible();
    const runningReview = page.getByRole('button', { name: /Grounding 审查.*running/ });
    await expect(runningReview).toBeVisible();

    await expect(page.getByText('最终答案：地图已定位，审查通过并正式发布。')).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => page.evaluate(() =>
      (window as Window & { __agentStreamMock?: { streamCalls: number } }).__agentStreamMock?.streamCalls,
    )).toBe(2);
    await expect(page.getByText('published', { exact: true })).toBeVisible();

    // A completed turn folds itself; opening it manually must survive later renders.
    await expect(processToggle).toHaveAttribute('aria-expanded', 'false');
    await processToggle.click();
    await expect(processToggle).toHaveAttribute('aria-expanded', 'true');
    const toolRow = page.getByRole('button', { name: /地图视角定位 .* succeeded/ });
    await expect(toolRow).toBeVisible();
    await toolRow.click();
    await expect(page.getByText('BROWSER RECEIPT')).toBeVisible();
    await expect(page.getByText(new RegExp(`Dimension: ${dimension}`))).toBeVisible();
    await expect(page.getByText(/Revision: \d+/)).toBeVisible();
    await expect(page.getByText('PASS', { exact: true })).toBeVisible();
    await expect(page.getByText('最终答案：地图已定位，审查通过并正式发布。')).toBeVisible();
    await expect(processToggle).toHaveAttribute('aria-expanded', 'true');
  });
}

test('stopping a running turn keeps its process visible with a stopped status', async ({ page }) => {
  await setupApplication(page);
  const input = page.getByPlaceholder('输入规划指令或搜索关键词...');
  await input.fill('请求稍后停止');
  await input.press('Enter');
  const processToggle = page.getByRole('button', { name: /Agent 执行流程/ });
  await expect(processToggle).toBeVisible();
  const runningTool = page.getByRole('button', { name: /检索知识库/ });
  await expect(runningTool).toBeVisible();
  await expect(runningTool).toContainText('running');
  await page.getByRole('button', { name: '停止生成' }).click();
  await expect(processToggle).toBeVisible();
  await expect(page.getByText(/已停止接收执行事件/)).toBeVisible();
});
