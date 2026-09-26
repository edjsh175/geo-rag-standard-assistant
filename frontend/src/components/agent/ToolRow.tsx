import React from 'react';
import { Wrench, Globe, CheckCircle2, XCircle, Clock } from 'lucide-react';
import { DisclosureRow } from './DisclosureRow';
import { AgentToolItem } from './types';

export interface ToolRowProps {
  tool: AgentToolItem;
}

export const ToolRow: React.FC<ToolRowProps> = ({ tool }) => {
  const getToolDisplayName = (name: string): string => {
    const map: Record<string, string> = {
      retrieve_kb: '检索知识库',
      search_evidence_memory: '检索历史证据',
      reuse_evidence: '激活历史证据',
      locate_map: '地图视角定位',
      import_vector_dataset: '导入矢量数据集',
      set_layer_visibility: '图层显隐控制',
      set_vector_style: '更新矢量样式',
      fit_vector_layer: '缩放至图层范围',
      inspect_layer_features: '要素属性探查',
      get_feature_geometry: '提取要素空间几何',
      query_spatial_relation: 'PostGIS 空间关系查询',
      spatial_overlay: 'PostGIS 空间拓扑叠加',
    };
    return map[name] || name;
  };

  const getStatusIcon = () => {
    switch (tool.status) {
      case 'running':
        return <Clock className="w-3.5 h-3.5 text-amber-400 animate-spin" />;
      case 'waiting_browser':
        return <Globe className="w-3.5 h-3.5 text-sky-400 animate-pulse" />;
      case 'succeeded':
        return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
      case 'failed':
      case 'cancelled':
        return <XCircle className="w-3.5 h-3.5 text-rose-400" />;
    }
  };

  const statusType =
    tool.status === 'succeeded'
      ? 'succeeded'
      : tool.status === 'failed' || tool.status === 'cancelled'
      ? 'failed'
      : tool.status === 'waiting_browser'
      ? 'waiting'
      : 'running';

  return (
    <DisclosureRow
      icon={tool.executionSite === 'browser' ? <Globe className="w-3.5 h-3.5 text-sky-400" /> : <Wrench className="w-3.5 h-3.5 text-slate-400" />}
      title={getToolDisplayName(tool.toolName)}
      status={statusType}
      summary={tool.executionSite === 'browser' ? '浏览器地图运行时执行' : undefined}
      badge={
        <div className="flex items-center gap-1.5 text-[11px]">
          {getStatusIcon()}
          <span className="font-mono">{tool.status}</span>
        </div>
      }
    >
      <div className="space-y-2">
        {tool.arguments && Object.keys(tool.arguments).length > 0 && (
          <div>
            <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-0.5">
              INPUT
            </div>
            <pre className="p-1.5 rounded bg-black/40 text-slate-300 text-[10px] overflow-x-auto">
              {JSON.stringify(tool.arguments, null, 2)}
            </pre>
          </div>
        )}

        {tool.browserReceipt && (
          <div>
            <div className="text-[10px] text-sky-400/80 font-semibold uppercase tracking-wider mb-0.5">
              BROWSER RECEIPT ({tool.browserReceipt.runtimeDimension || 'map'})
            </div>
            <div className="p-1.5 rounded bg-sky-950/30 border border-sky-800/30 text-sky-200 text-[10px]">
              Status: {tool.browserReceipt.status} | Rev: {tool.browserReceipt.stateRevision ?? 'N/A'}
            </div>
          </div>
        )}

        {tool.output && Object.keys(tool.output).length > 0 && (
          <div>
            <div className="text-[10px] text-slate-500 font-semibold uppercase tracking-wider mb-0.5">
              OUTPUT
            </div>
            <pre className="p-1.5 rounded bg-black/40 text-emerald-300/90 text-[10px] overflow-x-auto">
              {JSON.stringify(tool.output, null, 2)}
            </pre>
          </div>
        )}

        {tool.error && (
          <div>
            <div className="text-[10px] text-rose-400/80 font-semibold uppercase tracking-wider mb-0.5">
              ERROR
            </div>
            <div className="p-1.5 rounded bg-rose-950/40 border border-rose-800/30 text-rose-300 text-[10px]">
              {tool.error}
            </div>
          </div>
        )}
      </div>
    </DisclosureRow>
  );
};
