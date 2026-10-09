import { describe, it, expect } from 'vitest';
import { isProblemDetails, parseProblemDetails, type ProblemDetails } from '../src/types/problemDetails';

describe('RFC 7807 ProblemDetails', () => {
  it('identifies valid ProblemDetails objects', () => {
    const valid: ProblemDetails = {
      type: 'urn:geoai:error:400',
      title: 'Bad Request',
      status: 400,
      detail: 'Invalid parameters',
      instance: '/api/test',
    };
    expect(isProblemDetails(valid)).toBe(true);
  });

  it('parses JSON string into ProblemDetails', () => {
    const jsonStr = JSON.stringify({
      type: 'about:blank',
      title: 'Not Found',
      status: 404,
      detail: 'Resource not found',
      instance: '/api/docs/123',
    });
    const parsed = parseProblemDetails(jsonStr);
    expect(parsed).not.toBeNull();
    expect(parsed?.status).toBe(404);
    expect(parsed?.detail).toBe('Resource not found');
  });

  it('parses nested error problem details', () => {
    const jsonStr = JSON.stringify({
      error: {
        type: 'urn:geoai:error:500',
        title: 'Server Error',
        status: 500,
        detail: 'Fatal error',
      },
    });
    const parsed = parseProblemDetails(jsonStr);
    expect(parsed).not.toBeNull();
    expect(parsed?.status).toBe(500);
    expect(parsed?.detail).toBe('Fatal error');
  });

  it('returns null for non-problem JSON', () => {
    expect(parseProblemDetails(JSON.stringify({ count: 123 }))).toBeNull();
    expect(parseProblemDetails('invalid json')).toBeNull();
  });
});
