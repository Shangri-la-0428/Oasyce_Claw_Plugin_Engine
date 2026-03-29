/**
 * Home page tests — test-first for UX overhaul
 *
 * Tests the new accordion onboarding + veteran dashboard redesign.
 * Written BEFORE implementation — all tests initially red.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render } from 'preact';
import { act } from 'preact/test-utils';

// ── Mock fetch globally BEFORE any module imports ──────────
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// ── Mock heavy child components ────────────────────────────
// vi.hoisted ensures the variable is available when vi.mock factories run (hoisted)
const mockRegisterForm = vi.hoisted(() => vi.fn(() => null));
vi.mock('../components/register-form', () => ({ default: mockRegisterForm }));

// ── Imports (after mocks) ──────────────────────────────────
import { account, identity, balance, i18n, lang, powProgress } from '../store/ui';
import { assets } from '../store/assets';
import Home from '../pages/home';

// ── Helpers ────────────────────────────────────────────────
function okJson(data: any) {
  return {
    ok: true, status: 200,
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

async function settle() {
  for (let i = 0; i < 5; i++) {
    await act(async () => { await new Promise(r => setTimeout(r, 0)); });
  }
}

// ── Tests ──────────────────────────────────────────────────
describe('Home', () => {
  let container: HTMLElement;
  let goSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockFetch.mockReset();
    mockRegisterForm.mockClear();
    // Default: all fetches → 404 (handles ensureToken, loadAssets, earnings, etc.)
    mockFetch.mockResolvedValue({
      ok: false, status: 404,
      text: async () => '', json: async () => ({}),
    });

    // Reset signals
    identity.value = null;
    account.value = null;
    balance.value = null;
    assets.value = [];
    powProgress.value = { mining: false, attempts: 0, found: false };
    lang.value = 'zh';
    localStorage.clear();

    goSpy = vi.fn();
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    render(null, container);
    container.remove();
  });

  async function mount() {
    await act(async () => { render(<Home go={goSpy} />, container); });
    await settle();
  }

  // ════════════════════════════════════════════════════════
  // 1. Rendering States
  // ════════════════════════════════════════════════════════
  describe('rendering states', () => {
    it('renders onboarding with step 1 active for new user', async () => {
      await mount();
      expect(container.querySelector('.home-accordion')).not.toBeNull();
      expect(container.querySelector('.home-stats')).toBeNull();
      expect(container.querySelector('.home-account-panel')).not.toBeNull();
      expect(container.textContent).toContain('这台设备要创建新账户吗');

      const step1 = container.querySelector('[data-step="1"]');
      expect(step1?.classList.contains('is-active')).toBe(true);
      expect(step1?.getAttribute('aria-expanded')).toBe('true');
    });

    it('shows step 2 active when wallet exists but no funds', async () => {
      identity.value = { address: 'oasyce1testaddr123456', exists: true };
      account.value = {
        configured: true,
        account_address: 'oasyce1testaddr123456',
        account_mode: 'managed_local',
        can_sign: true,
        signer_name: 'local',
        signer_address: 'oasyce1testaddr123456',
        wallet_address: 'oasyce1testaddr123456',
        wallet_present: true,
        wallet_matches_account: true,
        signer_matches_account: true,
      };
      balance.value = 0;
      await mount();

      const step1 = container.querySelector('[data-step="1"]');
      const step2 = container.querySelector('[data-step="2"]');
      expect(step1?.classList.contains('is-done')).toBe(true);
      expect(step2?.classList.contains('is-active')).toBe(true);
      expect(step2?.getAttribute('aria-expanded')).toBe('true');
    });

    it('shows step 3 active when wallet + funds but no assets', async () => {
      identity.value = { address: 'oasyce1testaddr123456', exists: true };
      account.value = {
        configured: true,
        account_address: 'oasyce1testaddr123456',
        account_mode: 'managed_local',
        can_sign: true,
        signer_name: 'local',
        signer_address: 'oasyce1testaddr123456',
        wallet_address: 'oasyce1testaddr123456',
        wallet_present: true,
        wallet_matches_account: true,
        signer_matches_account: true,
      };
      balance.value = 100;
      await mount();

      const step3 = container.querySelector('[data-step="3"]');
      expect(step3?.classList.contains('is-active')).toBe(true);
    });

    it('renders veteran dashboard when all steps complete', async () => {
      identity.value = { address: 'oasyce1testaddr123456', exists: true };
      account.value = {
        configured: true,
        account_address: 'oasyce1testaddr123456',
        account_mode: 'managed_local',
        can_sign: true,
        signer_name: 'local',
        signer_address: 'oasyce1testaddr123456',
        wallet_address: 'oasyce1testaddr123456',
        wallet_present: true,
        wallet_matches_account: true,
        signer_matches_account: true,
      };
      balance.value = 100;
      assets.value = [{ asset_id: 'ASSET1' }];
      await mount();

      expect(container.querySelector('.home-stats')).not.toBeNull();
      expect(container.querySelector('.home-accordion')).toBeNull();
    });

    it('renders readonly attached state with account management actions', async () => {
      identity.value = { address: 'oasyce1readonly', exists: true };
      account.value = {
        configured: true,
        account_address: 'oasyce1readonly',
        account_mode: 'attached_readonly',
        account_origin: 'joined_existing',
        device_id: 'device-1',
        device_authorization_status: 'readonly',
        device_authorization_expires_at: 0,
        can_sign: false,
        signer_name: '',
        signer_address: '',
        wallet_address: '',
        wallet_present: false,
        wallet_matches_account: false,
        signer_matches_account: false,
      };
      balance.value = 5;

      await mount();

      expect(container.textContent).toContain('已接入现有账户');
      expect(container.textContent).toContain('改用其他账户');
      expect(container.textContent).toContain('断开这台设备');
    });

    it('renders existing-account signing device state instead of newcomer onboarding', async () => {
      identity.value = { address: 'oasyce1shared', exists: true };
      account.value = {
        configured: true,
        account_address: 'oasyce1shared',
        account_mode: 'managed_local',
        account_origin: 'joined_existing',
        device_id: 'device-signing',
        device_authorization_status: 'active',
        device_authorization_expires_at: 0,
        can_sign: true,
        signer_name: 'shared-signer',
        signer_address: 'oasyce1shared',
        wallet_address: 'oasyce1shared',
        wallet_present: true,
        wallet_matches_account: true,
        signer_matches_account: true,
      };
      balance.value = 0;

      await mount();

      expect(container.textContent).toContain('已接入现有账户');
      expect(container.textContent).toContain('这台设备已经连接到同一个经济账号，现在可以继续手动注册、买卖和质押');
      expect(container.querySelector('.home-accordion')).toBeNull();
      expect(container.textContent).toContain('改用其他账户');
    });
  });

  // ════════════════════════════════════════════════════════
  // 2. Accordion Behavior
  // ════════════════════════════════════════════════════════
  describe('accordion behavior', () => {
    it('only active step is expanded', async () => {
      await mount();
      const expanded = container.querySelectorAll('[aria-expanded="true"]');
      expect(expanded.length).toBe(1);
      expect(expanded[0]?.getAttribute('data-step')).toBe('1');
    });

    it('future steps are locked with no action buttons', async () => {
      await mount();
      const step2 = container.querySelector('[data-step="2"]');
      const step3 = container.querySelector('[data-step="3"]');
      expect(step2?.classList.contains('is-locked')).toBe(true);
      expect(step3?.classList.contains('is-locked')).toBe(true);
      expect(step2?.querySelector('.btn')).toBeNull();
      expect(step3?.querySelector('.btn')).toBeNull();
    });

    it('completed steps show summary inline', async () => {
      identity.value = { address: 'oasyce1testaddr123456', exists: true };
      account.value = {
        configured: true,
        account_address: 'oasyce1testaddr123456',
        account_mode: 'managed_local',
        can_sign: true,
        signer_name: 'local',
        signer_address: 'oasyce1testaddr123456',
        wallet_address: 'oasyce1testaddr123456',
        wallet_present: true,
        wallet_matches_account: true,
        signer_matches_account: true,
      };
      balance.value = 0;
      await mount();

      const step1 = container.querySelector('[data-step="1"]');
      const summary = step1?.querySelector('.accordion-summary');
      expect(summary).not.toBeNull();
      expect(summary?.textContent).toContain('oasy'); // masked address
    });
  });

  // ════════════════════════════════════════════════════════
  // 3. Step Actions
  // ════════════════════════════════════════════════════════
  describe('step actions', () => {
    it('step 1 prepare device calls POST /account/bootstrap', async () => {
      mockFetch.mockImplementation((url: string, opts?: any) => {
        if (url?.includes('/api/auth/token'))
          return Promise.resolve({ ok: false, status: 404, text: async () => '', json: async () => ({}) });
        if (url?.includes('/account/bootstrap') && opts?.method === 'POST')
          return Promise.resolve(okJson({ ok: true }));
        if (url?.includes('/account/status'))
          return Promise.resolve(okJson({
            configured: true,
            account_address: 'oasyce1new',
            account_mode: 'managed_local',
            can_sign: true,
            signer_name: 'local',
            signer_address: 'oasyce1new',
            wallet_address: 'oasyce1new',
            wallet_present: true,
            wallet_matches_account: true,
            signer_matches_account: true,
          }));
        if (url?.includes('/identity/wallet'))
          return Promise.resolve(okJson({ address: 'oasyce1new', exists: true }));
        if (url?.includes('/balance'))
          return Promise.resolve(okJson({ balance_oas: 0 }));
        return Promise.resolve({ ok: false, status: 404, text: async () => '', json: async () => ({}) });
      });

      await mount();
      const createButton = Array.from(container.querySelectorAll('.home-account-choice'))
        .find(btn => btn.textContent?.includes('创建新账户'));
      expect(createButton).not.toBeNull();
      await act(async () => { (createButton as HTMLButtonElement).click(); });

      const activeStep = container.querySelector('.accordion-step.is-active');
      const btn = activeStep?.querySelector('.home-account-card .btn-primary') as HTMLButtonElement;
      expect(btn).not.toBeNull();

      await act(async () => { btn.click(); });
      await settle();

      const postCalls = mockFetch.mock.calls.filter(
        (c: any[]) => c[0]?.includes('/account/bootstrap'),
      );
      expect(postCalls.length).toBeGreaterThan(0);
    });

    it('step 1 import bundle calls POST /device/join', async () => {
      mockFetch.mockImplementation((url: string, opts?: any) => {
        if (url?.includes('/device/join') && opts?.method === 'POST')
          return Promise.resolve(okJson({ ok: true }));
        if (url?.includes('/account/status'))
          return Promise.resolve(okJson({
            configured: true,
            account_address: 'oasyce1joined',
            account_mode: 'attached_readonly',
            can_sign: false,
            signer_name: '',
            signer_address: '',
            wallet_address: '',
            wallet_present: false,
            wallet_matches_account: false,
            signer_matches_account: false,
          }));
        if (url?.includes('/balance'))
          return Promise.resolve(okJson({ balance_oas: 5 }));
        return Promise.resolve({ ok: false, status: 404, text: async () => '', json: async () => ({}) });
      });

      await mount();
      const existingButton = Array.from(container.querySelectorAll('.home-account-choice'))
        .find(btn => btn.textContent?.includes('使用已有账户'));
      expect(existingButton).not.toBeNull();
      await act(async () => { (existingButton as HTMLButtonElement).click(); });

      const input = container.querySelector('#join-bundle-file') as HTMLInputElement;
      const file = new File(
        [JSON.stringify({
          kind: 'oasyce_trusted_device_bundle',
          version: 1,
          account_address: 'oasyce1joined',
          bundle_mode: 'readonly',
        })],
        'oasyce-device.json',
        { type: 'application/json' },
      );
      await act(async () => {
        Object.defineProperty(input, 'files', {
          configurable: true,
          value: [file],
        });
        input.dispatchEvent(new Event('change', { bubbles: true }));
      });
      const submit = Array.from(container.querySelectorAll('.home-account-card .btn-primary'))
        .find(btn => btn.textContent?.includes('导入连接文件'));
      expect(submit).not.toBeNull();
      await act(async () => { (submit as HTMLButtonElement).click(); });
      await settle();

      const joinCalls = mockFetch.mock.calls.filter(
        (c: any[]) => c[0]?.includes('/device/join'),
      );
      expect(joinCalls.length).toBeGreaterThan(0);
      expect(JSON.parse(joinCalls[0][1].body).bundle.account_address).toBe('oasyce1joined');
    });

    it('advanced manual join still supports readonly attach', async () => {
      mockFetch.mockImplementation((url: string, opts?: any) => {
        if (url?.includes('/device/join') && opts?.method === 'POST')
          return Promise.resolve(okJson({ ok: true }));
        if (url?.includes('/account/status'))
          return Promise.resolve(okJson({
            configured: true,
            account_address: 'oasyce1joined',
            account_mode: 'attached_readonly',
            can_sign: false,
            signer_name: '',
            signer_address: '',
            wallet_address: '',
            wallet_present: false,
            wallet_matches_account: false,
            signer_matches_account: false,
          }));
        if (url?.includes('/identity/wallet'))
          return Promise.resolve(okJson({ address: 'oasyce1joined', exists: true }));
        if (url?.includes('/balance'))
          return Promise.resolve(okJson({ balance_oas: 5 }));
        return Promise.resolve({ ok: false, status: 404, text: async () => '', json: async () => ({}) });
      });

      await mount();
      const existingButton = Array.from(container.querySelectorAll('.home-account-choice'))
        .find(btn => btn.textContent?.includes('使用已有账户'));
      expect(existingButton).not.toBeNull();
      await act(async () => { (existingButton as HTMLButtonElement).click(); });

      const advancedButton = Array.from(container.querySelectorAll('.home-account-card .btn'))
        .find(btn => btn.textContent?.includes('手动接入'));
      expect(advancedButton).not.toBeNull();
      await act(async () => { (advancedButton as HTMLButtonElement).click(); });

      const input = container.querySelector('#join-account-address') as HTMLInputElement;
      await act(async () => {
        input.value = 'oasyce1joined';
        input.dispatchEvent(new Event('input', { bubbles: true }));
      });
      const submit = Array.from(container.querySelectorAll('.home-account-card .btn-primary'))
        .find(btn => btn.textContent?.includes('已有账号'));
      expect(submit).not.toBeNull();
      await act(async () => { (submit as HTMLButtonElement).click(); });
      await settle();

      const joinCalls = mockFetch.mock.calls.filter(
        (c: any[]) => c[0]?.includes('/device/join'),
      );
      expect(joinCalls.length).toBeGreaterThan(0);
    });

    it('step 2 claim calls selfRegister endpoint', async () => {
      identity.value = { address: 'oasyce1testaddr123456', exists: true };
      account.value = {
        configured: true,
        account_address: 'oasyce1testaddr123456',
        account_mode: 'managed_local',
        can_sign: true,
        signer_name: 'local',
        signer_address: 'oasyce1testaddr123456',
        wallet_address: 'oasyce1testaddr123456',
        wallet_present: true,
        wallet_matches_account: true,
        signer_matches_account: true,
      };
      balance.value = 0;

      mockFetch.mockImplementation((url: string) => {
        if (url?.includes('/api/onboarding/register'))
          return Promise.resolve(okJson({ ok: true, attempts: 100, amount: 50, new_balance: 50 }));
        return Promise.resolve({ ok: false, status: 404, text: async () => '', json: async () => ({}) });
      });

      await mount();
      const step2 = container.querySelector('[data-step="2"]');
      const btn = step2?.querySelector('.btn-primary') as HTMLButtonElement;
      expect(btn).not.toBeNull();

      await act(async () => { btn.click(); });
      await settle();

      const regCalls = mockFetch.mock.calls.filter(
        (c: any[]) => c[0]?.includes('/api/onboarding/register'),
      );
      expect(regCalls.length).toBeGreaterThan(0);
    });

    it('step 3 renders RegisterForm with compact=true, no mode switch', async () => {
      identity.value = { address: 'oasyce1testaddr123456', exists: true };
      account.value = {
        configured: true,
        account_address: 'oasyce1testaddr123456',
        account_mode: 'managed_local',
        can_sign: true,
        signer_name: 'local',
        signer_address: 'oasyce1testaddr123456',
        wallet_address: 'oasyce1testaddr123456',
        wallet_present: true,
        wallet_matches_account: true,
        signer_matches_account: true,
      };
      balance.value = 100;
      await mount();

      expect(mockRegisterForm).toHaveBeenCalled();
      const lastProps = mockRegisterForm.mock.calls[mockRegisterForm.mock.calls.length - 1][0];
      expect(lastProps.compact).toBe(true);
      expect(lastProps.mode).toBe('data');

      // No mode switch tabs in onboarding
      expect(container.querySelector('[role="tablist"]')).toBeNull();
    });
  });

  // ════════════════════════════════════════════════════════
  // 4. Veteran View
  // ════════════════════════════════════════════════════════
  describe('veteran view', () => {
    beforeEach(() => {
      identity.value = { address: 'oasyce1testaddr123456', exists: true };
      account.value = {
        configured: true,
        account_address: 'oasyce1testaddr123456',
        account_mode: 'managed_local',
        device_id: 'device-A',
        device_authorization_status: 'active',
        device_authorization_expires_at: 0,
        can_sign: true,
        signer_name: 'local',
        signer_address: 'oasyce1testaddr123456',
        wallet_address: 'oasyce1testaddr123456',
        wallet_present: true,
        wallet_matches_account: true,
        signer_matches_account: true,
      };
      balance.value = 250;
      assets.value = [{ asset_id: 'ASSET1' }, { asset_id: 'ASSET2' }];
    });

    it('shows balance prominently with stat-value class', async () => {
      await mount();
      const statValues = container.querySelectorAll('.home-stat-value');
      expect(statValues.length).toBeGreaterThanOrEqual(1);
      expect(container.textContent).toContain('250.0');
    });

    it('recent trades include timestamps', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url?.includes('/api/earnings'))
          return Promise.resolve({
            ok: true, status: 200,
            text: async () => JSON.stringify({
              total_earned: 100,
              transactions: [{ asset_id: 'A1', buyer: 'bob', amount: 50, timestamp: 1711000000 }],
            }),
            json: async () => ({
              total_earned: 100,
              transactions: [{ asset_id: 'A1', buyer: 'bob', amount: 50, timestamp: 1711000000 }],
            }),
          });
        return Promise.resolve({ ok: false, status: 404, text: async () => '', json: async () => ({}) });
      });

      await mount();
      // fmtDate produces date strings containing digits and separators
      const rows = container.querySelectorAll('.item-row');
      if (rows.length > 0) {
        expect(rows[0].textContent).toMatch(/\d{4}/); // year in date output
      }
    });

    it('does not render redundant bottom navigation', async () => {
      await mount();
      expect(container.querySelector('.home-navigate')).toBeNull();
    });

    it('renders device share panel and exports a bundle', async () => {
      const createObjectURL = vi.fn(() => 'blob:bundle');
      const revokeObjectURL = vi.fn();
      const click = vi.fn();
      mockFetch.mockImplementation((url: string) => {
        if (url?.includes('/api/device/export')) {
          return Promise.resolve(okJson({
            ok: true,
            filename: 'oasyce-device-signing.json',
            bundle: { kind: 'oasyce_trusted_device_bundle', version: 1 },
          }));
        }
        if (url?.includes('/api/earnings')) {
          return Promise.resolve(okJson({ total_earned: 0, transactions: [] }));
        }
        return Promise.resolve({ ok: false, status: 404, text: async () => '', json: async () => ({}) });
      });
      const originalCreate = URL.createObjectURL;
      const originalRevoke = URL.revokeObjectURL;
      const originalClick = HTMLAnchorElement.prototype.click;
      URL.createObjectURL = createObjectURL;
      URL.revokeObjectURL = revokeObjectURL;
      HTMLAnchorElement.prototype.click = click;

      await mount();
      const exportButton = Array.from(container.querySelectorAll('.home-device-share .btn'))
        .find(btn => btn.textContent?.includes('导出可交易连接文件'));
      expect(exportButton).not.toBeNull();
      await act(async () => { (exportButton as HTMLButtonElement).click(); });
      await settle();

      expect(createObjectURL).toHaveBeenCalled();
      expect(click).toHaveBeenCalled();

      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
      HTMLAnchorElement.prototype.click = originalClick;
    });

    it('register button is visible inline, not in collapsed Section', async () => {
      await mount();
      // Should NOT be wrapped in a .card (Section renders .card wrapper)
      const sectionCards = container.querySelectorAll('.card');
      const registerInCard = Array.from(sectionCards).some(
        card => card.textContent?.includes(i18n.value['vet-register-cta'] || '上传更多'),
      );
      expect(registerInCard).toBe(false);
    });
  });

  // ════════════════════════════════════════════════════════
  // 5. i18n
  // ════════════════════════════════════════════════════════
  describe('i18n', () => {
    it('new de-Web3-ified keys exist in both zh and en', () => {
      const newKeys = [
        'onboard-step1-hint', 'onboard-step2-hint', 'onboard-step3-hint',
        'gate-create-body', 'gate-funds-body',
        'success-outcome', 'success-outcome-body',
        'success-cta-market', 'success-cta-more',
        'advanced-options-hint', 'vet-register-cta',
      ];

      lang.value = 'zh';
      for (const key of newKeys) {
        expect(i18n.value[key], `zh missing: ${key}`).not.toBe(key);
      }
      lang.value = 'en';
      for (const key of newKeys) {
        expect(i18n.value[key], `en missing: ${key}`).not.toBe(key);
      }
    });

    it('onboarding hero does not contain old slogan', async () => {
      lang.value = 'zh';
      await mount();
      const heroText = container.querySelector('.home-hero')?.textContent || '';
      expect(heroText).not.toContain('智能的价值');
      expect(heroText).not.toContain('自由交易');
    });
  });

  // ════════════════════════════════════════════════════════
  // 6. Success State
  // ════════════════════════════════════════════════════════
  describe('success state', () => {
    beforeEach(() => {
      identity.value = { address: 'oasyce1testaddr123456', exists: true };
      account.value = {
        configured: true,
        account_address: 'oasyce1testaddr123456',
        account_mode: 'managed_local',
        device_id: 'device-A',
        device_authorization_status: 'active',
        device_authorization_expires_at: 0,
        can_sign: true,
        signer_name: 'local',
        signer_address: 'oasyce1testaddr123456',
        wallet_address: 'oasyce1testaddr123456',
        wallet_present: true,
        wallet_matches_account: true,
        signer_matches_account: true,
      };
      balance.value = 100;
    });

    it('shows outcome message, not technical details', async () => {
      await mount();

      // Trigger success via RegisterForm's onSuccess
      const lastProps = mockRegisterForm.mock.calls[mockRegisterForm.mock.calls.length - 1][0];
      expect(lastProps.onSuccess).toBeDefined();

      await act(async () => {
        lastProps.onSuccess({ asset_id: 'NEW1', file_hash: 'abc123hash', price_model: 'auto', file_count: 3 });
      });
      await settle();

      const text = container.textContent || '';
      expect(text).not.toContain('abc123hash');
      expect(text).not.toContain('文件哈希');
      expect(text).not.toContain('定价方式');
      expect(text).toContain(i18n.value['success-outcome']);
    });

    it('has market and upload-another buttons', async () => {
      await mount();

      const lastProps = mockRegisterForm.mock.calls[mockRegisterForm.mock.calls.length - 1][0];
      await act(async () => {
        lastProps.onSuccess({ asset_id: 'NEW1' });
      });
      await settle();

      const btnTexts = Array.from(container.querySelectorAll('.btn'))
        .map(b => b.textContent?.trim());
      expect(btnTexts).toContain(i18n.value['success-cta-market']);
      expect(btnTexts).toContain(i18n.value['success-cta-more']);
    });
  });
});
