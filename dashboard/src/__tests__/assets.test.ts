import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Mock fetch before any module that touches api/client ───────
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// First call is ensureToken from client.ts module load
mockFetch.mockResolvedValueOnce({ ok: false, status: 404, text: async () => '' });

const { assets, loadAssets, deleteAsset } = await import('../store/assets');

// Helpers
function okResponse(data: any) {
  return { ok: true, status: 200, text: async () => JSON.stringify(data) };
}
function errResponse(status: number) {
  return { ok: false, status, text: async () => JSON.stringify({ error: 'fail' }) };
}

describe('Assets Store', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    // ensureToken on every API call
    mockFetch.mockResolvedValueOnce({ ok: false, status: 404, text: async () => '' });
    // Reset signal
    assets.value = [];
  });

  // ──────────────────────────────────────────────────────────
  // 1. loadAssets — success
  // ──────────────────────────────────────────────────────────
  describe('loadAssets', () => {
    it('populates signal with array response', async () => {
      const mockData = [
        {
          asset_id: 'OAS_001',
          asset_type: 'data',
          owner: 'alice',
          tags: ['nlp'],
          spot_price: 1.5,
          status: 'active',
          name: 'Test Data',
          description: 'Some data',
        },
        {
          asset_id: 'OAS_002',
          asset_type: 'capability',
          owner: 'bob',
          tags: ['ml'],
          spot_price: 3.0,
          status: 'active',
        },
      ];
      mockFetch.mockResolvedValueOnce(okResponse(mockData));

      await loadAssets();

      expect(assets.value).toHaveLength(2);
      expect(assets.value[0].asset_id).toBe('OAS_001');
      expect(assets.value[0].owner).toBe('alice');
      expect(assets.value[1].asset_id).toBe('OAS_002');
      expect(assets.value[1].spot_price).toBe(3.0);
    });

    // ──────────────────────────────────────────────────────────
    // 2. loadAssets — non-array response doesn't crash
    // ──────────────────────────────────────────────────────────
    it('does not crash on non-array response (e.g. object)', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ message: 'not an array' }));

      await loadAssets();

      // Should remain empty since Array.isArray check fails
      expect(assets.value).toEqual([]);
    });

    it('does not crash on null response', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, status: 200, text: async () => '' });

      await loadAssets();
      expect(assets.value).toEqual([]);
    });

    // ──────────────────────────────────────────────────────────
    // 3. loadAssets — failure leaves signal unchanged
    // ──────────────────────────────────────────────────────────
    it('leaves signal unchanged on server error', async () => {
      assets.value = [{ asset_id: 'existing', asset_type: 'data' } as any];
      mockFetch.mockResolvedValueOnce(errResponse(500));

      await loadAssets();

      expect(assets.value).toHaveLength(1);
      expect(assets.value[0].asset_id).toBe('existing');
    });

    it('leaves signal unchanged on network error', async () => {
      assets.value = [{ asset_id: 'existing' } as any];
      mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

      await loadAssets();

      expect(assets.value).toHaveLength(1);
      expect(assets.value[0].asset_id).toBe('existing');
    });
  });

  // ──────────────────────────────────────────────────────────
  // 4. deleteAsset — calls del with correct path
  // ──────────────────────────────────────────────────────────
  describe('deleteAsset', () => {
    it('sends DELETE request to /api/asset/{id}', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ ok: true }));

      await deleteAsset('OAS_ABC123');

      // The last fetch call (after ensureToken) should be the DELETE
      const deleteCalls = mockFetch.mock.calls.filter(
        (c: any[]) => c[0] === '/api/asset/OAS_ABC123'
      );
      expect(deleteCalls.length).toBeGreaterThanOrEqual(1);
      const opts = deleteCalls[0][1];
      expect(opts.method).toBe('DELETE');
    });

    it('returns success response', async () => {
      mockFetch.mockResolvedValueOnce(okResponse({ ok: true }));

      const result = await deleteAsset('OAS_X');
      expect(result.success).toBe(true);
    });
  });

  // ──────────────────────────────────────────────────────────
  // 5. Asset interface fields present in mock data
  // ──────────────────────────────────────────────────────────
  describe('Asset interface', () => {
    it('all major fields are representable', async () => {
      const fullAsset = {
        asset_id: 'OAS_FULL',
        asset_type: 'data' as const,
        owner: 'alice',
        provider: 'bob',
        name: 'Full Asset',
        description: 'Test all fields',
        version: '1.0.0',
        tags: ['a', 'b'],
        created_at: Date.now(),
        spot_price: 5.5,
        status: 'active',
        price_model: 'auto',
        price: 10,
        hash_status: 'ok' as const,
        rights_type: 'original',
        co_creators: [{ address: 'addr1', share: 60 }, { address: 'addr2', share: 40 }],
        disputed: false,
        delisted: false,
        total_calls: 100,
        success_rate: 0.95,
        avg_latency_ms: 120,
      };

      mockFetch.mockResolvedValueOnce(okResponse([fullAsset]));
      await loadAssets();

      const a = assets.value[0];
      expect(a.asset_id).toBe('OAS_FULL');
      expect(a.asset_type).toBe('data');
      expect(a.tags).toEqual(['a', 'b']);
      expect(a.co_creators).toHaveLength(2);
      expect(a.hash_status).toBe('ok');
      expect(a.success_rate).toBe(0.95);
    });
  });
});
