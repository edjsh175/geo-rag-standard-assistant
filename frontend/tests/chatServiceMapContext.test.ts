import { strict as assert } from 'node:assert';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { test } from 'vitest';

import Chat from '../src/components/Chat';
import { registerBrowserGisRuntime, setActiveBrowserGisRuntime } from '../src/gis/browserBridge';
import { chatService, withActiveMapContext } from '../src/services/chatService';
import { resolveFollowUpContext } from '../src/App';

test('shared chat request helper attaches the active map context', () => {
  const unregister = registerBrowserGisRuntime('3d', {
    execute: async () => ({}),
    snapshot: () => ({
      schema_version: 2,
      revision: 4,
      dimension: '3d',
      ready: true,
      supported_tools: ['locate_map'],
      viewport: { center: [104, 30], zoom: 5, crs: 'EPSG:4326' },
      layer_tree: [],
      user_layers: [],
      available_files: [],
    }),
  });

  try {
    setActiveBrowserGisRuntime('3d');
    const request = withActiveMapContext({
      query: '定位成都',
      use_generation: true,
    });
    assert.equal(request.map_context?.dimension, '3d');
    assert.deepEqual(request.map_context?.supported_tools, ['locate_map']);
  } finally {
    unregister();
  }
});

test('selected document follow-up uses the backend 1-based rank contract', () => {
  const context = resolveFollowUpContext(
    '介绍一下这个文档',
    [],
    {
      id: '17930',
      filename: 'DB50_T 1015-2020 土地整治项目规划设计规范.zip',
      file_type: 'zip',
      file_size: 0,
      content_hash: '',
      upload_time: new Date().toISOString(),
      last_modified: new Date().toISOString(),
      metadata: {
        title: 'DB50_T 1015-2020 土地整治项目规划设计规范.zip',
        author: '',
        description: '',
        keywords: [],
        language: 'zh',
        tags: [],
        custom_fields: {},
      },
      is_indexed: true,
      indexing_status: 'completed',
      storage_path: '',
      version: 1,
    },
  );

  assert.equal(context?.candidate_documents?.[0]?.rank, 1);
});

test('chat service forwards the reviewer preference into streaming requests', async () => {
  const original = chatService.sendMessageStream;
  let reviewerEnabled: boolean | undefined;
  chatService.sendMessageStream = (async (...args: unknown[]) => {
    reviewerEnabled = args[7] as boolean | undefined;
    return {
      message: 'ok',
      conversation_id: 'session-1',
      references: [],
      timestamp: new Date().toISOString(),
    };
  }) as typeof chatService.sendMessageStream;

  try {
    await (chatService.sendMessage as any)(
      '问题',
      'session-1',
      [],
      undefined,
      undefined,
      () => {},
      true,
    );
    assert.equal(reviewerEnabled, true);
  } finally {
    chatService.sendMessageStream = original;
  }
});

test('chat exposes a reviewer switch that reflects the current preference', () => {
  const html = renderToStaticMarkup(
    React.createElement(Chat, {
      messages: [],
      onSendMessage: async () => {},
      isLoading: false,
      inputValue: '',
      onInputChange: () => {},
      reviewerEnabled: true,
      onReviewerEnabledChange: () => {},
      sessions: [],
      onRefreshSessions: async () => {},
      onCreateSession: async () => {},
      onSelectSession: async () => {},
      onDeleteSession: async () => {},
    }),
  );

  assert.match(html, /role="switch"/);
  assert.match(html, /aria-checked="true"/);
  assert.match(html, /证据审查 Reviewer/);
  assert.match(html, /仅审查知识答案/);
});
