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
  create_buffer: { title: 'PostGIS 缓冲区分析', input: ['center', 'distance_m'], output: ['evidence_id'] },
  render_geojson_layer: { title: '渲染 GeoJSON 图层', input: ['geojson', 'name', 'style'], output: ['layer_ref', 'feature_count'] },
  query_geospatial_data: { title: 'GeoSQL 空间查询', input: ['operation', 'target_table', 'select_fields', 'filters', 'spatial', 'limit'], output: ['evidence_id'] },
};

const fields = (value: Record<string, unknown> | undefined, names: string[]) => names
  .filter((name) => value && value[name] !== undefined)
  .map((name) => `${name}: ${safePreview(value?.[name])}`);

export interface GenericToolViewProps { tool: AgentToolItem }

export const GenericToolView: React.FC<GenericToolViewProps> = ({ tool }) => {
  const config = views[tool.toolName];
  const inputFacts = fields(tool.arguments, config?.input || []);
  const outputFacts = fields(tool.output, config?.output || []);
  return (
    <div className="space-y-2.5 font-sans" data-tool-renderer={config ? tool.toolName : 'generic'}>
      <div className="text-[10px] text-on-background/50 font-semibold uppercase tracking-wider flex items-center gap-1.5">
        <span>Call ID</span>
        <span className="normal-case font-mono text-on-background/80 font-medium px-1.5 py-0.5 rounded bg-surface-container/60 border border-outline/50">{tool.callId}</span>
      </div>
      {config && inputFacts.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {inputFacts.map((fact) => (
            <span key={fact} className="rounded-md bg-surface-container-high/60 border border-outline/50 px-2 py-0.5 text-[10px] text-on-background/75 font-mono">
              {fact}
            </span>
          ))}
        </div>
      )}
      <section>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-on-background/45">INPUT</div>
        {tool.arguments && Object.keys(tool.arguments).length ? (
          <pre className="max-h-40 overflow-auto rounded-lg border border-outline/60 bg-surface-container-lowest/60 p-2 text-[10.5px] text-on-background/85 font-mono shadow-inner leading-relaxed">{renderJson(tool.arguments)}</pre>
        ) : (
          <span className="text-[10.5px] text-on-background/40 italic">无输入字段</span>
        )}
      </section>
      <section>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-on-background/45">OUTPUT</div>
        {tool.output && Object.keys(tool.output).length ? (
          <>
            <div className="mb-1.5 flex flex-wrap gap-1">
              {outputFacts.map((fact) => (
                <span key={fact} className="rounded-md bg-emerald-500/10 border border-emerald-500/25 px-2 py-0.5 text-[10px] text-emerald-600 dark:text-emerald-300 font-mono font-medium">
                  {fact}
                </span>
              ))}
            </div>
            <pre className="max-h-40 overflow-auto rounded-lg border border-emerald-500/25 bg-emerald-500/[0.04] p-2 text-[10.5px] text-emerald-700 dark:text-emerald-300 font-mono shadow-inner leading-relaxed">{renderJson(tool.output)}</pre>
          </>
        ) : (
          <span className="text-[10.5px] text-on-background/40 italic">尚无结果</span>
        )}
      </section>
      <section>
        <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-rose-500/90">ERROR</div>
        {tool.error ? (
          <div className="max-h-24 overflow-auto rounded-lg border border-rose-500/30 bg-rose-500/10 p-2 text-[10.5px] text-rose-700 dark:text-rose-300 font-mono leading-relaxed">{String(tool.error).slice(0, 700)}</div>
        ) : (
          <span className="text-[10.5px] text-on-background/40 italic">无错误</span>
        )}
      </section>
      {tool.executionSite === 'browser' && (
        <section>
          <div className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-sky-500/90">BROWSER RECEIPT</div>
          {tool.browserReceipt ? (
            <div className="rounded-lg border border-sky-500/30 bg-sky-500/10 p-2 text-[10.5px] text-sky-700 dark:text-sky-300 font-mono leading-relaxed">
              Status: {tool.browserReceipt.status} · Effect: {tool.browserReceipt.effectStatus || 'unknown'} · Dimension: {tool.browserReceipt.runtimeDimension || 'unknown'} · Revision: {tool.browserReceipt.stateRevision ?? 'unknown'}
            </div>
          ) : (
            <span className="text-[10.5px] text-on-background/40 italic">{tool.status === 'waiting_browser' ? '等待浏览器回执' : '未返回浏览器回执'}</span>
          )}
        </section>
      )}
    </div>
  );
};
