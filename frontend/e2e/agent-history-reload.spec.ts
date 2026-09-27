import { expect, test, type Request } from '@playwright/test';

const SESSION_ID = 'session-history-reload';
const TURN_ID = 'turn-published-history';
const TRACE_ID = 'trace-history-reload';

const historyEvents = [
  {
    event_type: 'controller_decision',
    event_id: 'event-decision',
    sequence: 1,
    payload: { tool_name: 'retrieve_kb', decision_summary: '从知识库检索相关规范' },
  },
  {
    event_type: 'tool_started',
    event_id: 'event-retrieve-start',
    sequence: 2,
    payload: { tool_call_id: 'call-retrieve', tool_name: 'retrieve_kb', arguments: { query: '历史过程回归' } },
  },
  {
    event_type: 'tool_completed',
    event_id: 'event-retrieve-complete',
    sequence: 3,
    payload: { tool_call_id: 'call-retrieve', tool_name: 'retrieve_kb', status: 'succeeded', result_summary: { count: 1 } },
  },
  {
    event_type: 'tool_started',
    event_id: 'event-browser-start',
    sequence: 4,
    payload: { tool_call_id: 'call-browser', tool_name: 'locate_map', arguments: { region: '北京市' } },
  },
  {
    event_type: 'browser_tool_requested',
    event_id: 'event-browser-requested',
    sequence: 5,
    payload: { tool_call_id: 'call-browser', tool_name: 'locate_map', arguments: { region: '北京市' } },
  },
  {
    event_type: 'browser_tool_completed',
    event_id: 'event-browser-completed',
    sequence: 6,
    payload: {
      tool_call_id: 'call-browser',
      tool_name: 'locate_map',
      status: 'succeeded',
      receipt: { map_dimension: '2d', state_revision: 7 },
    },
  },
  {
    event_type: 'tool_started',
    event_id: 'event-failed-start',
    sequence: 7,
    payload: { tool_call_id: 'call-failed', tool_name: 'inspect_layer_features' },
  },
  {
    event_type: 'tool_completed',
    event_id: 'event-failed-complete',
    sequence: 8,
    payload: {
      tool_call_id: 'call-failed',
      tool_name: 'inspect_layer_features',
      status: 'failed',
      error: '历史工具执行失败（fixture）',
    },
  },
  {
    event_type: 'evidence_frozen',
    event_id: 'event-evidence',
    sequence: 9,
    payload: { snapshot_id: 'snapshot-history', evidence_ids: ['doc-history-1'] },
  },
  {
    event_type: 'answer_generated',
    event_id: 'event-answer-generated',
    sequence: 10,
    payload: { citations: [{ document_id: 'doc-history-1' }] },
  },
  {
    event_type: 'review_completed',
    event_id: 'event-review',
    sequence: 11,
    payload: { verdict: 'PASS' },
  },
  {
    event_type: 'publication_completed',
    event_id: 'event-publication',
    sequence: 12,
    payload: { state: 'published' },
  },
].map((event) => ({
  ...event,
  session_id: SESSION_ID,
  turn_id: TURN_ID,
  trace_id: TRACE_ID,
  created_at: '2026-09-27T01:00:00Z',
}));

