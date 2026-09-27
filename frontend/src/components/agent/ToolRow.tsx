import React from 'react';
import { Wrench, Globe, CheckCircle2, XCircle, Clock } from 'lucide-react';
import { DisclosureRow } from './DisclosureRow';
import { GenericToolView } from './GenericToolView';
import { AgentToolItem } from './types';

export interface ToolRowProps { tool: AgentToolItem; paused?: boolean }

const titles: Record<string, string> = {
  retrieve_kb: '检索知识库', search_evidence_memory: '检索历史证据', reuse_evidence: '激活历史证据',
  locate_map: '地图视角定位', import_vector_dataset: '导入矢量数据集', set_layer_visibility: '图层显隐控制',
  set_vector_style: '更新矢量样式', fit_vector_layer: '缩放至图层范围', inspect_layer_features: '要素属性探查',
  get_feature_geometry: '提取要素空间几何', query_spatial_relation: 'PostGIS 空间关系查询', spatial_overlay: 'PostGIS 空间拓扑叠加',
};

export const ToolRow: React.FC<ToolRowProps> = ({ tool, paused = false }) => {
  const icon = tool.status === 'running'
    ? <Clock className={`h-3.5 w-3.5 text-amber-400 ${paused ? '' : 'motion-reduce:animate-none animate-spin'}`} />
    : tool.status === 'waiting_browser'
      ? <Globe className={`h-3.5 w-3.5 text-sky-400 ${paused ? '' : 'motion-reduce:animate-none animate-pulse'}`} />
      : tool.status === 'succeeded'
        ? <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />
        : <XCircle className="h-3.5 w-3.5 text-rose-400" />;
  const rowStatus = tool.status === 'succeeded' ? 'succeeded'
    : tool.status === 'failed' || tool.status === 'cancelled' ? 'failed'
      : tool.status === 'waiting_browser' ? 'waiting' : 'running';
  const title = titles[tool.toolName] || tool.toolName || '未知工具';
  return <DisclosureRow
    icon={tool.executionSite === 'browser' ? <Globe className="h-3.5 w-3.5 text-sky-400" /> : <Wrench className="h-3.5 w-3.5 text-slate-400" />}
    title={title}
    summary={`调用 ${tool.callId}${tool.executionSite === 'browser' ? ' · 浏览器地图运行时' : ''}`}
    status={rowStatus}
    badge={<div className="flex items-center gap-1.5 text-[11px]">{icon}<span className="font-mono">{tool.status}</span></div>}
    defaultExpanded={false}
  >
    <GenericToolView tool={tool} />
  </DisclosureRow>;
};
