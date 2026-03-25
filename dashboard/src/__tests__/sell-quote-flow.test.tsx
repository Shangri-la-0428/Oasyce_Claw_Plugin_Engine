/**
 * Sell Quote Flow tests — ExplorePortfolio sell quote preview
 *
 * Covers:
 * 1. Sell button opens inline form
 * 2. Quote button fetches quote and displays breakdown
 * 3. High price impact (>5%) shows warning
 * 4. Back button clears quote
 * 5. Amount change resets quote
 * 6. Quote button disabled without amount
 * 7. Confirm + back buttons exist in quote card
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'preact';
import { act } from 'preact/test-utils';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// Mock dispute-form to reduce complexity
vi.mock('../components/dispute-form', () => ({
  DisputeForm: () => null,
  MyDisputes: () => null,
}));

import { i18n, lang } from '../store/ui';
import ExplorePortfolio from '../pages/explore-portfolio';

const HOLDINGS = [
  { asset_id: 'ASSET_001', shares: 25, avg_price: 3.5 },
];
const QUOTE_NORMAL = { payout_oas: 45.2, protocol_fee: 2.4, burn_amount: 0.96, price_impact_pct: 3.5 };
const QUOTE_HIGH = { payout_oas: 30.0, protocol_fee: 2.0, burn_amount: 0.8, price_impact_pct: 12.7 };

function okJson(data: any) {
  return { ok: true, status: 200, text: async () => JSON.stringify(data), json: async () => data };
}

async function settle(n = 12) {
  for (let i = 0; i < n; i++) {
    await act(async () => { await new Promise(r => setTimeout(r, 0)); });
  }
}

/** Smart mock — routes by URL substring */
function setupSmartMock(quoteData = QUOTE_NORMAL) {
  mockFetch.mockImplementation((...args: any[]) => {
    const url = typeof args[0] === 'string' ? args[0] : args[0]?.url ?? '';
    if (url.includes('/auth/token')) return Promise.resolve(okJson({ token: 'test' }));
    if (url.includes('/shares')) return Promise.resolve(okJson(HOLDINGS));
    if (url.includes('/transactions')) return Promise.resolve(okJson([]));
    if (url.includes('/sell/quote')) return Promise.resolve(okJson(quoteData));
    if (url.includes('/sell')) return Promise.resolve(okJson({ ok: true }));
    return Promise.resolve(okJson({}));
  });
}

