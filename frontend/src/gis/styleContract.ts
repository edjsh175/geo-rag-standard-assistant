import type { VectorStyle, VectorStylePatch } from './contracts';
import { GisExecutionError } from './contracts';

const DEFAULT_STYLE: VectorStyle = {
  stroke: { color: '#f07040', width: 2, opacity: 1 },
  fill: { color: '#f07040', opacity: 0.18 },
  radius: 6,
};

const color = (value: string, field: string) => {
  if (!/^#[0-9a-fA-F]{6}$/.test(value)) {
    throw new GisExecutionError('INVALID_VECTOR_STYLE', `${field} 必须为 #RRGGBB`);
  }
  return value.toLowerCase();
};

const bounded = (value: number, min: number, max: number, field: string) => {
  if (!Number.isFinite(value) || value < min || value > max) {
    throw new GisExecutionError('INVALID_VECTOR_STYLE', `${field} 超出允许范围`);
  }
  return value;
};

export const defaultVectorStyle = (): VectorStyle => structuredClone(DEFAULT_STYLE);

export const mergeVectorStyle = (current: VectorStyle, patch: VectorStylePatch): VectorStyle => {
  if (!patch || Object.keys(patch).length === 0) {
    throw new GisExecutionError('INVALID_VECTOR_STYLE', 'style 至少包含一个修改项');
  }
  const next: VectorStyle = {
    stroke: { ...current.stroke, ...(patch.stroke ?? {}) },
    fill: { ...current.fill, ...(patch.fill ?? {}) },
    radius: patch.radius ?? current.radius,
  };
  return {
    stroke: {
      color: color(next.stroke.color, 'stroke.color'),
      width: bounded(next.stroke.width, 0, 64, 'stroke.width'),
      opacity: bounded(next.stroke.opacity, 0, 1, 'stroke.opacity'),
    },
    fill: {
      color: color(next.fill.color, 'fill.color'),
      opacity: bounded(next.fill.opacity, 0, 1, 'fill.opacity'),
    },
    radius: bounded(next.radius, 1, 128, 'radius'),
  };
};
