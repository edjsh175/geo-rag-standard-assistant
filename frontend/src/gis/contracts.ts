export type VectorStyle = {
  stroke: { color: string; width: number; opacity: number };
  fill: { color: string; opacity: number };
  radius: number;
};

export type VectorStylePatch = {
  stroke?: Partial<VectorStyle['stroke']>;
  fill?: Partial<VectorStyle['fill']>;
  radius?: number;
};

export interface AvailableVectorFile {
  file_ref: string;
  name: string;
  format: 'shapefile' | 'geojson';
  parts: string[];
}

export interface UserVectorLayerState {
  layer_ref: string;
  name: string;
  geometry_types: string[];
  feature_count: number;
  feature_refs: string[];
  visible: boolean;
  style: VectorStyle;
}

export interface LayerTreeNode {
  layer_ref: string;
  parent_ref?: string;
  name: string;
  kind: 'base' | 'annotation' | 'business' | 'user_vector' | 'group' | 'unknown';
  visible: boolean;
  opacity: number;
  z_index?: number;
  children?: LayerTreeNode[];
}

export interface FeatureObservation {
  feature_ref: string;
  layer_ref: string;
  geometry_type: string | null;
  properties: Record<string, unknown>;
}

export interface BrowserMapContext {
  [key: string]: unknown;
  schema_version: 2;
  revision: number;
  dimension: '2d';
  ready: boolean;
  supported_tools: string[];
  viewport: { center: [number, number]; zoom: number; crs: 'EPSG:4326' } | null;
  layer_tree: LayerTreeNode[];
  user_layers: UserVectorLayerState[];
  available_files: AvailableVectorFile[];
}

export interface BrowserMapAction {
  type: string;
  target: string;
  payload?: Record<string, unknown> | null;
}

export interface BrowserToolReceipt {
  tool_call_id: string;
  tool_name: string;
  status: 'succeeded' | 'failed';
  output?: Record<string, unknown>;
  error?: string;
  effect: {
    status: 'applied' | 'unknown' | 'none';
    kind?: string;
    state_revision?: number;
  };
  map_context: BrowserMapContext;
}

export class GisExecutionError extends Error {
  constructor(public readonly code: string, message: string) {
    super(message);
    this.name = 'GisExecutionError';
  }
}
