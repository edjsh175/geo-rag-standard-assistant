import JSZip from 'jszip';
import type { AvailableVectorFile } from './contracts';
import { GisExecutionError } from './contracts';

type BrowserFile = Pick<File, 'name' | 'arrayBuffer' | 'text'>;
type DatasetRecord = AvailableVectorFile & {
  dataset:
    | { format: 'geojson'; name: string; file: BrowserFile }
    | { format: 'shapefile'; name: string; shp: BrowserFile; dbf: BrowserFile; shx?: BrowserFile; prj?: BrowserFile };
};

const records = new Map<string, DatasetRecord>();
const splitName = (name: string) => {
  const match = /^(.*)\.([^.]+)$/.exec(name.trim());
  if (!match) throw new GisExecutionError('INVALID_ARGUMENT', '文件缺少扩展名');
  return { base: match[1], ext: match[2].toLowerCase() };
};

const fromZip = async (file: BrowserFile): Promise<BrowserFile[]> => {
  const zip = await JSZip.loadAsync(await file.arrayBuffer());
  const entries = Object.values(zip.files).filter((entry) => {
    if (entry.dir) return false;
    const ext = splitName(entry.name).ext;
    return ['shp', 'dbf', 'shx', 'prj'].includes(ext);
  });
  return Promise.all(entries.map(async (entry) => {
    const name = entry.name.split('/').pop() ?? entry.name;
    const bytes = await entry.async('uint8array');
    return new File([bytes], name);
  }));
};

export const registerVectorDataset = async (input: FileList | File[]): Promise<AvailableVectorFile> => {
  let files: BrowserFile[] = Array.from(input);
  if (files.length === 1 && splitName(files[0].name).ext === 'zip') {
    files = await fromZip(files[0]);
  }
  if (files.length === 1 && ['geojson', 'json'].includes(splitName(files[0].name).ext)) {
    const { base } = splitName(files[0].name);
    const record: DatasetRecord = {
      file_ref: `vf_${crypto.randomUUID()}`,
      name: base,
      format: 'geojson',
      parts: [splitName(files[0].name).ext],
      dataset: { format: 'geojson', name: base, file: files[0] },
    };
    records.set(record.file_ref, record);
    return { file_ref: record.file_ref, name: record.name, format: record.format, parts: [...record.parts] };
  }

  const indexed = files.map((file) => ({ file, ...splitName(file.name) }));
  const shp = indexed.find((item) => item.ext === 'shp');
  const dbf = indexed.find((item) => item.ext === 'dbf');
  if (!shp || !dbf || indexed.some((item) => item.base.toLowerCase() !== shp.base.toLowerCase())) {
    throw new GisExecutionError('INVALID_ARGUMENT', 'Shapefile 需要同名 .shp 与 .dbf，可附带 .shx/.prj，或选择单个 ZIP');
  }
  const record: DatasetRecord = {
    file_ref: `vf_${crypto.randomUUID()}`,
    name: shp.base,
    format: 'shapefile',
    parts: indexed.map((item) => item.ext),
    dataset: {
      format: 'shapefile',
      name: shp.base,
      shp: shp.file,
      dbf: dbf.file,
      shx: indexed.find((item) => item.ext === 'shx')?.file,
      prj: indexed.find((item) => item.ext === 'prj')?.file,
    },
  };
  records.set(record.file_ref, record);
  return { file_ref: record.file_ref, name: record.name, format: record.format, parts: [...record.parts] };
};

export const resolveVectorDataset = (fileRef: string): DatasetRecord['dataset'] => {
  const record = records.get(fileRef);
  if (!record) throw new GisExecutionError('FILE_REF_EXPIRED', '文件引用不存在或已失效');
  return record.dataset;
};

export const listVectorDatasets = (): AvailableVectorFile[] =>
  [...records.values()].map(({ dataset: _dataset, ...summary }) => ({ ...summary, parts: [...summary.parts] }));
