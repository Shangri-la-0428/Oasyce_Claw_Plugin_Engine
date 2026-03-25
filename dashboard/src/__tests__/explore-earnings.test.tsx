/**
 * ExploreEarnings component tests
 *
 * Covers:
 * 1. Loading skeleton states
 * 2. Empty state (new provider) with CTA
 * 3. Earnings stats display
 * 4. Invocation list rendering + status badges
 * 5. Expand/collapse invocation details
 * 6. Provider actions (complete / claim) per status
 * 7. i18n parity for new keys
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'preact';
import { act } from 'preact/test-utils';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

const mockClipboard = { writeText: vi.fn().mockResolvedValue(undefined) };
Object.defineProperty(navigator, 'clipboard', { value: mockClipboard, writable: true });

import { i18n, lang } from '../store/ui';
import ExploreEarnings from '../pages/explore-earnings';

function okJson(data: any) {
  return { ok: true, status: 200, text: async () => JSON.stringify(data), json: async () => data };
}

async function settle(n = 12) {
  for (let i = 0; i < n; i++) {
    await act(async () => { await new Promise(r => setTimeout(r, 0)); });
  }
}

const EARNINGS = { provider_id: 'alice', total_earnings: 123.45, invocations: 42 };
const EARNINGS_EMPTY = { provider_id: 'alice', total_earnings: 0, invocations: 0 };
const INVOCATIONS = [
  { invocation_id: 'INV_001', capability_id: 'CAP_A', price: 2.5, status: 'pending', timestamp: 1711353600 },
  { invocation_id: 'INV_002', capability_id: 'CAP_B', price: 1.0, status: 'completed', timestamp: 1711350000 },
  { invocation_id: 'INV_003', capability_id: 'CAP_C', price: 0.5, status: 'disputed', timestamp: 1711346400 },
];

function setupMock(earnings = EARNINGS, invocations: any[] = INVOCATIONS) {
  mockFetch.mockImplementation((...args: any[]) => {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url ?? '';
    if (url.includes('/auth/token')) return Promise.resolve(okJson({ token: 'test' }));
    if (url.includes('/delivery/earnings')) return Promise.resolve(okJson(earnings));
    if (url.includes('/delivery/invocations')) return Promise.resolve(okJson(invocations));
    if (url.includes('/delivery/invocation') && url.includes('/complete')) return Promise.resolve(okJson({ ok: true }));
    if (url.includes('/delivery/invocation') && url.includes('/claim')) return Promise.resolve(okJson({ ok: true }));
    return Promise.resolve(okJson({}));
  });
}

describe('ExploreEarnings', () => {
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

  async function mount(props: { onRegister?: () => void } = {}) {
    await act(async () => { render(<ExploreEarnings {...props} />, container); });
    await settle();
  }

  // ═══════════════════════════════════════════════
  // 1. Loading states
  // ═══════════════════════════════════════════════
  it('shows loading skeletons initially', async () => {
    mockFetch.mockReturnValue(new Promise(() => {}));
    await act(async () => { render(<ExploreEarnings />, container); });

    expect(container.querySelectorAll('.skeleton').length).toBeGreaterThanOrEqual(1);
  });

  // ═══════════════════════════════════════════════
  // 2. Empty state
  // ═══════════════════════════════════════════════
  it('shows empty state for new provider', async () => {
    setupMock(EARNINGS_EMPTY, []);
    await mount({ onRegister: () => {} });

    const empty = container.querySelector('.empty-state');
    expect(empty).not.toBeNull();
    expect(empty!.textContent).toContain(i18n.value['earnings-empty']);
  });

  it('empty state CTA calls onRegister', async () => {
    const onRegister = vi.fn();
    setupMock(EARNINGS_EMPTY, []);
    await mount({ onRegister });

    const btn = container.querySelector('.empty-state button') as HTMLButtonElement;
    expect(btn).not.toBeNull();
    await act(async () => { btn.click(); });
    expect(onRegister).toHaveBeenCalledOnce();
  });

  it('hides invocation history when empty', async () => {
    setupMock(EARNINGS_EMPTY, []);
    await mount();

    expect(container.querySelector('.inv-list')).toBeNull();
  });

  // ═══════════════════════════════════════════════
  // 3. Earnings stats
  // ═══════════════════════════════════════════════
  it('displays total earnings and invocation count', async () => {
    await mount();

    const statVals = container.querySelectorAll('.earnings-stat-val');
    expect(statVals.length).toBe(2);
    expect(statVals[0].textContent).toContain('123.45');
    expect(statVals[1].textContent).toContain('42');
  });

  // ═══════════════════════════════════════════════
  // 4. Invocation list
  // ═══════════════════════════════════════════════
  it('renders all invocations with statuses', async () => {
    await mount();

    const items = container.querySelectorAll('.inv-item');
    expect(items.length).toBe(3);
    expect(container.querySelector('.inv-status-pending')).not.toBeNull();
    expect(container.querySelector('.inv-status-completed')).not.toBeNull();
    expect(container.querySelector('.inv-status-disputed')).not.toBeNull();
  });

  it('shows prices', async () => {
    await mount();

    const prices = container.querySelectorAll('.inv-price');
    expect(prices[0].textContent).toContain('2.50');
    expect(prices[1].textContent).toContain('1.00');
    expect(prices[2].textContent).toContain('0.50');
  });

  it('shows invocation-empty when no invocations but has earnings', async () => {
    setupMock(EARNINGS, []);
    await mount();

    const empty = container.querySelector('.empty-state');
    expect(empty).not.toBeNull();
    expect(empty!.textContent).toContain(i18n.value['invocation-empty']);
  });

  // ═══════════════════════════════════════════════
  // 5. Expand/collapse
  // ═══════════════════════════════════════════════
  it('expand on click, collapse on second click', async () => {
    await mount();

    const items = container.querySelectorAll('.inv-item');
    expect(container.querySelector('.inv-detail')).toBeNull();

    await act(async () => { (items[0] as HTMLElement).click(); });
    expect(container.querySelector('.inv-detail')).not.toBeNull();
    expect(items[0].classList.contains('inv-item-expanded')).toBe(true);

    await act(async () => { (items[0] as HTMLElement).click(); });
    expect(container.querySelector('.inv-detail')).toBeNull();
  });

  it('only one expanded at a time', async () => {
    await mount();

    const items = container.querySelectorAll('.inv-item');
    await act(async () => { (items[0] as HTMLElement).click(); });
    expect(items[0].classList.contains('inv-item-expanded')).toBe(true);

    await act(async () => { (items[1] as HTMLElement).click(); });
    expect(items[0].classList.contains('inv-item-expanded')).toBe(false);
    expect(items[1].classList.contains('inv-item-expanded')).toBe(true);
  });

  // ═══════════════════════════════════════════════
  // 6. Provider actions
  // ═══════════════════════════════════════════════
  it('"complete" button for pending invocations', async () => {
    await mount();

    const items = container.querySelectorAll('.inv-item');
    await act(async () => { (items[0] as HTMLElement).click(); }); // pending

    const btn = items[0].querySelector('.inv-detail button.btn-sm');
    expect(btn).not.toBeNull();
    expect(btn!.textContent).toContain(i18n.value['inv-complete']);
  });

  it('"claim" button for completed invocations', async () => {
    await mount();

    const items = container.querySelectorAll('.inv-item');
    await act(async () => { (items[1] as HTMLElement).click(); }); // completed

    const btn = items[1].querySelector('.inv-detail button.btn-sm');
    expect(btn).not.toBeNull();
    expect(btn!.textContent).toContain(i18n.value['inv-claim']);
  });

  it('no action buttons for disputed invocations', async () => {
    await mount();

    const items = container.querySelectorAll('.inv-item');
    await act(async () => { (items[2] as HTMLElement).click(); }); // disputed

    const actionBtns = items[2].querySelectorAll('.inv-detail button.btn-sm');
    expect(actionBtns.length).toBe(0);
  });

  it('complete action calls correct API endpoint', async () => {
    const fetchCalls: string[] = [];
    mockFetch.mockImplementation((...args: any[]) => {
      const url = typeof args[0] === 'string' ? args[0] : args[0]?.url ?? '';
      fetchCalls.push(url);
      if (url.includes('/auth/token')) return Promise.resolve(okJson({ token: 'test' }));
      if (url.includes('/delivery/earnings')) return Promise.resolve(okJson(EARNINGS));
      if (url.includes('/delivery/invocations')) return Promise.resolve(okJson(INVOCATIONS));
      if (url.includes('/complete')) return Promise.resolve(okJson({ ok: true }));
      return Promise.resolve(okJson({}));
    });

    await mount();
    const items = container.querySelectorAll('.inv-item');
    await act(async () => { (items[0] as HTMLElement).click(); });

    const btn = items[0].querySelector('.inv-detail button.btn-sm') as HTMLElement;
    await act(async () => { btn.click(); });
    await settle();

    expect(fetchCalls.some(u => u.includes('/delivery/invocation/INV_001/complete'))).toBe(true);
  });

  // ═══════════════════════════════════════════════
  // 7. i18n parity
  // ═══════════════════════════════════════════════
  describe('i18n keys', () => {
    const KEYS = [
      'inv-complete', 'inv-claim', 'inv-completing', 'inv-claiming',
      'inv-complete-success', 'inv-claim-success',
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
