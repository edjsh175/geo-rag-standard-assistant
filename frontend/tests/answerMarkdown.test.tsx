import { strict as assert } from 'node:assert';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { test } from 'vitest';
import Chat from '../src/components/Chat';

const renderChatAnswer = (content: string, id = 'answer-1') => renderToStaticMarkup(
  <Chat
    messages={[{ id, role: 'assistant', content, timestamp: '2026-01-01T00:00:00Z' }]}
    onSendMessage={async () => {}}
    isLoading={false}
    inputValue=""
    onInputChange={() => {}}
    reviewerEnabled={false}
    onReviewerEnabledChange={() => {}}
    sessions={[]}
  />,
);

test('Chat exposes a disclosure for a long assistant list', () => {
  const content = Array.from({ length: 8 }, (_, index) => `标准 ${index + 1}`).map((item) => `- ${item}`).join('\n');
  const html = renderChatAnswer(content);
  const disclosureIndex = html.indexOf('<details');
  const answerStart = html.indexOf('<div class="answer-markdown');
  const visibleList = html.slice(answerStart, disclosureIndex);

  assert.match(html, /展开剩余 2 项/);
  assert.equal((visibleList.match(/<li>/g) ?? []).length, 6);
  for (let index = 1; index <= 8; index++) assert.match(html, new RegExp(`标准 ${index}`));
  assert.match(html, /<details class="answer-markdown__list-disclosure">/);
});

test('short lists remain visible without a disclosure', () => {
  const html = renderChatAnswer('- 甲\n- 乙\n- 丙');
  assert.doesNotMatch(html, /<details/);
  assert.match(html, /<li>甲<\/li>/);
});

test('a nested list is not folded a second time', () => {
  const nestedItems = Array.from({ length: 8 }, (_, index) => `  - 子项 ${index + 1}`).join('\n');
  const html = renderChatAnswer(`- 父项\n${nestedItems}`);
  assert.doesNotMatch(html, /<details/);
  assert.match(html, /子项 8/);
});

test('ordered list continuation preserves the source numbering', () => {
  const items = Array.from({ length: 8 }, (_, index) => `${index + 1}. 编号项 ${index + 1}`).join('\n');
  const html = renderChatAnswer(`4. 编号项 1\n${items.split('\n').slice(1).join('\n')}`);
  assert.match(html, /<ol start="4">/);
  assert.match(html, /<ol start="10">/);
});

test('headings and paragraphs stay outside the folded list', () => {
  const html = renderChatAnswer(`## 结论\n\n重要限制始终可见。\n\n${Array.from({ length: 8 }, (_, index) => `- 条目 ${index + 1}`).join('\n')}`);
  assert.match(html, /<h2>结论<\/h2>/);
  assert.match(html, /重要限制始终可见。/);
  assert.match(html, /展开剩余 2 项/);
});

test('tables and code blocks have local keyboard-scroll regions', () => {
  const html = renderChatAnswer('| 名称 | 值 |\n| --- | --- |\n| A | B |\n\n```text\nwide\tcode\n```');
  assert.match(html, /aria-label="可横向滚动的数据表格"[^>]*tabindex="0"/);
  assert.match(html, /aria-label="可横向滚动的代码块"[^>]*tabindex="0"/);
  assert.match(html, /<table>/);
  assert.match(html, /wide\tcode/);
});

test('unsafe raw HTML is rendered as text', () => {
  const html = renderChatAnswer('<img src=x onerror=alert(1)>');
  assert.doesNotMatch(html, /<img\b/i);
  assert.match(html, /&lt;img/);
});

test('legacy plain text keeps its original wording', () => {
  const html = renderChatAnswer('这是一条旧的纯文本答案，没有列表分组。');
  assert.match(html, /<p>这是一条旧的纯文本答案，没有列表分组。<\/p>/);
});
