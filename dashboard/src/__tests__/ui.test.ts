import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ── Mock fetch globally before any module imports ──────────────
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// Helper responses
function okJson(data: any) {
  return { ok: true, status: 200, json: async () => data, text: async () => JSON.stringify(data) };
}
function failRes(status = 500) {
  return { ok: false, status, json: async () => ({}), text: async () => '' };
}

// ── Fresh module import helper ─────────────────────────────────
// Each test group re-imports ui.ts to get fresh signal state.
// The module uses raw `fetch` (not the api client), so we only need
// to handle fetch calls from ui.ts itself.
async function freshUI() {
  // Reset module registry so signals start at default values
  vi.resetModules();
  // Re-stub fetch on the fresh global (resetModules clears stubs)
  vi.stubGlobal('fetch', mockFetch);
  return await import('../store/ui');
}

describe('UI Store', () => {
  beforeEach(() => {
    mockFetch.mockReset();
    localStorage.clear();
    document.documentElement.removeAttribute('data-theme');
  });

  // ────────────────────────────────────────────────────────────
  // 1. theme — toggleTheme
  // ────────────────────────────────────────────────────────────
  describe('toggleTheme', () => {
    it('switches dark to light and back', async () => {
      const ui = await freshUI();
      // Default is 'dark'
      expect(ui.theme.value).toBe('dark');

      ui.toggleTheme();
      expect(ui.theme.value).toBe('light');
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
      expect(localStorage.getItem('oasyce-theme')).toBe('light');

      ui.toggleTheme();
      expect(ui.theme.value).toBe('dark');
      expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
      expect(localStorage.getItem('oasyce-theme')).toBe('dark');
    });
  });

  // ────────────────────────────────────────────────────────────
  // 2. lang — toggleLang
  // ────────────────────────────────────────────────────────────
  describe('toggleLang', () => {
    it('switches zh to en and back, persists to localStorage', async () => {
      const ui = await freshUI();
      expect(ui.lang.value).toBe('zh');

      ui.toggleLang();
      expect(ui.lang.value).toBe('en');
      expect(localStorage.getItem('oasyce-lang')).toBe('en');

      ui.toggleLang();
      expect(ui.lang.value).toBe('zh');
      expect(localStorage.getItem('oasyce-lang')).toBe('zh');
    });
  });

  // ────────────────────────────────────────────────────────────
  // 3. initUI — loads from localStorage, system-preference fallback
  // ────────────────────────────────────────────────────────────
  describe('initUI', () => {
    it('loads saved theme and lang from localStorage', async () => {
      localStorage.setItem('oasyce-theme', 'light');
      localStorage.setItem('oasyce-lang', 'en');

      // loadIdentity will fire fetch — provide a response
      mockFetch.mockResolvedValue(failRes());

      const ui = await freshUI();
      ui.initUI();

      expect(ui.theme.value).toBe('light');
      expect(ui.lang.value).toBe('en');
      expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    });

    it('falls back to system preference when nothing saved', async () => {
      // matchMedia returns dark
      Object.defineProperty(window, 'matchMedia', {
        writable: true,
        value: vi.fn().mockImplementation((query: string) => ({
          matches: query === '(prefers-color-scheme: dark)',
          media: query,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        })),
      });
      // navigator.language → en (not zh)
      Object.defineProperty(navigator, 'language', { writable: true, value: 'en-US', configurable: true });

      mockFetch.mockResolvedValue(failRes());

      const ui = await freshUI();
      ui.initUI();

      expect(ui.theme.value).toBe('dark');
      expect(ui.lang.value).toBe('en');
    });

    it('falls back to zh when navigator.language starts with zh', async () => {
      Object.defineProperty(navigator, 'language', { writable: true, value: 'zh-CN', configurable: true });
      mockFetch.mockResolvedValue(failRes());

      const ui = await freshUI();
      ui.initUI();

      expect(ui.lang.value).toBe('zh');
    });
  });

  // ────────────────────────────────────────────────────────────
  // 4. showToast — adds toast, resolves i18n keys, auto-dismisses
  // ────────────────────────────────────────────────────────────
  describe('showToast', () => {
    beforeEach(() => { vi.useFakeTimers(); });
    afterEach(() => { vi.useRealTimers(); });

    it('adds a toast with unique id and resolves plain message', async () => {
      const ui = await freshUI();
      ui.showToast('hello', 'success');
      expect(ui.toasts.value).toHaveLength(1);
      expect(ui.toasts.value[0].message).toBe('hello');
      expect(ui.toasts.value[0].type).toBe('success');
      expect(ui.toasts.value[0].id).toBeTruthy();
    });

    it('resolves known i18n error key to localized string', async () => {
      const ui = await freshUI();
      // lang defaults to 'zh', so error-generic should resolve
      ui.showToast('error-generic', 'error');
      expect(ui.toasts.value[0].message).not.toBe('error-generic');
      // It should be the zh translation
      expect(ui.toasts.value[0].message).toContain('操作失败');
    });

    it('defaults type to info', async () => {
      const ui = await freshUI();
      ui.showToast('test');
      expect(ui.toasts.value[0].type).toBe('info');
    });

    it('auto-dismisses after 3 seconds', async () => {
      const ui = await freshUI();
      ui.showToast('vanish');
      expect(ui.toasts.value).toHaveLength(1);

      vi.advanceTimersByTime(2999);
      expect(ui.toasts.value).toHaveLength(1);

      vi.advanceTimersByTime(1);
      expect(ui.toasts.value).toHaveLength(0);
    });

    it('can show multiple toasts and dismiss individually', async () => {
      const ui = await freshUI();
      ui.showToast('a');
      vi.advanceTimersByTime(1000);
      ui.showToast('b');
      expect(ui.toasts.value).toHaveLength(2);

      // First toast expires at 3000ms (from its creation at t=0)
      vi.advanceTimersByTime(2000);
      expect(ui.toasts.value).toHaveLength(1);
      expect(ui.toasts.value[0].message).toBe('b');

      // Second toast expires at 4000ms (created at t=1000)
      vi.advanceTimersByTime(1000);
      expect(ui.toasts.value).toHaveLength(0);
    });
  });

  // ────────────────────────────────────────────────────────────
  // 5. loadIdentity
  // ────────────────────────────────────────────────────────────
  describe('loadIdentity', () => {
    it('sets identity on success', async () => {
      const ui = await freshUI();
      mockFetch.mockResolvedValueOnce(okJson({ address: 'oasyce1abc', exists: true }));

      await ui.loadIdentity();
      expect(ui.identity.value).toEqual({ address: 'oasyce1abc', exists: true });
    });

    it('leaves identity null on network error', async () => {
      const ui = await freshUI();
      mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

      await ui.loadIdentity();
      expect(ui.identity.value).toBeNull();
    });

    it('leaves identity null on non-ok response', async () => {
      const ui = await freshUI();
      mockFetch.mockResolvedValueOnce(failRes(500));

      await ui.loadIdentity();
      expect(ui.identity.value).toBeNull();
    });
  });

  // ────────────────────────────────────────────────────────────
  // 6. walletAddress
  // ────────────────────────────────────────────────────────────
  describe('walletAddress', () => {
    it('returns address when identity exists', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1xyz', exists: true };
      expect(ui.walletAddress()).toBe('oasyce1xyz');
    });

    it('returns anonymous when identity is null', async () => {
      const ui = await freshUI();
      expect(ui.walletAddress()).toBe('anonymous');
    });

    it('returns anonymous when exists is false', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1xyz', exists: false };
      expect(ui.walletAddress()).toBe('anonymous');
    });
  });

  // ────────────────────────────────────────────────────────────
  // 7. loadBalance
  // ────────────────────────────────────────────────────────────
  describe('loadBalance', () => {
    it('sets balance on success', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1abc', exists: true };
      mockFetch.mockResolvedValueOnce(okJson({ balance_oas: 42.5 }));

      await ui.loadBalance();
      expect(ui.balance.value).toBe(42.5);
    });

    it('sets balance to 0 when anonymous', async () => {
      const ui = await freshUI();
      // identity is null → walletAddress() === 'anonymous'
      await ui.loadBalance();
      expect(ui.balance.value).toBe(0);
      // No fetch should have been called
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('leaves balance unchanged on fetch error', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1abc', exists: true };
      ui.balance.value = 10;
      mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

      await ui.loadBalance();
      // balance stays at 10 since the catch block doesn't modify it
      expect(ui.balance.value).toBe(10);
    });
  });

  // ────────────────────────────────────────────────────────────
  // 8. selfRegister
  // ────────────────────────────────────────────────────────────
  describe('selfRegister', () => {
    it('returns error when anonymous', async () => {
      const ui = await freshUI();
      const result = await ui.selfRegister();
      expect(result.ok).toBe(false);
      expect(result.error).toBe('no wallet');
    });

    it('updates powProgress and balance on success', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1abc', exists: true };
      mockFetch.mockResolvedValueOnce(okJson({ ok: true, attempts: 1234, amount: 100, new_balance: 200 }));

      const result = await ui.selfRegister();

      expect(result.ok).toBe(true);
      expect(result.amount).toBe(100);
      expect(ui.powProgress.value).toEqual({ mining: false, attempts: 1234, found: true });
      expect(ui.balance.value).toBe(200);
    });

    it('sets mining=true during the call', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1abc', exists: true };

      // Capture progress during fetch
      let progressDuringFetch: any = null;
      mockFetch.mockImplementationOnce(() => {
        progressDuringFetch = { ...ui.powProgress.value };
        return Promise.resolve(okJson({ ok: true, attempts: 1, amount: 50, new_balance: 50 }));
      });

      await ui.selfRegister();
      expect(progressDuringFetch).toEqual({ mining: true, attempts: 0, found: false });
    });

    it('resets powProgress on network error', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1abc', exists: true };
      mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

      const result = await ui.selfRegister();

      expect(result.ok).toBe(false);
      expect(result.error).toBe('network error');
      expect(ui.powProgress.value).toEqual({ mining: false, attempts: 0, found: false });
    });

    it('handles server rejection (ok=false in body)', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1abc', exists: true };
      mockFetch.mockResolvedValueOnce(okJson({ ok: false, error: 'already registered', attempts: 5 }));

      const result = await ui.selfRegister();
      expect(result.ok).toBe(false);
      expect(result.error).toBe('already registered');
      expect(ui.powProgress.value.found).toBe(false);
    });
  });

  // ────────────────────────────────────────────────────────────
  // 9. loadNotifications
  // ────────────────────────────────────────────────────────────
  describe('loadNotifications', () => {
    it('sets notifications and unreadCount on success', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1abc', exists: true };

      const mockNotifs = [
        { id: 'n1', event_type: 'buy', message: 'bought', data: {}, read: false, created_at: 1000 },
        { id: 'n2', event_type: 'sell', message: 'sold', data: {}, read: true, created_at: 2000 },
      ];
      // First call: /api/notifications
      mockFetch.mockResolvedValueOnce(okJson({ notifications: mockNotifs }));
      // Second call: /api/notifications/count
      mockFetch.mockResolvedValueOnce(okJson({ unread_count: 1 }));

      await ui.loadNotifications();

      expect(ui.notifications.value).toHaveLength(2);
      expect(ui.notifications.value[0].id).toBe('n1');
      expect(ui.unreadCount.value).toBe(1);
    });

    it('resets to empty when anonymous', async () => {
      const ui = await freshUI();
      // Set some pre-existing data
      ui.notifications.value = [{ id: 'x', event_type: '', message: '', data: {}, read: false, created_at: 0 }];
      ui.unreadCount.value = 5;

      await ui.loadNotifications();

      expect(ui.notifications.value).toEqual([]);
      expect(ui.unreadCount.value).toBe(0);
      expect(mockFetch).not.toHaveBeenCalled();
    });
  });

  // ────────────────────────────────────────────────────────────
  // 10. markNotificationsRead
  // ────────────────────────────────────────────────────────────
  describe('markNotificationsRead', () => {
    it('marks single notification as read', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1abc', exists: true };
      ui.notifications.value = [
        { id: 'n1', event_type: 'buy', message: 'bought', data: {}, read: false, created_at: 1000 },
        { id: 'n2', event_type: 'sell', message: 'sold', data: {}, read: false, created_at: 2000 },
      ];
      ui.unreadCount.value = 2;

      mockFetch.mockResolvedValueOnce(okJson({ ok: true }));

      await ui.markNotificationsRead('n1');

      expect(ui.notifications.value[0].read).toBe(true);
      expect(ui.notifications.value[1].read).toBe(false);
      expect(ui.unreadCount.value).toBe(1);
    });

    it('marks all notifications as read when no id given', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1abc', exists: true };
      ui.notifications.value = [
        { id: 'n1', event_type: 'buy', message: 'bought', data: {}, read: false, created_at: 1000 },
        { id: 'n2', event_type: 'sell', message: 'sold', data: {}, read: false, created_at: 2000 },
      ];
      ui.unreadCount.value = 2;

      mockFetch.mockResolvedValueOnce(okJson({ ok: true }));

      await ui.markNotificationsRead();

      expect(ui.notifications.value.every(n => n.read)).toBe(true);
      expect(ui.unreadCount.value).toBe(0);
    });

    it('does nothing on server failure', async () => {
      const ui = await freshUI();
      ui.identity.value = { address: 'oasyce1abc', exists: true };
      ui.notifications.value = [
        { id: 'n1', event_type: 'buy', message: 'bought', data: {}, read: false, created_at: 1000 },
      ];
      ui.unreadCount.value = 1;

      mockFetch.mockResolvedValueOnce(okJson({ ok: false }));

      await ui.markNotificationsRead('n1');

      // Should not update since server returned ok: false
      expect(ui.notifications.value[0].read).toBe(false);
      expect(ui.unreadCount.value).toBe(1);
    });
  });

  // ────────────────────────────────────────────────────────────
  // 11. i18n — computed signal
  // ────────────────────────────────────────────────────────────
  describe('i18n', () => {
    it('returns zh dictionary by default', async () => {
      const ui = await freshUI();
      expect(ui.lang.value).toBe('zh');
      expect(ui.i18n.value['home']).toBe('首页');
    });

    it('returns en dictionary after toggling lang', async () => {
      const ui = await freshUI();
      ui.toggleLang();
      expect(ui.lang.value).toBe('en');
      expect(ui.i18n.value['home']).toBe('Home');
    });

    it('returns the key itself for unknown keys (fallback)', async () => {
      const ui = await freshUI();
      expect(ui.i18n.value['nonexistent-key-xyz']).toBe('nonexistent-key-xyz');
    });
  });
});
