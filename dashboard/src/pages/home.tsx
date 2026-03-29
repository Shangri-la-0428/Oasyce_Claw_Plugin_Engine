/**
 * Home — launch console
 * Accordion onboarding for new users, flat dashboard for veterans.
 * All strings via i18n — no inline copy object.
 */
import { useEffect, useState, useRef } from 'preact/hooks';
import { get } from '../api/client';
import { assets, loadAssets } from '../store/assets';
import {
  account,
  balance,
  identity,
  i18n,
  loadBalance,
  loadIdentity,
  powProgress,
  selfRegister,
  showToast,
  walletAddress as getWalletAddress,
} from '../store/ui';
import AccountJoinPanel from '../components/account-join-panel';
import DeviceSharePanel from '../components/device-share-panel';
import RegisterForm from '../components/register-form';
import { mask, fmtPrice, maskIdShort, fmtDate } from '../utils';
import type { Page } from '../hooks/use-route';
import './home.css';

interface LaunchResult {
  asset_id?: string;
  file_hash?: string;
  file_count?: number;
  price_model?: string;
  capability?: boolean;
}

interface OwnerEarningsData {
  total_earned: number;
  transactions: { asset_id: string; buyer: string; amount: number; timestamp: number }[];
}

export default function Home({ go }: { go: (p: Page, sub?: string) => void }) {
  const _ = i18n.value;

  const [claiming, setClaiming] = useState(false);
  const [done, setDone] = useState<LaunchResult | null>(null);
  const [ownerEarnings, setOwnerEarnings] = useState<OwnerEarningsData | null>(null);
  const [earningsLoading, setEarningsLoading] = useState(false);

  const successRef = useRef<HTMLHeadingElement>(null);
  const earningsFetched = useRef(false);

  useEffect(() => {
    loadAssets();
  }, []);

  const accountStatus = account.value;
  const walletExists = !!identity.value?.exists;
  const walletAddr = identity.value?.address || '';
  const accountConfigured = !!accountStatus?.configured;
  const accountAddr = accountStatus?.account_address || walletAddr;
  const canSign = !!accountStatus?.can_sign;
  const currentBalance = balance.value ?? 0;
  const hasStarterFunds = currentBalance > 0;
  const assetCount = assets.value.length;
  const isReadonlyAttached = accountConfigured && !canSign && accountStatus?.account_mode === 'attached_readonly';
  const isVeteran = accountConfigured && canSign && hasStarterFunds && assetCount > 0;

  // Load earnings for veteran view
  useEffect(() => {
    if (!isVeteran || earningsFetched.current) return;
    const addr = getWalletAddress();
    if (addr === 'anonymous') return;
    earningsFetched.current = true;
    setEarningsLoading(true);
    get<OwnerEarningsData>(`/earnings?owner=${encodeURIComponent(addr)}`).then(res => {
      if (res.success && res.data && typeof res.data === 'object') setOwnerEarnings(res.data);
    }).catch(() => {}).finally(() => {
      setEarningsLoading(false);
    });
  }, [isVeteran]);

  const currentStep = !accountConfigured ? 1 : !canSign ? 1 : !hasStarterFunds ? 2 : 3;
  const onboardingDone = accountConfigured && canSign && hasStarterFunds && (assetCount > 0 || !!done);

  // ── Actions ──

  async function handleSelfRegister() {
    if (claiming || powProgress.value.mining) return;
    setClaiming(true);
    const res = await selfRegister();
    setClaiming(false);

    if (res.ok) {
      await loadBalance();
      showToast(
        _['register-success'].replace('{amount}', String(res.amount ?? 0)),
        'success',
      );
      return;
    }
    showToast(res.error || _['error-generic'], 'error');
  }

  function handleSuccess(result: LaunchResult) {
    setDone(result);
    loadAssets();
    showToast(_['protected'], 'success');
    requestAnimationFrame(() => successRef.current?.focus());
  }

  function handleAccountReady() {
    loadAssets();
  }

  if (isReadonlyAttached && !done) {
    return (
      <main class="page home-page">
        <div class="home-hero">
          <h1 class="display">
            <span class="home-title-light">{_['readonly-device-title']}</span><br />
            {_['join-existing']}
          </h1>
          <p class="home-sub">{_['readonly-device-body']}</p>
        </div>

        <div class="home-stats">
          <div class="home-stat">
            <span class="home-stat-label">{_['account']}</span>
            <span class="home-stat-value mono">{mask(accountAddr, 8, 6)}</span>
          </div>
          <div class="home-stat">
            <span class="home-stat-label">{_['mode']}</span>
            <span class="home-stat-value mono">{_['account-mode-readonly']}</span>
          </div>
          <div class="home-stat secondary">
            <span class="home-stat-label">{_['balance-label']}</span>
            <span class="home-stat-value mono">{currentBalance.toFixed(1)} OAS</span>
          </div>
          <div class="home-stat secondary">
            <span class="home-stat-label">{_['wallet']}</span>
            <span class="home-stat-value mono">{walletExists ? mask(walletAddr, 8, 6) : '—'}</span>
          </div>
        </div>

        <div class="home-readonly-note">
          <p class="body-text">{_['readonly-device-upgrade']}</p>
          <div class="row gap-8 wrap mt-16">
            <button class="btn btn-primary" onClick={() => go('explore')}>
              {_['readonly-device-cta-market']}
            </button>
            <button class="btn btn-ghost" onClick={() => go('network')}>
              {_['readonly-device-cta-network']}
            </button>
          </div>
        </div>
        <DeviceSharePanel canSign={canSign} />
      </main>
    );
  }

  // ── Veteran view ──
  if (isVeteran && !done) {
    return (
      <main class="page home-page">
        <h1 class="sr-only">{_['home']}</h1>
        {/* Stats — balance + earnings prominent */}
        <div class="home-stats">
          <div class="home-stat">
            <span class="home-stat-label">{_['balance-label']}</span>
            <span class="home-stat-value mono">{currentBalance.toFixed(1)} OAS</span>
          </div>
          <div class="home-stat">
            <span class="home-stat-label">{_['earnings']}</span>
            <span class="home-stat-value mono">{fmtPrice(ownerEarnings?.total_earned)} OAS</span>
          </div>
          <div class="home-stat secondary">
            <span class="home-stat-label">{_['account']}</span>
            <span class="home-stat-value mono">{mask(accountAddr, 8, 6)}</span>
          </div>
          <div class="home-stat secondary">
            <span class="home-stat-label">{_['mydata']}</span>
            <span class="home-stat-value mono">{assetCount}</span>
          </div>
        </div>

        {/* Recent trades */}
        <div class="home-trades">
          <div class="label">{_['recent-trades']}</div>
          {earningsLoading ? (
            <div class="item-list" role="status" aria-busy="true" aria-label={_['loading']}>
              {[0, 1, 2].map(i => (
                <div key={i} class="item-row cursor-default">
                  <div class="grow"><div class="skeleton home-skel-name" /></div>
                  <div class="skeleton home-skel-price" />
                </div>
              ))}
            </div>
          ) : ownerEarnings && ownerEarnings.transactions.length > 0 ? (
            <div class="item-list">
              {ownerEarnings.transactions.slice(0, 5).map((tx) => (
                <div key={`${tx.asset_id}-${tx.timestamp}`} class="item-row cursor-default">
                  <div class="grow">
                    <div class="item-meta">
                      <span class="mono item-id-inline">{maskIdShort(tx.asset_id)}</span>
                      <span class="caption fg-muted">{fmtDate(tx.timestamp)}</span>
                    </div>
                  </div>
                  <span class="mono item-price">{fmtPrice(tx.amount)} <span class="oas-unit">OAS</span></span>
                </div>
              ))}
            </div>
          ) : (
            <p class="caption fg-muted mt-8">{_['no-data']}</p>
          )}
        </div>

        {/* Inline register button */}
        <div class="home-vet-actions">
          <RegisterForm mode="data" onSuccess={handleSuccess} />
          <button class="btn btn-primary mt-16" onClick={() => go('explore')}>
            {_['vet-register-cta']}
          </button>
        </div>
        <DeviceSharePanel canSign={canSign} />
      </main>
    );
  }

  // ── Success state ──
  if (done) {
    return (
      <main class="page home-page">
        <div class="home-success">
          <div class="home-success-banner">
            <span class="home-success-check color-green" aria-hidden="true">✓</span>
            <h1 class="home-section-title" ref={successRef} tabIndex={-1}>
              {_['success-outcome']}
            </h1>
          </div>
          <p class="body-text mt-16">{_['success-outcome-body']}</p>
          <div class="row gap-8 wrap mt-16">
            <button class="btn btn-primary" onClick={() => go('explore')}>
              {_['success-cta-market']}
            </button>
            <button class="btn btn-ghost" onClick={() => setDone(null)}>
              {_['success-cta-more']}
            </button>
          </div>
        </div>
      </main>
    );
  }

  // ── Onboarding flow (accordion) ──
  return (
    <main class="page home-page">
      {/* Hero */}
      <div class="home-hero">
        <h1 class="display">
          <span class="home-title-light">{_['hero-title-light']}</span><br />
          {_['hero-title-bold']}
        </h1>
        <p class="home-sub">{_['hero-sub']}</p>
      </div>

      {/* Accordion onboarding */}
      <div class="home-accordion">
        <div class="label">{_['onboard-welcome']}</div>
        <p class="caption fg-muted mb-12">{_['onboard-welcome-hint']}</p>

        {/* Step 1 — Create account */}
        <div
          class={`accordion-step ${walletExists ? 'is-done' : ''} ${currentStep === 1 ? 'is-active' : ''} ${currentStep < 1 ? 'is-locked' : ''}`}
          data-step="1"
          aria-expanded={currentStep === 1 ? 'true' : 'false'}
          aria-disabled={currentStep < 1 ? 'true' : undefined}
        >
          <div class="accordion-header">
            <span class="accordion-idx mono" aria-hidden="true">{walletExists ? '✓' : '01'}</span>
            <div class="accordion-title">
              <strong>{_['onboard-step1']}</strong>
              <span class="accordion-hint">{_['onboard-step1-hint']}</span>
              {accountConfigured && (
                <span class="accordion-summary mono">{mask(accountAddr, 8, 6)}</span>
              )}
            </div>
          </div>
          {currentStep === 1 && (
            <div class="accordion-body">
              <p class="body-text mb-16">{_['gate-create-body']}</p>
              <AccountJoinPanel onReady={handleAccountReady} />
            </div>
          )}
        </div>

        {/* Step 2 — Claim starter bonus */}
        <div
          class={`accordion-step ${hasStarterFunds ? 'is-done' : ''} ${currentStep === 2 ? 'is-active' : ''} ${currentStep < 2 ? 'is-locked' : ''}`}
          data-step="2"
          aria-expanded={currentStep === 2 ? 'true' : 'false'}
          aria-disabled={currentStep < 2 ? 'true' : undefined}
        >
          <div class="accordion-header">
            <span class="accordion-idx mono" aria-hidden="true">{hasStarterFunds ? '✓' : '02'}</span>
            <div class="accordion-title">
              <strong>{_['onboard-step2']}</strong>
              <span class="accordion-hint">{_['onboard-step2-hint']}</span>
              {hasStarterFunds && (
                <span class="accordion-summary mono">{currentBalance.toFixed(1)} OAS</span>
              )}
            </div>
          </div>
          {currentStep === 2 && (
            <div class="accordion-body">
              <p class="body-text mb-16">{_['gate-funds-body']}</p>
              <button class="btn btn-primary"
                onClick={handleSelfRegister}
                disabled={claiming || powProgress.value.mining}>
                {powProgress.value.mining
                  ? _['onboard-step2-mining']
                  : _['onboard-step2-btn']}
              </button>
            </div>
          )}
        </div>

        {/* Step 3 — Upload first file */}
        <div
          class={`accordion-step ${onboardingDone ? 'is-done' : ''} ${currentStep === 3 ? 'is-active' : ''} ${currentStep < 3 ? 'is-locked' : ''}`}
          data-step="3"
          aria-expanded={currentStep === 3 ? 'true' : 'false'}
          aria-disabled={currentStep < 3 ? 'true' : undefined}
        >
          <div class="accordion-header">
            <span class="accordion-idx mono" aria-hidden="true">{onboardingDone ? '✓' : '03'}</span>
            <div class="accordion-title">
              <strong>{_['onboard-step3']}</strong>
              <span class="accordion-hint">{_['onboard-step3-hint']}</span>
            </div>
          </div>
          {currentStep === 3 && (
            <div class="accordion-body">
              <RegisterForm compact mode="data" onSuccess={handleSuccess} />
            </div>
          )}
        </div>
      </div>

      {accountConfigured && (
        <DeviceSharePanel canSign={canSign} />
      )}
    </main>
  );
}
