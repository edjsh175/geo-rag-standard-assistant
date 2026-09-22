import * as shapefile from 'shapefile';
import { GisExecutionError } from './contracts';
import { resolveVectorDataset } from './fileReferenceStore';

export interface ParsedVectorDataset {
  name: string;
  features: Array<Record<string, unknown>>;
}

export const readVectorDataset = async (fileRef: string): Promise<ParsedVectorDataset> => {
  const dataset = resolveVectorDataset(fileRef);
  if (dataset.format === 'geojson') {
    let payload: Record<string, any>;
    try {
      payload = JSON.parse(await dataset.file.text()) as Record<string, any>;
    } catch (error) {
      throw new GisExecutionError('VECTOR_PARSE_FAILED', error instanceof Error ? error.message : 'GeoJSON 解析失败');
    }
    const features: Array<Record<string, unknown>> = payload.type === 'FeatureCollection' && Array.isArray(payload.features)
      ? payload.features as Array<Record<string, unknown>>
      : payload.type === 'Feature'
        ? [payload as Record<string, unknown>]
        : [];
    if (!features.length) throw new GisExecutionError('EMPTY_VECTOR_DATASET', '矢量数据集没有可显示要素');
    return { name: dataset.name, features };
  }

  const source = await shapefile.open(await dataset.shp.arrayBuffer(), await dataset.dbf.arrayBuffer(), { encoding: 'utf-8' });
  const features: Array<Record<string, unknown>> = [];
  while (true) {
    const result = await source.read();
    if (!result || result.done) break;
    if (result.value?.type === 'Feature' && result.value.geometry) features.push(result.value as Record<string, unknown>);
  }
  if (!features.length) throw new GisExecutionError('EMPTY_VECTOR_DATASET', '矢量数据集没有可显示要素');
  return { name: dataset.name, features };
};
