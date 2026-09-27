import { expect, test } from '@playwright/test';

type SessionSummary = {
  session_id: string;
  title: string;
  status: string;
  turn_count: number;
  updated_at?: string;
};

test('history button manages multiple durable sessions', async ({ page }) => {
  let sessions: SessionSummary[] = [
    { session_id: 'session-one', title: '土地整治', status: 'active', turn_count: 2, updated_at: '2026-09-27T08:00:00Z' },
    { session_id: 'session-two', title: '地图定位', status: 'active', turn_count: 1, updated_at: '2026-09-27T07:00:00Z' },
  ];
  let createCount = 0;
  let deleteCount = 0;

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
  await page.route('**/tianditu/**', (route) => route.abort());

  await page.route('**/api/agent/sessions', async (route) => {
    const request = route.request();
    if (request.method() === 'POST') {
      createCount += 1;
      const created: SessionSummary = {
        session_id: 'session-three',
        title: '新建对话',
        status: 'active',
        turn_count: 0,
        updated_at: '2026-09-27T09:00:00Z',
      };
      sessions = [created, ...sessions.filter((item) => item.session_id !== created.session_id)];
      await route.fulfill({ status: 201, contentType: 'application/json', body: JSON.stringify(created) });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(sessions) });
  });

  const detail = (sessionId: string, content: string) => ({
    session_id: sessionId,
    messages: [{
      id: `answer-${sessionId}`,
      role: 'assistant',
      content,
      timestamp: '2026-09-27T08:00:00Z',
    }],
    turns: [],
  });
  await page.route('**/api/agent/sessions/session-one', async (route) => {
    if (route.request().method() === 'DELETE') {
      deleteCount += 1;
      sessions = sessions.filter((item) => item.session_id !== 'session-one');
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ session_id: 'session-one', deleted: true }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(detail('session-one', '会话一答案')) });
  });
  await page.route('**/api/agent/sessions/session-two', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(detail('session-two', '会话二答案')),
  }));
  await page.route('**/api/agent/sessions/session-three', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ session_id: 'session-three', messages: [], turns: [] }),
  }));

  await page.addInitScript(() => {
    localStorage.setItem('geoai.agent.session.v1:admin:alice', 'session-one');
  });
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');

  const enterButton = page.locator('[data-boot-action]');
  await expect(enterButton).toBeVisible({ timeout: 60_000 });
  await enterButton.click();
  await expect(page.getByText('会话一答案', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: '管理会话' }).click();
  await expect(page.getByRole('dialog', { name: '会话管理' })).toBeVisible();
  await expect(page.getByText('土地整治', { exact: true })).toBeVisible();
  await expect(page.getByText('地图定位', { exact: true })).toBeVisible();

  await page.getByText('地图定位', { exact: true }).click();
  await expect(page.getByText('会话二答案', { exact: true })).toBeVisible();

  await page.getByRole('button', { name: '新建' }).click();
  await expect(page.getByText('新建对话', { exact: true })).toBeVisible();
  expect(createCount).toBe(1);

  await page.getByRole('button', { name: '删除会话 土地整治' }).click();
  await expect(page.getByText('土地整治', { exact: true })).toHaveCount(0);
  expect(deleteCount).toBe(1);
});
