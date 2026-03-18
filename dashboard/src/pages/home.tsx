/**
 * Home — 首页
 * 注册流程使用共享 RegisterForm 组件
 */
import { useState, useEffect } from 'preact/hooks';
import { showToast, i18n, balance, claimFaucet, faucetCooldown, identity, loadIdentity, loadBalance } from '../store/ui';
import NetworkGrid from '../components/network-grid';
import RegisterForm from '../components/register-form';
import type { Page } from '../hooks/use-route';
import { fmtPrice } from '../utils';
import './home.css';

interface Props { go: (p: Page, sub?: string) => void; }

function maskId(id: string) {
  if (!id || id.length <= 8) return id;
  return id.slice(0, 8) + '••••';
}

type Mode = 'data' | 'capability';

const ONBOARD_DONE_KEY = 'oasyce-onboard-done';

function isOnboardComplete(): boolean {
  try { return localStorage.getItem(ONBOARD_DONE_KEY) === '1'; } catch { return false; }
}
function markOnboardComplete(): void {
  try { localStorage.setItem(ONBOARD_DONE_KEY, '1'); } catch { /* private mode */ }
}

export default function Home({ go }: Props) {
  const [mode, setMode] = useState<Mode>('data');
  const [done, setDone] = useState<any>(null);
  const [claiming, setClaiming] = useState(false);
  const [creatingWallet, setCreatingWallet] = useState(false);
  const [onboardDismissed, setOnboardDismissed] = useState(isOnboardComplete);

  const _ = i18n.value;

  const walletExists = identity.value && identity.value.exists;
  const hasBalance = balance.value !== null && balance.value > 0;

  // Determine the current onboarding step (1-based)
  // Step 1: Create Wallet — active when wallet does not exist
  // Step 2: Claim Test OAS — active after wallet created, before balance > 0
  // Step 3: Register First Asset — active after claiming OAS, until first asset registered
  const onboardStep: number = !walletExists ? 1 : !hasBalance ? 2 : 3;

  // Show the onboarding wizard when identity exists but has no wallet,
  // OR wallet exists but user hasn't finished onboarding yet.
  const showOnboard = identity.value !== null && !identity.value.exists
    ? true  // no wallet yet — always show step 1
    : (walletExists && !onboardDismissed && !done);

  const handleCreateWallet = async () => {
    setCreatingWallet(true);
    try {
      const res = await fetch('/api/identity/create', { method: 'POST' });
      if (res.ok) {
        showToast(_['wallet-created'], 'success');
        await loadIdentity();
        await loadBalance();
      } else {
        showToast(_['error-generic'], 'error');
      }
    } catch {
      showToast(_['error-generic'], 'error');
    } finally {
      setCreatingWallet(false);
    }
  };

  const handleFaucetClaim = async () => {
    setClaiming(true);
    const res = await claimFaucet();
    setClaiming(false);
    if (res.ok) {
      showToast((_['faucet-success'] || 'Claimed {amount} OAS').replace('{amount}', String(res.amount ?? 0)), 'success');
    } else if (res.error?.includes('Cooldown')) {
      faucetCooldown.value = true;
      showToast(_['faucet-cooldown'] || 'Please try again later', 'warn');
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
  };

  const handleSuccess = (result: any) => {
    setDone(result);
    // Complete onboarding when first asset is registered via the wizard
    if (!onboardDismissed) {
      markOnboardComplete();
      setOnboardDismissed(true);
    }
  };

  const copyId = async () => {
    if (!done?.asset_id) return;
    try {
      await navigator.clipboard.writeText(done.asset_id);
      showToast(_['copied'], 'success');
    } catch {
      showToast(_['error-generic'], 'error');
    }
  };

  // --- Onboarding step UI helper ---
  const stepStyle = (step: number, current: number) => {
    const base = 'display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;font-weight:700;font-size:14px;flex-shrink:0;';
    if (step < current) return base + 'background:var(--accent);color:var(--bg-0);';
    if (step === current) return base + 'background:var(--accent);color:var(--bg-0);box-shadow:0 0 0 3px var(--accent-dim,rgba(99,102,241,0.25));';
    return base + 'background:var(--bg-3,#333);color:var(--fg-2);';
  };

  return (
    <div class="page">
      <div class="home-grid-wrap home-grid-top">
        <NetworkGrid />
      </div>

      {/* Onboarding wizard — shown for first-time users */}
      {showOnboard && !onboardDismissed && (
        <div class="home-wallet-banner" style="background:var(--bg-2);border:1px solid var(--border);border-radius:12px;padding:24px;margin:0 auto 24px;max-width:520px">
          {/* Step indicators */}
          <div style="display:flex;align-items:center;gap:12px;margin-bottom:20px;justify-content:center">
            <span style={stepStyle(1, onboardStep)}>{onboardStep > 1 ? '\u2713' : '1'}</span>
            <div style="width:32px;height:2px;background:var(--border);border-radius:1px" />
            <span style={stepStyle(2, onboardStep)}>{onboardStep > 2 ? '\u2713' : '2'}</span>
            <div style="width:32px;height:2px;background:var(--border);border-radius:1px" />
            <span style={stepStyle(3, onboardStep)}>3</span>
          </div>

          {/* Step 1: Create Wallet */}
          {onboardStep === 1 && (
            <div style="text-align:center">
              <h3 style="margin:0 0 8px;font-size:16px;color:var(--fg-0)">{_['onboard-step1']}</h3>
              <p style="margin:0 0 12px;color:var(--fg-2);font-size:14px">{_['wallet-needed']}</p>
              <button
                class="btn btn-ghost"
                style="border:2px solid var(--accent);font-weight:600"
                disabled={creatingWallet}
                onClick={handleCreateWallet}
              >
                {creatingWallet ? '...' : _['create-wallet']}
              </button>
            </div>
          )}

          {/* Step 2: Claim Test OAS */}
          {onboardStep === 2 && (
            <div style="text-align:center">
              <h3 style="margin:0 0 8px;font-size:16px;color:var(--fg-0)">{_['onboard-step2']}</h3>
              <p style="margin:0 0 12px;color:var(--fg-2);font-size:14px">{(balance.value ?? 0).toFixed(1)} OAS</p>
              <button
                class="btn btn-ghost"
                style="border:2px solid var(--accent);font-weight:600"
                disabled={claiming || faucetCooldown.value}
                onClick={handleFaucetClaim}
              >
                {claiming ? '...' : (_['faucet-claim'] || 'Claim Test OAS')}
              </button>
            </div>
          )}

          {/* Step 3: Register First Asset */}
          {onboardStep === 3 && (
            <div>
              <h3 style="margin:0 0 12px;font-size:16px;color:var(--fg-0);text-align:center">{_['onboard-step3']}</h3>
              {/* Mode toggle */}
              <div class="home-mode-switch" role="tablist" style="margin-bottom:12px">
                <button
                  role="tab"
                  aria-selected={mode === 'data'}
                  class={`home-mode-tab ${mode === 'data' ? 'active' : ''}`}
                  onClick={() => setMode('data')}
                >
                  {_['register-data'] || 'Register data'}
                </button>
                <span class="home-mode-sep" aria-hidden="true">/</span>
                <button
                  role="tab"
                  aria-selected={mode === 'capability'}
                  class={`home-mode-tab ${mode === 'capability' ? 'active' : ''}`}
                  onClick={() => setMode('capability')}
                >
                  {_['publish-cap'] || 'List capability'}
                </button>
              </div>
              <RegisterForm mode={mode} onSuccess={handleSuccess} />
            </div>
          )}
        </div>
      )}

      {/* Onboarding complete message (shown briefly after step 3 finishes) */}
      {onboardDismissed && done && (
        <div style="text-align:center;margin:0 auto 24px;max-width:480px;padding:16px;background:var(--bg-2);border:1px solid var(--accent);border-radius:12px">
          <div style="font-size:20px;margin-bottom:4px">{_['onboard-complete']}</div>
        </div>
      )}

      {/* Hero */}
      <div class="home-hero">
        <h1 class="display">
          <span class="home-title-light">{_['hero-title-light']}</span>
          <br />
          <strong>{_['hero-title-bold']}</strong>
        </h1>
        <p class="body-text mt-16">{_['hero-sub']}</p>
        {walletExists && (
          <div class="home-faucet mt-16" style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
            <span class="mono" style="font-size:14px;color:var(--fg-1)">{(balance.value ?? 0).toFixed(1)} OAS</span>
            <button
              class="btn btn-ghost btn-sm"
              disabled={claiming || faucetCooldown.value}
              onClick={handleFaucetClaim}
            >
              {claiming ? '...' : (_['faucet-claim'] || 'Claim Test OAS')}
            </button>
          </div>
        )}
      </div>

      <div class="spacer-48" />

      {/* 注册区 — only shown when wallet exists and onboarding is complete */}
      <div class="home-register">
        {!walletExists ? (
          <div style="text-align:center;color:var(--fg-2);padding:24px">
            <p>{_['wallet-needed']}</p>
          </div>
        ) : !done ? (
          <>
            {/* 模式切换 — 用下划线文字，不用按钮 */}
            <div class="home-mode-switch" role="tablist">
              <button
                role="tab"
                aria-selected={mode === 'data'}
                class={`home-mode-tab ${mode === 'data' ? 'active' : ''}`}
                onClick={() => setMode('data')}
              >
                {_['register-data'] || '注册数据'}
              </button>
              <span class="home-mode-sep" aria-hidden="true">/</span>
              <button
                role="tab"
                aria-selected={mode === 'capability'}
                class={`home-mode-tab ${mode === 'capability' ? 'active' : ''}`}
                onClick={() => setMode('capability')}
              >
                {_['publish-cap'] || '发布能力'}
              </button>
            </div>

            <RegisterForm mode={mode} onSuccess={handleSuccess} />
          </>
        ) : (
          <div class="home-success">
            <div class="home-success-icon">✓</div>
            <div class="home-success-title">
              {done.capability ? (_['cap-published'] || '能力已发布') : _['protected']}
            </div>
            {done.file_count && (
              <div class="caption mb-8">
                {done.file_count} {_['files-bundled'] || '个文件已打包注册'}
              </div>
            )}
            <div class="home-success-detail">
              <div class="kv">
                <span class="kv-key">{_['id']}</span>
                <span class="kv-val">
                  <span class="masked">
                    <span>{maskId(done.asset_id)}</span>
                    <button class="btn-copy" onClick={copyId}>{_['copy']}</button>
                  </span>
                </span>
              </div>
              {done.spot_price != null && (
                <div class="kv">
                  <span class="kv-key">{_['spot-price']}</span>
                  <span class="kv-val">{fmtPrice(done.spot_price)} OAS</span>
                </div>
              )}
              {done.rights_type && (
                <div class="kv">
                  <span class="kv-key">{_['rights-type']}</span>
                  <span class="kv-val">{_[`rights-${done.rights_type}`] || done.rights_type}</span>
                </div>
              )}
              {done.fingerprint && (
                <div class="kv">
                  <span class="kv-key">{_['wm-fingerprint'] || '指纹'}</span>
                  <span class="kv-val mono fingerprint-val">{done.fingerprint.slice(0, 12)}…</span>
                </div>
              )}
            </div>
            <div class="row gap-8 mt-16 justify-center">
              <button class="btn btn-ghost btn-sm" onClick={() => go('mydata')}>{_['view-mydata']} →</button>
              <button class="btn btn-ghost btn-sm" onClick={() => setDone(null)}>{_['again']}</button>
            </div>
          </div>
        )}
      </div>

      <div class="spacer-48" />

      {/* 底部导航 */}
      <div class="home-nav">
        <button class="nav-row" role="link" onClick={() => go('mydata')}>
          <span class="nav-row-title">{_['nav-mydata']} →</span>
          <span class="nav-row-desc">{_['nav-mydata-desc']}</span>
        </button>
        <button class="nav-row" role="link" onClick={() => go('explore')}>
          <span class="nav-row-title">{_['nav-explore']} →</span>
          <span class="nav-row-desc">{_['nav-explore-desc']}</span>
        </button>
        <button class="nav-row" role="link" onClick={() => go('network')}>
          <span class="nav-row-title">{_['nav-network']} →</span>
          <span class="nav-row-desc">{_['nav-network-desc']}</span>
        </button>
      </div>
    </div>
  );
}