test('reload restores the published Agent process and never replays GIS actions', async ({ page }) => {
  const apiWrites: string[] = [];
  let turnTraceReads = 0;
  page.on('request', (request: Request) => {
    const url = new URL(request.url());
    if (request.method() === 'POST' && url.pathname.startsWith('/api/')) apiWrites.push(url.pathname);
    if (request.method() === 'GET' && url.pathname === `/api/agent/sessions/${SESSION_ID}/turns/${TURN_ID}`) {
      turnTraceReads += 1;
    }
  });

  await page.route('**/api/auth/me', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ username: 'alice', role: 'admin' }),
  }));
  await page.route('**/health', (route) => route.fulfill({ status: 200, body: 'ok' }));
  await page.route('**/data/china-provinces.json', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ type: 'FeatureCollection', features: [] }),
  }));
  await page.route('**/api/agent/sessions/session-history-reload', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      session_id: SESSION_ID,
      messages: [
        { id: 'message-user', role: 'user', content: '请恢复历史 Agent 执行过程', turn_id: TURN_ID, timestamp: '2026-09-27T01:00:00Z' },
        {
          id: 'message-assistant',
          role: 'assistant',
          content: '历史恢复答案：已根据规范完成分析。',
          turn_id: TURN_ID,
          timestamp: '2026-09-27T01:00:01Z',
          references: [{ id: 'doc-history-1', title: '历史规划规范', content: '规范中的相关依据。', similarity: 0.91 }],
        },
      ],
      turns: [{ turn_id: TURN_ID, trace_id: TRACE_ID, events: [] }],
    }),
  }));
  await page.route('**/api/agent/sessions/session-history-reload/turns/turn-published-history', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ session_id: SESSION_ID, turn_id: TURN_ID, trace_id: TRACE_ID, ordered_events: historyEvents }),
  }));
  // The map runtime initializes locally, while external base map tiles are unnecessary here.
  await page.route('**/tianditu/**', (route) => route.abort());

  await page.addInitScript(({ sessionId }) => {
    localStorage.setItem('geoai.agent.session.v1:admin:alice', sessionId);
  }, { sessionId: SESSION_ID });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');

  const enterButton = page.locator('[data-boot-action]');
  await expect(enterButton).toBeVisible({ timeout: 60_000 });
  await enterButton.click();
  await expect(page.getByPlaceholder('输入规划指令或搜索关键词...')).toBeVisible({ timeout: 20_000 });

  const restoredAnswer = page.getByText('历史恢复答案：已根据规范完成分析。');
  await expect(restoredAnswer).toBeVisible();
  await expect(page.getByText('doc-history-1', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: /Agent 执行流程/ }).click();
  await expect(page.getByText('published', { exact: true })).toBeVisible();
  await expect(page.getByText('历史规划规范')).toBeVisible();
  const failedTool = page.getByRole('button', { name: /要素属性探查.*failed/ });
  await expect(failedTool).toBeVisible();
  await failedTool.click();
  await expect(page.getByText('历史工具执行失败（fixture）', { exact: true })).toBeVisible();

  const browserTool = page.getByRole('button', { name: /地图视角定位/ });
  await expect(browserTool).toContainText('succeeded');
  await browserTool.click();
  await expect(page.getByText('BROWSER RECEIPT', { exact: true })).toBeVisible();
  await expect(page.getByText(/Status: succeeded.*Dimension: 2d.*Revision: 7/)).toBeVisible();

  // The browser-history read is a GET; no search, continuation, or GIS mutation may run during restore.
  expect(apiWrites).toEqual([]);
  expect(turnTraceReads).toBe(1);

  await page.reload();
  await expect(page.locator('[data-boot-action]')).toBeVisible({ timeout: 60_000 });
  await page.locator('[data-boot-action]').click();
  await expect(page.getByPlaceholder('输入规划指令或搜索关键词...')).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText('历史恢复答案：已根据规范完成分析。')).toBeVisible();
  await expect(page.getByRole('button', { name: /Agent 执行流程/ })).toBeVisible();
  await page.getByRole('button', { name: /Agent 执行流程/ }).click();
  await expect(page.getByText('published', { exact: true })).toBeVisible();
  await expect(page.getByText('doc-history-1', { exact: true })).toBeVisible();
  const reloadedFailedTool = page.getByRole('button', { name: /要素属性探查.*failed/ });
  await expect(reloadedFailedTool).toBeVisible();
  await reloadedFailedTool.click();
  await expect(page.getByText('历史工具执行失败（fixture）', { exact: true })).toBeVisible();
  expect(apiWrites).toEqual([]);
  expect(turnTraceReads).toBe(2);
});
