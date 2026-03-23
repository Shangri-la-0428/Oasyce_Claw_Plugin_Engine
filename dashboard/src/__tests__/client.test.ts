import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock fetch globally before importing client
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// First call from ensureToken (module load) — just return no token
mockFetch.mockResolvedValueOnce({
  ok: false, status: 404, text: async () => '',
});

// Import after mock setup
const { get, post, del } = await import('../api/client');

function okResponse(data: any) {
  return {
    ok: true,
    status: 200,
    text: async () => JSON.stringify(data),
  };
}

function errResponse(status: number, error: string) {
  return {
    ok: false,
    status,
    text: async () => JSON.stringify({ error }),
  };
}

describe('API client', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    // ensureToken will call fetch if no cached token — return no-op
    mockFetch.mockResolvedValueOnce({ ok: false, status: 404, text: async () => '' });
  });

  describe('get', () => {
    it('returns success with data on 200', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ balance: 100 }));

      const res = await get('/balance/abc');
      expect(res.success).toBe(true);
      expect(res.data).toEqual({ balance: 100 });
    });

    it('returns error on non-ok status', async () => {
      mockFetch.mockResolvedValueOnce(errResponse(500, 'internal'));

      const res = await get('/fail');
      expect(res.success).toBe(false);
      expect(res.error).toBe('internal');
    });

    it('handles network errors', async () => {
      mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

      const res = await get('/down');
      expect(res.success).toBe(false);
      expect(res.error).toBe('error-network');
    });

    it('handles empty response body', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true, status: 200, text: async () => '',
      });

      const res = await get('/empty');
      expect(res.success).toBe(true);
      expect(res.data).toBeUndefined();
    });
  });

  describe('post', () => {
    it('sends JSON body and returns data', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ ok: true, asset_id: 'X' }));

      const res = await post<any>('/register', { file_path: '/tmp/a' });
      expect(res.success).toBe(true);
      expect(res.data?.ok).toBe(true);
    });

    it('returns error message from server', async () => {
      mockFetch.mockResolvedValueOnce(errResponse(400, 'file_path required'));

      const res = await post('/register', {});
      expect(res.success).toBe(false);
      expect(res.error).toBe('file_path required');
    });
  });

  describe('del', () => {
    it('sends DELETE request', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ ok: true }));

      const res = await del('/asset/X');
      expect(res.success).toBe(true);
    });
  });
});
