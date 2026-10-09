/**
 * RFC 7807 Problem Details representation for frontend error handling.
 */

export interface ProblemDetails {
  type: string;
  title: string;
  status: number;
  detail: string;
  instance?: string;
  error?: {
    type: string;
    title: string;
    status: number;
    detail: string;
    instance?: string;
  };
}

export function isProblemDetails(value: unknown): value is ProblemDetails {
  if (!value || typeof value !== 'object') return false;
  const obj = value as Record<string, unknown>;
  return (
    typeof obj.title === 'string' &&
    typeof obj.status === 'number' &&
    typeof obj.detail === 'string'
  );
}

export function parseProblemDetails(value: unknown): ProblemDetails | null {
  if (isProblemDetails(value)) return value;
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      if (isProblemDetails(parsed)) return parsed;
      if (parsed && typeof parsed === 'object' && isProblemDetails(parsed.error)) {
        return parsed.error;
      }
    } catch {
      return null;
    }
  }
  return null;
}