describe('Sell Quote Flow', () => {
  let container: HTMLElement;

  beforeEach(() => {
    mockFetch.mockReset();
    setupSmartMock();
    lang.value = 'zh';
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    render(null, container);
    container.remove();
  });

  async function mount() {
    await act(async () => { render(<ExplorePortfolio />, container); });
    await settle();
  }

  function findSellButton(): HTMLElement | undefined {
    return Array.from(container.querySelectorAll('button')).find(
      b => b.textContent?.trim() === i18n.value['sell'] && b.closest('.portfolio-stats')
    ) as HTMLElement | undefined;
  }

  // ═══════════════════════════════════════════════
  // 1. Sell form opens
  // ═══════════════════════════════════════════════
  it('clicking Sell opens inline form', async () => {
    await mount();

    expect(container.querySelector('.sell-flow')).toBeNull();

    const sellBtn = findSellButton();
    expect(sellBtn, 'sell button not found').toBeDefined();
    await act(async () => { sellBtn!.click(); });

    expect(container.querySelector('.sell-flow')).not.toBeNull();
    expect(container.querySelector('.sell-flow input[type="number"]')).not.toBeNull();
  });

  // ═══════════════════════════════════════════════
  // 2. Quote fetches and displays breakdown
  // ═══════════════════════════════════════════════
  it('quote shows payout/fee/burn/impact', async () => {
    await mount();
    await act(async () => { findSellButton()!.click(); });

    const input = container.querySelector('.sell-flow input[type="number"]') as HTMLInputElement;
    await act(async () => {
      input.value = '12.5';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const quoteBtn = Array.from(container.querySelectorAll('.sell-flow button')).find(
      b => b.textContent?.includes(i18n.value['sell-quote'])
    ) as HTMLElement;
    await act(async () => { quoteBtn.click(); });
    await settle();

    const card = container.querySelector('.sell-quote-card');
    expect(card).not.toBeNull();
    expect(card!.textContent).toContain('45.20');
    expect(card!.textContent).toContain('2.40');
    expect(card!.textContent).toContain('0.96');
    expect(card!.textContent).toContain('3.5%');
  });

  // ═══════════════════════════════════════════════
  // 3. High price impact warning
  // ═══════════════════════════════════════════════
  it('shows warning for price impact > 5%', async () => {
    setupSmartMock(QUOTE_HIGH);
    await mount();
    await act(async () => { findSellButton()!.click(); });

    const input = container.querySelector('.sell-flow input[type="number"]') as HTMLInputElement;
    await act(async () => {
      input.value = '50';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const quoteBtn = Array.from(container.querySelectorAll('.sell-flow button')).find(
      b => b.textContent?.includes(i18n.value['sell-quote'])
    ) as HTMLElement;
    await act(async () => { quoteBtn.click(); });
    await settle();

    expect(container.querySelector('.sell-impact-warning')).not.toBeNull();
    expect(container.querySelector('.color-yellow')).not.toBeNull();
    expect(container.querySelector('.color-yellow')!.textContent).toContain('12.7%');
  });

  // ═══════════════════════════════════════════════
  // 4. Back clears quote
  // ═══════════════════════════════════════════════
  it('back clears quote card', async () => {
    await mount();
    await act(async () => { findSellButton()!.click(); });

    const input = container.querySelector('.sell-flow input[type="number"]') as HTMLInputElement;
    await act(async () => {
      input.value = '10';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const quoteBtn = Array.from(container.querySelectorAll('.sell-flow button')).find(
      b => b.textContent?.includes(i18n.value['sell-quote'])
    ) as HTMLElement;
    await act(async () => { quoteBtn.click(); });
    await settle();
    expect(container.querySelector('.sell-quote-card')).not.toBeNull();

    const backBtn = Array.from(container.querySelectorAll('.sell-quote-card button')).find(
      b => b.textContent?.includes(i18n.value['back'])
    ) as HTMLElement;
    await act(async () => { backBtn.click(); });

    expect(container.querySelector('.sell-quote-card')).toBeNull();
    expect(container.querySelector('.sell-flow')).not.toBeNull();
  });

  // ═══════════════════════════════════════════════
  // 5. Amount change resets quote
  // ═══════════════════════════════════════════════
  it('changing amount clears quote', async () => {
    await mount();
    await act(async () => { findSellButton()!.click(); });

    const input = container.querySelector('.sell-flow input[type="number"]') as HTMLInputElement;
    await act(async () => {
      input.value = '10';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const quoteBtn = Array.from(container.querySelectorAll('.sell-flow button')).find(
      b => b.textContent?.includes(i18n.value['sell-quote'])
    ) as HTMLElement;
    await act(async () => { quoteBtn.click(); });
    await settle();
    expect(container.querySelector('.sell-quote-card')).not.toBeNull();

    await act(async () => {
      input.value = '20';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });
    expect(container.querySelector('.sell-quote-card')).toBeNull();
  });

  // ═══════════════════════════════════════════════
  // 6. Quote button disabled without amount
  // ═══════════════════════════════════════════════
  it('quote button disabled when empty', async () => {
    await mount();
    await act(async () => { findSellButton()!.click(); });

    const quoteBtn = Array.from(container.querySelectorAll('.sell-flow button')).find(
      b => b.textContent?.includes(i18n.value['sell-quote'])
    ) as HTMLButtonElement;
    expect(quoteBtn).toBeDefined();
    expect(quoteBtn.disabled).toBe(true);
  });

  // ═══════════════════════════════════════════════
  // 7. Confirm + back buttons in quote card
  // ═══════════════════════════════════════════════
  it('quote card has back + confirm buttons', async () => {
    await mount();
    await act(async () => { findSellButton()!.click(); });

    const input = container.querySelector('.sell-flow input[type="number"]') as HTMLInputElement;
    await act(async () => {
      input.value = '5';
      input.dispatchEvent(new Event('input', { bubbles: true }));
    });

    const quoteBtn = Array.from(container.querySelectorAll('.sell-flow button')).find(
      b => b.textContent?.includes(i18n.value['sell-quote'])
    ) as HTMLElement;
    await act(async () => { quoteBtn.click(); });
    await settle();

    const cardBtns = container.querySelectorAll('.sell-quote-card button');
    expect(cardBtns.length).toBe(2);
    const texts = Array.from(cardBtns).map(b => b.textContent);
    expect(texts.some(t => t?.includes(i18n.value['back']))).toBe(true);
    expect(texts.some(t => t?.includes(i18n.value['sell-confirm']))).toBe(true);
  });
});
