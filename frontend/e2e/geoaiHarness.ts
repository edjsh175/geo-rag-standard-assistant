import fs from 'node:fs';
import path from 'node:path';
import type { Page, Request, Response } from '@playwright/test';

export type ManifestAssertion = {
  type: string;
  tool?: string;
  state?: string;
};

export type EvalTask = {
  id: string;
  category: string;
  scenario: string;
  depends_on: string[];
  prompt: string;
  fixture?: string;
  assertions: ManifestAssertion[];
};

export type SearchExchange = {
  request: Record<string, any>;
  response: Record<string, any>;
};

export type AssertionEvidence = ManifestAssertion & {
  required: true;
  passed: boolean;
  evidence?: unknown;
};

export type ExecutedTaskResult = {
  id: string;
  completed: boolean;
  scenario: string;
  session_id?: string;
  trace_ids: string[];
  started_at: string;
  duration_ms: number;
  assertions: AssertionEvidence[];
  tool_calls: Array<{ tool: string; trace_id?: string; tool_call_id?: string }>;
  receipts: Array<Record<string, any>>;
  final_answer?: string;
  failure_reason?: string | null;
  artifacts?: Record<string, string>;
};

const SEARCH_PATH = '/api/search/query';

export class SearchObserver {
  readonly exchanges: SearchExchange[] = [];

  constructor(page: Page) {
    page.on('response', async (response: Response) => {
      const request = response.request();
      if (request.method() !== 'POST' || !new URL(response.url()).pathname.startsWith(SEARCH_PATH)) return;
      try {
        const requestBody = (request.postDataJSON() ?? {}) as Record<string, any>;
        const responseBody = await response.json() as Record<string, any>;
        this.exchanges.push({ request: requestBody, response: responseBody });
      } catch {
        // A malformed or non-JSON response is observable as task timeout/failure.
      }
    });
  }
}

export const loadManifest = (root: string): EvalTask[] =>
  JSON.parse(fs.readFileSync(path.join(root, 'evals', 'geoai_agent_36_tasks.json'), 'utf-8')) as EvalTask[];

export const orderScenarioTasks = (tasks: EvalTask[]): EvalTask[] => {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const ordered: EvalTask[] = [];
  const visiting = new Set<string>();
  const visited = new Set<string>();

  const visit = (task: EvalTask) => {
    if (visited.has(task.id)) return;
    if (visiting.has(task.id)) throw new Error(`dependency cycle at ${task.id}`);
    visiting.add(task.id);
    for (const depId of task.depends_on) {
      const dep = byId.get(depId);
      if (dep) visit(dep);
    }
    visiting.delete(task.id);
    visited.add(task.id);
    ordered.push(task);
  };

  for (const task of tasks) visit(task);
  return ordered;
};

const toolCallsFrom = (exchanges: SearchExchange[]) => exchanges
  .filter(({ response }) => response.publication_state === 'tool_execution_required' && response.map_action?.type)
  .map(({ response }) => ({
    tool: String(response.map_action.type),
    trace_id: response.trace_id ? String(response.trace_id) : undefined,
    tool_call_id: response.pending_tool_call_id ? String(response.pending_tool_call_id) : undefined,
  }));

const receiptsFrom = (exchanges: SearchExchange[]) => exchanges
  .map(({ request }) => request.browser_tool_receipt)
  .filter((receipt): receipt is Record<string, any> => Boolean(receipt && typeof receipt === 'object'));

const contextsFrom = (exchanges: SearchExchange[]) => exchanges
  .flatMap(({ request }) => [request.map_context, request.browser_tool_receipt?.map_context])
  .filter((context): context is Record<string, any> => Boolean(context && typeof context === 'object'));

