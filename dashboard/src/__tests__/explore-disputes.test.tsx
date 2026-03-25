/**
 * ExploreDisputes component tests
 *
 * Covers:
 * 1. Loading skeleton states
 * 2. Empty state when no disputes
 * 3. Dispute list rendering with status badges
 * 4. Status filter (all / open / resolved / dismissed)
 * 5. Expand/collapse dispute details
 * 6. Copy buttons in expanded view
 * 7. i18n parity for dispute keys
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'preact';
import { act } from 'preact/test-utils';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

const mockClipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
Object.defineProperty(navigator, 'clipboard', { value: mockClipboard, writable: true });

import { i18n, lang } from '../store/ui';
import ExploreDisputes from '../pages/explore-disputes';

function okJson(data: any) {
  return { ok: true, status: 200, text: async () => JSON.stringify(data), json: async () => data };
}

async function settle(n = 12) {
  for (let i = 0; i < n; i++) {
    await act(async () => { await new Promise(r => setTimeout(r, 0)); });
  }
}

const DISPUTES = [
  {
    dispute_id: 'DIS_001', asset_id: 'ASSET_A', buyer: 'BUYER_1',
    reason: 'data_quality', evidence_text: 'Missing columns',
    status: 'open', created_at: 1711353600, resolved_at: null, resolution: null,
  },
  {
    dispute_id: 'DIS_002', asset_id: 'ASSET_B', buyer: 'BUYER_2',
    reason: 'unauthorized_use', evidence_text: '',
    status: 'resolved', created_at: 1711350000, resolved_at: 1711360000, resolution: 'refund',
  },
  {
    dispute_id: 'DIS_003', asset_id: 'ASSET_C', buyer: 'BUYER_3',
    reason: 'service_unavailable', evidence_text: 'API returned 500',
    status: 'dismissed', created_at: 1711346400, resolved_at: 1711356400, resolution: 'no_action',
  },
];

function setupMock(disputes: any[] = DISPUTES) {
  mockFetch.mockImplementation((...args: any[]) => {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url ?? '';
    if (url.includes('/auth/token')) return Promise.resolve(okJson({ token: 'test' }));
    if (url.includes('/disputes')) return Promise.resolve(okJson({ disputes }));
    return Promise.resolve(okJson({}));
  });
}

describe('ExploreDisputes', () => {
  let container: HTMLElement;

  beforeEach(() => {
    mockFetch.mockReset();
    mockClipboard.writeText.mockClear();
    setupMock();
    lang.value = 'zh';
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    render(null, container);
    container.remove();
  });

  async function mount() {
    await act(async () => { render(<ExploreDisputes />, container); });
    await settle();
  }

  // ═══════════════════════════════════════════════
  // 1. Loading states
  // ═══════════════════════════════════════════════
  it('shows loading skeletons initially', async () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    await act(async () => { render(<ExploreDisputes />, container); });

    expect(container.querySelectorAll('.skeleton').length).toBeGreaterThanOrEqual(1);
  });

  // ═══════════════════════════════════════════════
  // 2. Empty state
  // ═══════════════════════════════════════════════
  it('shows empty state when no disputes', async () => {
    setupMock([]);
    await mount();

    const empty = container.querySelector('.empty-state');
    expect(empty).not.toBeNull();
    expect(empty!.textContent).toContain(i18n.value['dispute-no-global']);
  });

  // ═══════════════════════════════════════════════
  // 3. Dispute list rendering
  // ═══════════════════════════════════════════════
  it('renders all disputes with status badges', async () => {
    await mount();

    const items = container.querySelectorAll('.dispute-item');
    expect(items.length).toBe(3);
    expect(container.querySelector('.dispute-status-open')).not.toBeNull();
    expect(container.querySelector('.dispute-status-resolved')).not.toBeNull();
    expect(container.querySelector('.dispute-status-dismissed')).not.toBeNull();
  });

  it('shows reason text', async () => {
    await mount();

    const reasons = container.querySelectorAll('.dispute-item-reason');
    expect(reasons.length).toBe(3);
  });

  it('shows evidence text when present', async () => {
    await mount();

    const evidences = container.querySelectorAll('.dispute-item-evidence');
    // DIS_001 has evidence, DIS_002 has empty evidence, DIS_003 has evidence
    expect(evidences.length).toBe(2);
    expect(evidences[0].textContent).toContain('Missing columns');
  });

  // ═══════════════════════════════════════════════
  // 4. Status filters
  // ═══════════════════════════════════════════════
  it('shows all filter buttons', async () => {
    await mount();

    const filterBtns = container.querySelectorAll('.btn-sm');
    expect(filterBtns.length).toBe(4); // all, open, resolved, dismissed
  });

  it('filters by open status', async () => {
    await mount();

    const openBtn = Array.from(container.querySelectorAll('.btn-sm')).find(
      b => b.textContent?.includes(i18n.value['dispute-open'])
    ) as HTMLElement;
    expect(openBtn).toBeDefined();
    await act(async () => { openBtn.click(); });

    const items = container.querySelectorAll('.dispute-item');
    expect(items.length).toBe(1);
    expect(container.querySelector('.dispute-status-open')).not.toBeNull();
  });

  it('filters by resolved status', async () => {
    await mount();

    const resolvedBtn = Array.from(container.querySelectorAll('.btn-sm')).find(
      b => b.textContent?.includes(i18n.value['dispute-resolved'])
    ) as HTMLElement;
    await act(async () => { resolvedBtn.click(); });

    const items = container.querySelectorAll('.dispute-item');
    expect(items.length).toBe(1);
    expect(container.querySelector('.dispute-status-resolved')).not.toBeNull();
  });

  it('filters by dismissed status', async () => {
    await mount();

    const dismissedBtn = Array.from(container.querySelectorAll('.btn-sm')).find(
      b => b.textContent?.includes(i18n.value['dispute-dismissed'])
    ) as HTMLElement;
    await act(async () => { dismissedBtn.click(); });

    const items = container.querySelectorAll('.dispute-item');
    expect(items.length).toBe(1);
    expect(container.querySelector('.dispute-status-dismissed')).not.toBeNull();
  });

  it('all filter shows everything', async () => {
    await mount();

    // Switch to open first
    const openBtn = Array.from(container.querySelectorAll('.btn-sm')).find(
      b => b.textContent?.includes(i18n.value['dispute-open'])
    ) as HTMLElement;
    await act(async () => { openBtn.click(); });
    expect(container.querySelectorAll('.dispute-item').length).toBe(1);

    // Switch back to all
    const allBtn = Array.from(container.querySelectorAll('.btn-sm')).find(
      b => b.textContent?.includes(i18n.value['filter-all'])
    ) as HTMLElement;
    await act(async () => { allBtn.click(); });
    expect(container.querySelectorAll('.dispute-item').length).toBe(3);
  });

  it('shows empty state when filter matches nothing', async () => {
    setupMock([DISPUTES[0]]); // only 'open'
    await mount();

    const resolvedBtn = Array.from(container.querySelectorAll('.btn-sm')).find(
      b => b.textContent?.includes(i18n.value['dispute-resolved'])
    ) as HTMLElement;
    await act(async () => { resolvedBtn.click(); });

    expect(container.querySelector('.empty-state')).not.toBeNull();
  });

  // ═══════════════════════════════════════════════
  // 5. Expand/collapse
  // ═══════════════════════════════════════════════
  it('expand on click, collapse on second click', async () => {
    await mount();

    const items = container.querySelectorAll('.dispute-item');
    expect(container.querySelector('.inv-detail')).toBeNull();

    await act(async () => { (items[0] as HTMLElement).click(); });
    expect(container.querySelector('.inv-detail')).not.toBeNull();
    expect(items[0].classList.contains('inv-item-expanded')).toBe(true);

    await act(async () => { (items[0] as HTMLElement).click(); });
    expect(container.querySelector('.inv-detail')).toBeNull();
  });

  it('only one expanded at a time', async () => {
    await mount();

    const items = container.querySelectorAll('.dispute-item');
    await act(async () => { (items[0] as HTMLElement).click(); });
    expect(items[0].classList.contains('inv-item-expanded')).toBe(true);

    await act(async () => { (items[1] as HTMLElement).click(); });
    expect(items[0].classList.contains('inv-item-expanded')).toBe(false);
    expect(items[1].classList.contains('inv-item-expanded')).toBe(true);
  });

  it('shows resolved_at and resolution in expanded resolved dispute', async () => {
    await mount();

    const items = container.querySelectorAll('.dispute-item');
    // DIS_002 is resolved (index 1)
    await act(async () => { (items[1] as HTMLElement).click(); });

    const detail = container.querySelector('.inv-detail');
    expect(detail).not.toBeNull();
    expect(detail!.textContent).toContain(i18n.value['dispute-resolved-at']);
    expect(detail!.textContent).toContain(i18n.value['dispute-resolution']);
  });

  it('does not show resolved_at for open disputes', async () => {
    await mount();

    const items = container.querySelectorAll('.dispute-item');
    // DIS_001 is open (index 0)
    await act(async () => { (items[0] as HTMLElement).click(); });

    const kvKeys = container.querySelectorAll('.inv-detail .kv-key');
    const keyTexts = Array.from(kvKeys).map(k => k.textContent);
    expect(keyTexts).not.toContain(i18n.value['dispute-resolved-at']);
  });

  // ═══════════════════════════════════════════════
  // 6. Copy buttons
  // ═══════════════════════════════════════════════
  it('copy dispute ID on click', async () => {
    await mount();

    const items = container.querySelectorAll('.dispute-item');
    await act(async () => { (items[0] as HTMLElement).click(); });

    const copyBtns = container.querySelectorAll('.inv-detail .btn-link');
    expect(copyBtns.length).toBeGreaterThanOrEqual(2); // dispute_id + buyer

    await act(async () => { (copyBtns[0] as HTMLElement).click(); });
    await settle(); // copyText is async (dynamic import + clipboard)
    expect(mockClipboard.writeText).toHaveBeenCalledWith('DIS_001');
  });

  it('copy buyer on click', async () => {
    await mount();

    const items = container.querySelectorAll('.dispute-item');
    await act(async () => { (items[0] as HTMLElement).click(); });

    const copyBtns = container.querySelectorAll('.inv-detail .btn-link');
    await act(async () => { (copyBtns[1] as HTMLElement).click(); });
    await settle(); // copyText is async (dynamic import + clipboard)
    expect(mockClipboard.writeText).toHaveBeenCalledWith('BUYER_1');
  });

  // ═══════════════════════════════════════════════
  // 7. i18n parity
  // ═══════════════════════════════════════════════
  describe('i18n keys', () => {
    const KEYS = [
      'disputes-tab', 'all-disputes', 'dispute-buyer',
      'dispute-no-global', 'dispute-no-global-hint',
      'dispute-resolved-at', 'dispute-resolution', 'filter-all',
    ];

    it('zh has all keys', () => {
      lang.value = 'zh';
      for (const key of KEYS) {
        expect(i18n.value[key], `Missing zh: ${key}`).not.toBe(key);
      }
    });

    it('en has all keys', () => {
      lang.value = 'en';
      for (const key of KEYS) {
        expect(i18n.value[key], `Missing en: ${key}`).not.toBe(key);
      }
    });
  });
});
