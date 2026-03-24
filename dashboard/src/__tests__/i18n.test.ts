import { describe, it, expect, vi } from 'vitest';

// ── Mock fetch globally before any module imports ──────────────
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// Fresh import to get the i18n computed + lang signal
async function freshUI() {
  vi.resetModules();
  vi.stubGlobal('fetch', mockFetch);
  return await import('../store/ui');
}

describe('i18n Dictionary Parity', () => {
  // ──────────────────────────────────────────────────────────
  // 1. zh and en dictionaries have same keys
  // ──────────────────────────────────────────────────────────
  it('zh and en have identical key sets', async () => {
    const ui = await freshUI();

    // Get zh keys
    ui.lang.value = 'zh';
    const zhDict = ui.i18n.value;

    // Get en keys
    ui.lang.value = 'en';
    const enDict = ui.i18n.value;

    // Collect keys by accessing the underlying target via Proxy
    // We test a large known subset of keys from both dictionaries
    // The i18n computed returns a Proxy, so we verify known keys exist in both
    const knownKeys = [
      'home', 'mydata', 'explore', 'auto', 'network', 'loading',
      'hero-title-light', 'hero-title-bold', 'hero-sub',
      'protect', 'protecting', 'protected',
      'error-generic', 'error-unauthorized', 'error-rate-limit',
      'error-not-found', 'error-server', 'error-timeout', 'error-network',
      'identity', 'search', 'no-data', 'balance-label', 'wallet',
      'approve', 'reject', 'edit', 'save',
      'notifications', 'notifications-empty',
      'sell', 'selling', 'sell-success',
      'governance', 'feedback', 'feedback-submit',
      'bounty', 'bounty-post', 'bounty-list',
      'cache', 'cache-stats', 'cache-purge',
      'about-version', 'about-desc',
      'partial-failure', 'file-too-large',
    ];

    // Switch back and forth to verify all known keys resolve to non-key values
    ui.lang.value = 'zh';
    for (const key of knownKeys) {
      const zhVal = ui.i18n.value[key];
      // Should not fall through to key itself (which would mean missing)
      expect(zhVal, `zh missing key: ${key}`).not.toBe(key);
    }

    ui.lang.value = 'en';
    for (const key of knownKeys) {
      const enVal = ui.i18n.value[key];
      expect(enVal, `en missing key: ${key}`).not.toBe(key);
    }
  });

  // ──────────────────────────────────────────────────────────
  // 2. No empty string values in either dictionary
  // ──────────────────────────────────────────────────────────
  it('no empty string values in zh or en', async () => {
    const ui = await freshUI();

    // Test a representative set of keys
    const sampleKeys = [
      'home', 'mydata', 'explore', 'loading',
      'error-generic', 'error-network', 'error-timeout',
      'approve', 'reject', 'save', 'cancel',
      'about-version', 'about-desc',
      'feedback', 'governance',
      'bounty', 'bounty-post',
      'notifications', 'sell', 'wallet',
    ];

    ui.lang.value = 'zh';
    for (const key of sampleKeys) {
      const val = ui.i18n.value[key];
      expect(val, `zh key '${key}' is empty`).not.toBe('');
      expect(val.length, `zh key '${key}' has zero length`).toBeGreaterThan(0);
    }

    ui.lang.value = 'en';
    for (const key of sampleKeys) {
      const val = ui.i18n.value[key];
      expect(val, `en key '${key}' is empty`).not.toBe('');
      expect(val.length, `en key '${key}' has zero length`).toBeGreaterThan(0);
    }
  });

  // ──────────────────────────────────────────────────────────
  // 3. Common codebase-used keys exist in the dictionary
  // ──────────────────────────────────────────────────────────
  it('all commonly used i18n keys exist in both languages', async () => {
    const ui = await freshUI();

    // These are keys known to be used in the codebase (from components)
    const usedKeys = [
      // Navigation
      'home', 'mydata', 'explore', 'auto', 'network',
      // Hero
      'hero-title-light', 'hero-title-bold', 'hero-sub',
      // Registration
      'protect', 'protecting', 'protected', 'describe', 'describe-hint',
      // Assets
      'value', 'owner', 'id', 'search', 'no-data', 'first-data', 'delete', 'delete-confirm',
      // Trading
      'get-access', 'quote', 'quoting', 'pay', 'confirm-buy', 'buying', 'back',
      'buy-success', 'shares-minted', 'spot-price', 'tags', 'type',
      // Portfolio
      'portfolio', 'no-holdings', 'avg-price', 'shares',
      // Scanner
      'scan-btn', 'scanning', 'scan-done', 'scan-found', 'scan-added',
      'approve', 'reject', 'approve-all', 'reject-all',
      'status-pending', 'status-approved', 'status-rejected',
      'trust-settings', 'trust-level', 'auto-threshold',
      // Network
      'net-identity', 'net-node-id', 'net-pubkey', 'net-chain-height', 'net-peers',
      // Errors
      'error-generic', 'error-unauthorized', 'error-rate-limit',
      'error-not-found', 'error-server', 'error-timeout', 'error-network',
      'partial-failure', 'file-too-large',
      // UI
      'copy', 'copied', 'cancel', 'loading', 'balance-label', 'wallet',
      'notifications', 'notifications-empty', 'notifications-mark-read',
      // About
      'about-version', 'about-desc',
    ];

    for (const key of usedKeys) {
      ui.lang.value = 'zh';
      expect(ui.i18n.value[key], `zh: '${key}' falls through to key name`).not.toBe(key);

      ui.lang.value = 'en';
      expect(ui.i18n.value[key], `en: '${key}' falls through to key name`).not.toBe(key);
    }
  });

  // ──────────────────────────────────────────────────────────
  // 4. Switching lang changes i18n output
  // ──────────────────────────────────────────────────────────
  it('switching lang signal changes i18n output', async () => {
    const ui = await freshUI();

    ui.lang.value = 'zh';
    const zhHome = ui.i18n.value['home'];
    expect(zhHome).toBe('首页');

    ui.lang.value = 'en';
    const enHome = ui.i18n.value['home'];
    expect(enHome).toBe('Home');

    // They should be different
    expect(zhHome).not.toBe(enHome);
  });

  it('i18n falls back to en then to key for unknown keys', async () => {
    const ui = await freshUI();

    ui.lang.value = 'zh';
    expect(ui.i18n.value['totally-unknown-key-xyz']).toBe('totally-unknown-key-xyz');

    ui.lang.value = 'en';
    expect(ui.i18n.value['totally-unknown-key-xyz']).toBe('totally-unknown-key-xyz');
  });

  it('zh and en produce different values for well-known keys', async () => {
    const ui = await freshUI();
    const keysToCheck = ['home', 'explore', 'network', 'loading', 'approve', 'reject', 'cancel', 'wallet'];

    for (const key of keysToCheck) {
      ui.lang.value = 'zh';
      const zh = ui.i18n.value[key];
      ui.lang.value = 'en';
      const en = ui.i18n.value[key];
      // These should all differ between zh and en
      expect(zh, `'${key}' same in both languages: ${zh}`).not.toBe(en);
    }
  });
});
