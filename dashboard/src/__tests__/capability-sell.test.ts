/**
 * Tests for Capability Earnings, Invocation History, and Sell Quote features.
 * PRD: docs/PRD-capability-sell.md
 *
 * Validates:
 * 1. i18n keys exist for all new strings (zh + en parity)
 * 2. API response shapes are handled correctly
 * 3. Edge cases: empty data, error responses, high price impact
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';

// ── Mock fetch globally ──
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

async function freshUI() {
  vi.resetModules();
  vi.stubGlobal('fetch', mockFetch);
  return await import('../store/ui');
}

/** Mock a successful fetch response (matches client.ts safeJson: res.text → JSON.parse) */
function okResponse(data: any) {
  return Promise.resolve({
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(data)),
  });
}

/** Mock a token response (consumed by ensureToken on module load) */
function tokenResponse() {
  return okResponse({ token: 'test-token' });
}

/** Mock a failed fetch response */
function errResponse(status = 400, error = 'test error') {
  return Promise.resolve({
    ok: false,
    status,
    text: () => Promise.resolve(JSON.stringify({ error })),
  });
}

/** Fresh import of client — needs token mock first */
async function freshClient() {
  vi.resetModules();
  vi.stubGlobal('fetch', mockFetch);
  mockFetch.mockReturnValueOnce(tokenResponse()); // ensureToken on module load
  return await import('../api/client');
}

// ────────────────────────────────────────────────────────────
// 1. i18n keys
// ────────────────────────────────────────────────────────────
describe('Capability & Sell i18n Keys', () => {
  const REQUIRED_KEYS = [
    'earnings-tab', 'total-earnings', 'total-invocations',
    'earnings-empty', 'earnings-empty-cta',
    'invocation-history', 'my-invocations', 'invocation-empty',
    'sell-quote', 'sell-payout', 'sell-fee', 'sell-burn',
    'sell-impact', 'sell-impact-warning', 'sell-confirm', 'sell-quoting',
  ];

  it('zh dictionary contains all required keys (not just Proxy fallback)', async () => {
    const ui = await freshUI();
    ui.lang.value = 'zh';
    const dict = ui.i18n.value;
    for (const key of REQUIRED_KEYS) {
      // Proxy returns key itself as fallback — that means the key is MISSING
      expect(dict[key], `Missing zh key: ${key}`).not.toBe(key);
    }
  });

  it('en dictionary contains all required keys (not just Proxy fallback)', async () => {
    const ui = await freshUI();
    ui.lang.value = 'en';
    const dict = ui.i18n.value;
    for (const key of REQUIRED_KEYS) {
      expect(dict[key], `Missing en key: ${key}`).not.toBe(key);
    }
  });
});

// ────────────────────────────────────────────────────────────
// 2. Delivery Earnings API
// ────────────────────────────────────────────────────────────
describe('Delivery Earnings API', () => {
  beforeEach(() => { mockFetch.mockReset(); });

  it('parses earnings response with total and invocations', async () => {
    const { get } = await freshClient();
    mockFetch.mockReturnValueOnce(tokenResponse()); // ensureToken in get()
    mockFetch.mockReturnValueOnce(okResponse({ provider_id: 'alice', total_earnings: 123.45, invocations: 42 }));

    const res = await get<any>('/delivery/earnings?provider=alice');
    expect(res.success).toBe(true);
    expect(res.data.total_earnings).toBe(123.45);
    expect(res.data.invocations).toBe(42);
  });

  it('handles empty earnings (new provider)', async () => {
    const { get } = await freshClient();
    mockFetch.mockReturnValueOnce(tokenResponse());
    mockFetch.mockReturnValueOnce(okResponse({ provider_id: 'alice', total_earnings: 0, invocations: 0 }));

    const res = await get<any>('/delivery/earnings?provider=alice');
    expect(res.success).toBe(true);
    expect(res.data.total_earnings).toBe(0);
  });
});

// ────────────────────────────────────────────────────────────
// 3. Delivery Invocations API
// ────────────────────────────────────────────────────────────
describe('Delivery Invocations API', () => {
  beforeEach(() => { mockFetch.mockReset(); });

  it('parses invocation list', async () => {
    const { get } = await freshClient();
    const invocations = [
      { invocation_id: 'INV_001', capability_id: 'CAP_A', price: 2.5, status: 'completed', timestamp: 1711353600 },
      { invocation_id: 'INV_002', capability_id: 'CAP_B', price: 1.0, status: 'disputed', timestamp: 1711350000 },
    ];
    mockFetch.mockReturnValueOnce(tokenResponse());
    mockFetch.mockReturnValueOnce(okResponse(invocations));

    const res = await get<any[]>('/delivery/invocations?consumer=bob&limit=20');
    expect(res.success).toBe(true);
    expect(res.data).toHaveLength(2);
    expect(res.data![0].invocation_id).toBe('INV_001');
    expect(res.data![1].status).toBe('disputed');
  });

  it('handles empty invocation list', async () => {
    const { get } = await freshClient();
    mockFetch.mockReturnValueOnce(tokenResponse());
    mockFetch.mockReturnValueOnce(okResponse([]));

    const res = await get<any[]>('/delivery/invocations?consumer=bob&limit=20');
    expect(res.success).toBe(true);
    expect(res.data).toHaveLength(0);
  });
});

// ────────────────────────────────────────────────────────────
// 4. Sell Quote API
// ────────────────────────────────────────────────────────────
describe('Sell Quote API', () => {
  beforeEach(() => { mockFetch.mockReset(); });

  it('parses sell quote with payout and fees', async () => {
    const { get } = await freshClient();
    mockFetch.mockReturnValueOnce(tokenResponse());
    mockFetch.mockReturnValueOnce(okResponse({ payout_oas: 45.2, protocol_fee: 2.4, burn_amount: 0.96, price_impact_pct: 3.5 }));

    const res = await get<any>('/sell/quote?asset_id=A1&seller=alice&tokens=12.5');
    expect(res.success).toBe(true);
    expect(res.data.payout_oas).toBe(45.2);
    expect(res.data.protocol_fee).toBe(2.4);
    expect(res.data.burn_amount).toBe(0.96);
    expect(res.data.price_impact_pct).toBe(3.5);
  });

  it('detects high price impact (> 5%)', async () => {
    const { get } = await freshClient();
    mockFetch.mockReturnValueOnce(tokenResponse());
    mockFetch.mockReturnValueOnce(okResponse({ payout_oas: 30.0, protocol_fee: 2.0, burn_amount: 0.8, price_impact_pct: 12.7 }));

    const res = await get<any>('/sell/quote?asset_id=A1&seller=alice&tokens=50');
    expect(res.success).toBe(true);
    expect(res.data.price_impact_pct).toBeGreaterThan(5);
  });

  it('handles sell quote error (insufficient shares)', async () => {
    const { get } = await freshClient();
    mockFetch.mockReturnValueOnce(tokenResponse());
    mockFetch.mockReturnValueOnce(errResponse(400, 'Insufficient shares'));

    const res = await get<any>('/sell/quote?asset_id=A1&seller=alice&tokens=9999');
    expect(res.success).toBe(false);
    expect(res.error).toBe('Insufficient shares');
  });
});
