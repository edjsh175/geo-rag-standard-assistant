import type { BrowserMapAction, BrowserMapContext, BrowserToolReceipt } from './contracts';

interface BrowserRuntime {
  execute(runId: string, toolCallId: string, action: BrowserMapAction): Promise<Record<string, unknown>>;
  snapshot(): BrowserMapContext;
}

type BrowserRuntimeKind = '2d' | '3d';

const runtimes = new Map<BrowserRuntimeKind, BrowserRuntime>();
let activeRuntimeKind: BrowserRuntimeKind | null = null;

export const registerBrowserGisRuntime = (kind: BrowserRuntimeKind, next: BrowserRuntime) => {
  runtimes.set(kind, next);
  return () => {
    if (runtimes.get(kind) === next) runtimes.delete(kind);
  };
};

export const setActiveBrowserGisRuntime = (kind: BrowserRuntimeKind) => {
  activeRuntimeKind = kind;
};

const getActiveRuntime = () => activeRuntimeKind ? runtimes.get(activeRuntimeKind) ?? null : null;

export const getBrowserMapContext = () => getActiveRuntime()?.snapshot() ?? null;

export const executeBrowserTool = async (
  runId: string,
  toolCallId: string,
  action: BrowserMapAction,
): Promise<BrowserToolReceipt> => {
  const runtime = getActiveRuntime();
  if (!runtime) throw new Error('WebGIS runtime is not ready');
  const before = runtime.snapshot();
  if (!before.ready) {
    return {
      tool_call_id: toolCallId,
      tool_name: action.type,
      status: 'failed',
      error: 'Active GIS runtime is not ready',
      effect: { status: 'none', kind: action.type },
      map_context: before,
    };
  }
  if (!before.supported_tools.includes(action.type)) {
    return {
      tool_call_id: toolCallId,
      tool_name: action.type,
      status: 'failed',
      error: `GIS tool is not supported by the active map runtime: ${action.type}`,
      effect: { status: 'none', kind: action.type },
      map_context: before,
    };
  }
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
