import type { BrowserMapAction, BrowserMapContext, BrowserToolReceipt } from './contracts';

interface BrowserRuntime {
  execute(runId: string, toolCallId: string, action: BrowserMapAction): Promise<Record<string, unknown>>;
  snapshot(): BrowserMapContext;
}

let runtime: BrowserRuntime | null = null;

export const registerBrowserGisRuntime = (next: BrowserRuntime) => {
  runtime = next;
  return () => { if (runtime === next) runtime = null; };
};

export const getBrowserMapContext = () => runtime?.snapshot() ?? null;

export const executeBrowserTool = async (
  runId: string,
  toolCallId: string,
  action: BrowserMapAction,
): Promise<BrowserToolReceipt> => {
  if (!runtime) throw new Error('WebGIS runtime is not ready');
  try {
    const output = await runtime.execute(runId, toolCallId, action);
    const mapContext = runtime.snapshot();
    return {
      tool_call_id: toolCallId,
      tool_name: action.type,
      status: 'succeeded',
      output,
      effect: { status: 'applied', kind: action.type, state_revision: mapContext.revision },
      map_context: mapContext,
    };
  } catch (error) {
    return {
      tool_call_id: toolCallId,
      tool_name: action.type,
      status: 'failed',
      error: error instanceof Error ? error.message : String(error),
      effect: { status: 'unknown', kind: action.type },
      map_context: runtime.snapshot(),
    };
  }
};
