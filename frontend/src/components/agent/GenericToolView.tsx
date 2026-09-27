import React from 'react';
import { AgentToolItem } from './types';

const LIMIT = 1600;
const boundedValue = (value: unknown, depth = 0): unknown => {
  if (typeof value === 'string') return value.length > 240 ? `${value.slice(0, 240)}…` : value;
  if (value === null || typeof value !== 'object') return value;
  if (depth >= 4) return '[嵌套内容已省略]';
  if (Array.isArray(value)) return [...value.slice(0, 12).map((entry) => boundedValue(entry, depth + 1)), ...(value.length > 12 ? ['…'] : [])];
  const entries = Object.entries(value as Record<string, unknown>);
  return Object.fromEntries([...entries.slice(0, 20).map(([key, entry]) => [key, boundedValue(entry, depth + 1)]), ...(entries.length > 20 ? [['…', '字段已省略']] : [])]);
};
const safePreview = (value: unknown): string => {
  if (typeof value === 'string') return value.length > 80 ? `${value.slice(0, 80)}…` : value;
  if (value && typeof value === 'object') return Array.isArray(value) ? `[${value.length} 项]` : `{${Object.keys(value).slice(0, 6).join(', ')}}`;
  return String(value);
};
const renderJson = (value: unknown): string => {
  let text: string;
  try { text = JSON.stringify(boundedValue(value), null, 2); } catch { text = String(value).slice(0, LIMIT); }
  return text.length > LIMIT ? `${text.slice(0, LIMIT)}…（已截断）` : text;
};

const views: Record<string, { title: string; input: string[]; output: string[] }> = {
  retrieve_kb: { title: '检索知识库', input: ['query'], output: ['evidence_ids', 'candidate_count', 'admitted_count'] },
  import_vector_dataset: { title: '导入矢量数据集', input: ['file_ref', 'name'], output: ['layer_ids', 'layer_count', 'feature_count'] },
  set_layer_visibility: { title: '图层显隐控制', input: ['layer_ref', 'visible'], output: [] },
  set_vector_style: { title: '更新矢量样式', input: ['layer_ref', 'style'], output: [] },
  fit_vector_layer: { title: '缩放至图层范围', input: ['layer_ref'], output: [] },
  locate_map: { title: '地图视角定位', input: ['longitude', 'latitude', 'zoom'], output: [] },
  inspect_layer_features: { title: '要素属性探查', input: ['layer_ref', 'offset', 'limit'], output: ['feature_ids', 'feature_count'] },
  get_feature_geometry: { title: '提取要素空间几何', input: ['feature_ref'], output: ['feature_count'] },
  query_spatial_relation: { title: 'PostGIS 空间关系查询', input: ['left', 'right', 'relation'], output: ['result_ids', 'result_count', 'evidence_ids'] },
  spatial_overlay: { title: 'PostGIS 空间拓扑叠加', input: ['left', 'right', 'operation'], output: ['result_ids', 'result_count', 'evidence_ids'] },
};

const fields = (value: Record<string, unknown> | undefined, names: string[]) => names
  .filter((name) => value && value[name] !== undefined)
  .map((name) => `${name}: ${safePreview(value?.[name])}`);

export interface GenericToolViewProps { tool: AgentToolItem }

export const GenericToolView: React.FC<GenericToolViewProps> = ({ tool }) => {
  const config = views[tool.toolName];
  const inputFacts = fields(tool.arguments, config?.input || []);
  const outputFacts = fields(tool.output, config?.output || []);
  return <div className="space-y-2" data-tool-renderer={config ? tool.toolName : 'generic'}>
    <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider">Call ID <span className="normal-case font-mono text-slate-300">{tool.callId}</span></div>
    {config && inputFacts.length > 0 && <div className="flex flex-wrap gap-1">{inputFacts.map((fact) => <span key={fact} className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] text-slate-300">{fact}</span>)}</div>}
    <section><div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">INPUT</div>
      {tool.arguments && Object.keys(tool.arguments).length ? <pre className="max-h-40 overflow-auto rounded bg-black/40 p-1.5 text-[10px] text-slate-300">{renderJson(tool.arguments)}</pre> : <span className="text-[10px] text-slate-500">无输入字段</span>}
    </section>
    <section><div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-slate-500">OUTPUT</div>
      {tool.output && Object.keys(tool.output).length ? <><div className="mb-1 flex flex-wrap gap-1">{outputFacts.map((fact) => <span key={fact} className="rounded bg-emerald-950/40 px-1.5 py-0.5 text-[10px] text-emerald-200">{fact}</span>)}</div><pre className="max-h-40 overflow-auto rounded bg-black/40 p-1.5 text-[10px] text-emerald-300/90">{renderJson(tool.output)}</pre></> : <span className="text-[10px] text-slate-500">尚无结果</span>}
    </section>
    <section><div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-rose-400/80">ERROR</div>
      {tool.error ? <div className="max-h-24 overflow-auto rounded border border-rose-800/30 bg-rose-950/40 p-1.5 text-[10px] text-rose-300">{String(tool.error).slice(0, 700)}</div> : <span className="text-[10px] text-slate-500">无错误</span>}
    </section>
    {tool.executionSite === 'browser' && <section><div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-sky-400/80">BROWSER RECEIPT</div>
      {tool.browserReceipt ? <div className="rounded border border-sky-800/30 bg-sky-950/30 p-1.5 text-[10px] text-sky-200">Status: {tool.browserReceipt.status} · Effect: {tool.browserReceipt.effectStatus || 'unknown'} · Dimension: {tool.browserReceipt.runtimeDimension || 'unknown'} · Revision: {tool.browserReceipt.stateRevision ?? 'unknown'}</div> : <span className="text-[10px] text-slate-500">{tool.status === 'waiting_browser' ? '等待浏览器回执' : '未返回浏览器回执'}</span>}
    </section>}
  </div>;
};