export const evaluateAssertions = (
  task: EvalTask,
  exchanges: SearchExchange[],
  scenarioExchanges: SearchExchange[],
): AssertionEvidence[] => {
  const toolCalls = toolCallsFrom(exchanges);
  const receipts = receiptsFrom(exchanges);
  const contexts = contextsFrom([...scenarioExchanges, ...exchanges]);
  const finalResponse = exchanges.at(-1)?.response ?? {};

  const layerRefs = contexts.flatMap((ctx) => Array.isArray(ctx.user_layers)
    ? ctx.user_layers.map((layer: Record<string, any>) => layer.layer_ref).filter(Boolean)
    : []);
  const featureRefs = contexts.flatMap((ctx) => Array.isArray(ctx.user_layers)
    ? ctx.user_layers.flatMap((layer: Record<string, any>) => Array.isArray(layer.feature_refs) ? layer.feature_refs : [])
    : []);

  return task.assertions.map((assertion) => {
    let passed = false;
    let evidence: unknown;
    switch (assertion.type) {
      case 'published_answer_present':
        passed = typeof finalResponse.generated_answer === 'string' && finalResponse.generated_answer.trim().length > 0;
        evidence = finalResponse.generated_answer;
        break;
      case 'publication_state':
        passed = finalResponse.publication_state === assertion.state;
        evidence = finalResponse.publication_state;
        break;
      case 'tool_called':
        passed = toolCalls.some((call) => call.tool === assertion.tool);
        evidence = toolCalls;
        break;
      case 'tool_receipt_success':
        passed = receipts.some((receipt) => receipt.tool_name === assertion.tool && receipt.status === 'succeeded');
        evidence = receipts;
        break;
      case 'tool_receipt_failure':
        passed = receipts.some((receipt) => receipt.status === 'failed');
        evidence = receipts;
        break;
      case 'map_context_present':
        passed = contexts.some((context) => context.ready === true && Array.isArray(context.layer_tree));
        evidence = contexts.at(-1);
        break;
      case 'stable_layer_ref':
        passed = new Set(layerRefs).size > 0 && layerRefs.length > new Set(layerRefs).size;
        evidence = layerRefs;
        break;
      case 'stable_feature_ref':
        passed = new Set(featureRefs).size > 0 && featureRefs.length > new Set(featureRefs).size;
        evidence = featureRefs;
        break;
      case 'response_has_citations':
        passed = Array.isArray(finalResponse.results) && finalResponse.results.length > 0;
        evidence = finalResponse.results?.map((item: Record<string, any>) => item.id ?? item.document_id ?? item.title);
        break;
      case 'response_contains_limit':
        passed = finalResponse.publication_state === 'limitation';
        evidence = finalResponse.publication_state;
        break;
      case 'no_false_success_after_failure': {
        const failedReceipt = receipts.some((receipt) => receipt.status === 'failed');
        const finalText = String(finalResponse.generated_answer ?? '');
        passed = failedReceipt && !/成功|已完成|已执行成功/.test(finalText);
        evidence = { failedReceipt, finalText };
        break;
      }
      default:
        passed = false;
        evidence = { unsupported_assertion: assertion.type };
    }
    return { ...assertion, required: true as const, passed, evidence };
  });
};

const waitForFinalExchange = async (observer: SearchObserver, start: number, timeoutMs = 90_000) => {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const current = observer.exchanges.slice(start);
    if (current.length > 0 && current.at(-1)?.response.publication_state !== 'tool_execution_required') return current;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error('agent request timed out before final publication state');
};

export const executeTask = async (
  page: Page,
  observer: SearchObserver,
  task: EvalTask,
  repoRoot: string,
  scenarioExchanges: SearchExchange[],
): Promise<ExecutedTaskResult> => {
  const started = Date.now();
  const startCount = observer.exchanges.length;
  if (task.fixture) {
    const fixturePath = path.join(repoRoot, 'evals', 'fixtures', task.fixture);
    const input = page.locator('input[type="file"]');
    if (fs.statSync(fixturePath).isDirectory()) {
      const files = fs.readdirSync(fixturePath).map((name) => path.join(fixturePath, name));
      await input.setInputFiles(files);
    } else {
      await input.setInputFiles(fixturePath);
    }
  }

  const promptInput = page.getByPlaceholder('输入规划指令或搜索关键词...');
  await promptInput.fill(task.prompt);
  await promptInput.press('Enter');

  const exchanges = await waitForFinalExchange(observer, startCount);
  const assertions = evaluateAssertions(task, exchanges, scenarioExchanges);
  const completed = assertions.every((assertion) => assertion.passed);
  const finalResponse = exchanges.at(-1)?.response ?? {};
  const toolCalls = toolCallsFrom(exchanges);
  const receipts = receiptsFrom(exchanges);

  return {
    id: task.id,
    completed,
    scenario: task.scenario,
    session_id: finalResponse.session_id,
    trace_ids: [...new Set(exchanges.map(({ response }) => response.trace_id).filter(Boolean).map(String))],
    started_at: new Date(started).toISOString(),
    duration_ms: Date.now() - started,
    assertions,
    tool_calls: toolCalls,
    receipts,
    final_answer: finalResponse.generated_answer,
    failure_reason: completed ? null : assertions.filter((item) => !item.passed).map((item) => item.type).join(','),
  };
};

export const dependencyFailureResult = (task: EvalTask, failedDependency: string): ExecutedTaskResult => ({
  id: task.id,
  completed: false,
  scenario: task.scenario,
  trace_ids: [],
  started_at: new Date().toISOString(),
  duration_ms: 0,
  assertions: task.assertions.map((assertion) => ({ ...assertion, required: true, passed: false, evidence: { dependency_failed: failedDependency } })),
  tool_calls: [],
  receipts: [],
  failure_reason: `dependency_failed:${failedDependency}`,
});
