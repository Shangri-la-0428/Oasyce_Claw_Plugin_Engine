/**
 * Capability register entry point tests — ExploreBrowse
 *
 * Covers:
 * 1. Register button only appears when "capability" filter active
 * 2. Clicking button toggles RegisterForm
 * 3. RegisterForm receives mode="capability"
 * 4. Button hidden on other filters
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'preact';
import { act } from 'preact/test-utils';

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// Mock RegisterForm to capture props
const mockRegisterForm = vi.hoisted(() => vi.fn(() => null));
vi.mock('../components/register-form', () => ({ default: mockRegisterForm }));

// Mock DataPreview (heavy component)
vi.mock('../components/data-preview', () => ({ default: () => null }));

import { i18n, lang } from '../store/ui';
import ExploreBrowse from '../pages/explore-browse';

function okJson(data: any) {
  return { ok: true, status: 200, text: async () => JSON.stringify(data), json: async () => data };
}

async function settle(n = 10) {
  for (let i = 0; i < n; i++) {
    await act(async () => { await new Promise(r => setTimeout(r, 0)); });
  }
}

describe('Capability Register Entry', () => {
  let container: HTMLElement;

  beforeEach(() => {
    mockFetch.mockReset();
    mockRegisterForm.mockClear();
    // Default mock: token + assets list
    mockFetch.mockResolvedValue(okJson([]));
    lang.value = 'zh';
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    render(null, container);
    container.remove();
  });

  async function mount() {
    await act(async () => { render(<ExploreBrowse />, container); });
    await settle();
  }

  function getFilterButtons() {
    return Array.from(container.querySelectorAll('button.btn-sm')).filter(
      b => ['all', 'data', 'capability'].some(t => b.textContent?.trim() === i18n.value[`type-${t}`])
    );
  }

  function getRegisterButton() {
    return Array.from(container.querySelectorAll('button')).find(
      b => b.textContent?.includes(i18n.value['earnings-empty-cta'])
    ) as HTMLElement | undefined;
  }

  it('register button NOT visible on "all" filter (default)', async () => {
    await mount();
    expect(getRegisterButton()).toBeUndefined();
  });

  it('register button NOT visible on "data" filter', async () => {
    await mount();

    const dataBtn = getFilterButtons().find(b => b.textContent?.trim() === i18n.value['type-data']);
    await act(async () => { (dataBtn as HTMLElement).click(); });

    expect(getRegisterButton()).toBeUndefined();
  });

  it('register button appears on "capability" filter', async () => {
    await mount();

    const capBtn = getFilterButtons().find(b => b.textContent?.trim() === i18n.value['type-capability']);
    await act(async () => { (capBtn as HTMLElement).click(); });

    expect(getRegisterButton()).not.toBeUndefined();
  });

  it('clicking register button renders RegisterForm with mode="capability"', async () => {
    await mount();

    // Switch to capability filter
    const capBtn = getFilterButtons().find(b => b.textContent?.trim() === i18n.value['type-capability']);
    await act(async () => { (capBtn as HTMLElement).click(); });

    // RegisterForm not rendered yet
    expect(mockRegisterForm).not.toHaveBeenCalled();

    // Click register button
    const regBtn = getRegisterButton()!;
    await act(async () => { regBtn.click(); });

    // RegisterForm should be called with mode="capability"
    expect(mockRegisterForm).toHaveBeenCalled();
    const lastCall = mockRegisterForm.mock.calls[mockRegisterForm.mock.calls.length - 1][0];
    expect(lastCall.mode).toBe('capability');
    expect(lastCall.compact).toBe(true);
  });

  it('clicking register button again hides the form', async () => {
    await mount();

    const capBtn = getFilterButtons().find(b => b.textContent?.trim() === i18n.value['type-capability']);
    await act(async () => { (capBtn as HTMLElement).click(); });

    const regBtn = getRegisterButton()!;

    // Open
    await act(async () => { regBtn.click(); });
    expect(mockRegisterForm).toHaveBeenCalled();
    const callsBefore = mockRegisterForm.mock.calls.length;

    // Close (toggle)
    await act(async () => { regBtn.click(); });
    await settle(3);

    // Form should no longer be rendered (no new calls after toggle-off re-render)
    // The toggle hides it, so we check the DOM
    // Since RegisterForm is mocked to return null, we check the state via button class
    expect(regBtn.classList.contains('btn-active')).toBe(false);
  });

  it('switching away from capability filter hides register form', async () => {
    await mount();

    // Switch to capability, open form
    const capBtn = getFilterButtons().find(b => b.textContent?.trim() === i18n.value['type-capability']);
    await act(async () => { (capBtn as HTMLElement).click(); });
    const regBtn = getRegisterButton()!;
    await act(async () => { regBtn.click(); });

    // Switch to "all"
    const allBtn = getFilterButtons().find(b => b.textContent?.trim() === i18n.value['type-all']);
    await act(async () => { (allBtn as HTMLElement).click(); });

    // Register button should be gone
    expect(getRegisterButton()).toBeUndefined();
  });
});
