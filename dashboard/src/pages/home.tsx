/**
 * Home — launch console
 * Flat layout: no shell-panel, no card grids.
 * Hierarchy through typography + spacing + borders only.
 */
import { useEffect, useState, useRef, useCallback } from 'preact/hooks';
import { get, post } from '../api/client';
import { assets, loadAssets } from '../store/assets';
import {
  balance,
  identity,
  i18n,
  lang,
  loadBalance,
  loadIdentity,
  powProgress,
  selfRegister,
  showToast,
  walletAddress as getWalletAddress,
} from '../store/ui';
import RegisterForm from '../components/register-form';
import { Section } from '../components/section';
import NetworkGrid from '../components/network-grid';
import { mask, fmtPrice, maskIdShort } from '../utils';
import type { Page } from '../hooks/use-route';
import './home.css';

type Mode = 'data' | 'capability';

interface LaunchResult {
  asset_id?: string;
  file_hash?: string;
  file_count?: number;
  price_model?: string;
  capability?: boolean;
}

interface CreateWalletResult {
  ok?: boolean;
  address?: string;
  created?: boolean;
  error?: string;
}

interface OwnerEarningsData {
  total_earned: number;
  transactions: { asset_id: string; buyer: string; amount: number; timestamp: number }[];
}

export default function Home({ go }: { go: (p: Page, sub?: string) => void }) {
  const _ = i18n.value;
  const zh = lang.value === 'zh';

  const [mode, setMode] = useState<Mode>('data');
  const [creatingWallet, setCreatingWallet] = useState(false);
  const [claiming, setClaiming] = useState(false);
  const [done, setDone] = useState<LaunchResult | null>(null);
  const [ownerEarnings, setOwnerEarnings] = useState<OwnerEarningsData | null>(null);
  const [earningsLoading, setEarningsLoading] = useState(false);

  // Refs for focus management
  const successRef = useRef<HTMLHeadingElement>(null);
  const gateRef = useRef<HTMLHeadingElement>(null);
  // Guard to prevent re-fetching earnings on isVeteran toggle
  const earningsFetched = useRef(false);

  useEffect(() => {
    loadAssets();
  }, []);

  const walletExists = !!identity.value?.exists;
  const walletAddr = identity.value?.address || '';
  const currentBalance = balance.value ?? 0;
  const hasStarterFunds = currentBalance > 0;
  const assetCount = assets.value.length;
  const isVeteran = walletExists && hasStarterFunds && assetCount > 0;

  // Load earnings for veteran view (L2: stable guard via ref)
  useEffect(() => {
    if (!isVeteran || earningsFetched.current) return;
    const addr = getWalletAddress();
    if (addr === 'anonymous') return;
    earningsFetched.current = true;
    setEarningsLoading(true);
    get<OwnerEarningsData>(`/earnings?owner=${encodeURIComponent(addr)}`).then(res => {
      if (res.success && res.data && typeof res.data === 'object') setOwnerEarnings(res.data);
    }).catch(() => {
      // earnings fetch failed — non-critical, UI shows fallback
    }).finally(() => {
      setEarningsLoading(false);
    });
  }, [isVeteran]);

  const copy = zh
    ? {
        heroActionPrimary: walletExists ? '进入市场' : _['create-wallet'],
        heroActionSecondary: walletExists ? '查看网络' : '',
        statusWallet: '钱包',
        statusBalance: _['balance-label'],
        statusInventory: '资产',
        routeWallet: '创建身份',
        routeFunds: '领取启动资金',
        routeLaunch: '登记并进入市场',
        walletGateTitle: '创建你的链上身份',
        walletGateBody: '你的地址是所有操作的唯一身份。',
        fundsGateTitle: '获取启动资金',
        fundsGateBody: '完成算力验证，获取进入市场所需的 OAS。',
        registerTitle: '登记资产',
        registerBody: '登记数据资产或发布 AI 能力。',
        successTitleData: '数据资产已登记',
        successTitleCap: '能力已上架',
        successBody: '资产已进入市场索引，前往资产页或市场页查看。',
        summaryHash: '文件哈希',
        summaryFiles: '打包文件数',
        summaryPricing: '定价方式',
        summaryType: '登记类型',
        dataType: '数据资产',
        capType: 'AI 能力',
        walletExisting: '钱包已存在',
        destinationsTitle: '下一站',
        vetRegisterMore: '登记更多',
        earningsTitle: '收益概览',
        recentTitle: '最近交易',
        noActivity: '暂无交易',
      }
    : {
        heroActionPrimary: walletExists ? 'Open market' : _['create-wallet'],
        heroActionSecondary: walletExists ? 'View network' : '',
        statusWallet: 'Wallet',
        statusBalance: _['balance-label'],
        statusInventory: 'Assets',
        routeWallet: 'Create identity',
        routeFunds: 'Claim starter funds',
        routeLaunch: 'Register and enter market',
        walletGateTitle: 'Create your on-chain identity',
        walletGateBody: 'Your address becomes your single identity for all operations.',
        fundsGateTitle: 'Earn starter funds',
        fundsGateBody: 'Complete proof-of-work to receive starter OAS for market entry.',
        registerTitle: 'Register assets',
        registerBody: 'Register a data asset or list an AI capability.',
        successTitleData: 'Data asset registered',
        successTitleCap: 'Capability listed',
        successBody: 'Asset is now in the market index. View it in My Data or Market.',
        summaryHash: 'File hash',
        summaryFiles: 'Bundled files',
        summaryPricing: 'Pricing model',
        summaryType: 'Registration type',
        dataType: 'Data asset',
        capType: 'AI capability',
        walletExisting: 'Wallet already exists',
        destinationsTitle: 'Navigate',
        vetRegisterMore: 'Register more',
        earningsTitle: 'Earnings',
        recentTitle: 'Recent trades',
        noActivity: 'No trades yet',
      };

  const currentStep = !walletExists ? 1 : !hasStarterFunds ? 2 : 3;
  const onboardingDone = walletExists && hasStarterFunds && (assetCount > 0 || !!done);

  const steps = [
    {
      index: '01',
      title: _['onboard-step1'],
      detail: walletExists ? mask(walletAddr, 8, 6) : _['wallet-needed'],
      done: walletExists,
      active: currentStep === 1,
    },
    {
      index: '02',
      title: _['onboard-step2'],
      detail: hasStarterFunds ? `${currentBalance.toFixed(1)} OAS` : (_['onboard-step2-btn'] || 'Register'),
      done: hasStarterFunds,
      active: currentStep === 2,
    },
    {
      index: '03',
      title: _['onboard-step3'],
      detail: onboardingDone ? (done?.capability ? copy.capType : copy.dataType) : copy.routeLaunch,
      done: onboardingDone,
      active: currentStep === 3,
    },
  ];

  const resultRows = done ? [
    { label: _['id'], value: mask(done.asset_id, 12, 8), mono: true },
    ...(done.file_hash ? [{ label: copy.summaryHash, value: mask(done.file_hash, 14, 8), mono: true }] : []),
    ...(done.file_count != null ? [{ label: copy.summaryFiles, value: String(done.file_count), mono: false }] : []),
    ...(done.price_model ? [{ label: copy.summaryPricing, value: _[`price-model-${done.price_model}`] || done.price_model, mono: false }] : []),
    { label: copy.summaryType, value: done.capability ? copy.capType : copy.dataType, mono: false },
  ] : [];

  async function handleCreateWallet() {
    if (creatingWallet) return;
    setCreatingWallet(true);
    const res = await post<CreateWalletResult>('/identity/create');
    setCreatingWallet(false);

    if (res.success && res.data?.ok) {
      await loadIdentity();
      await loadBalance();
      await loadAssets();
      showToast(res.data.created ? _['wallet-created'] : copy.walletExisting, 'success');
      // M2: move focus to next gate section
      requestAnimationFrame(() => gateRef.current?.focus());
      return;
    }

    showToast(res.error || res.data?.error || _['error-generic'], 'error');
  }

  async function handleSelfRegister() {
    if (claiming || powProgress.value.mining) return;
    setClaiming(true);
    const res = await selfRegister();
    setClaiming(false);

    if (res.ok) {
      await loadBalance();
      showToast(
        (_['register-success'] || 'Received {amount} OAS').replace('{amount}', String(res.amount ?? 0)),
        'success',
      );
      return;
    }

    showToast(res.error || _['error-generic'], 'error');
  }

  function handleSuccess(result: LaunchResult) {
    setDone(result);
    loadAssets();
    showToast(result.capability ? (_['cap-published'] || copy.successTitleCap) : _['protected'], 'success');
    // M2: move focus to success heading
    requestAnimationFrame(() => successRef.current?.focus());
  }

  async function handleCopyAssetId() {
    if (!done?.asset_id) return;
    try {
      await navigator.clipboard.writeText(done.asset_id);
      showToast(_['copied'], 'success');
    } catch {
      showToast(_['error-generic'], 'error');
    }
  }

  /* ── Mode switch (shared between veteran & onboarding) ── */
  const handleTabKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      const next: Mode = mode === 'data' ? 'capability' : 'data';
      setMode(next);
      // Move focus to the newly active tab
      const target = (e.currentTarget as HTMLElement)
        ?.parentElement?.querySelector(`[data-tab="${next}"]`) as HTMLElement | null;
      target?.focus();
    }
  }, [mode]);

  const modeSwitch = (label: string) => (
    <div class="home-mode-switch" role="tablist" aria-label={label}>
      <button role="tab" aria-selected={mode === 'data'}
        aria-controls="home-tabpanel"
        tabIndex={mode === 'data' ? 0 : -1}
        data-tab="data"
        class={`home-mode-tab ${mode === 'data' ? 'active' : ''}`}
        onClick={() => setMode('data')}
        onKeyDown={handleTabKeyDown}>{_['register-data']}</button>
      <span class="home-mode-sep" aria-hidden="true">/</span>
      <button role="tab" aria-selected={mode === 'capability'}
        aria-controls="home-tabpanel"
        tabIndex={mode === 'capability' ? 0 : -1}
        data-tab="capability"
        class={`home-mode-tab ${mode === 'capability' ? 'active' : ''}`}
        onClick={() => setMode('capability')}
        onKeyDown={handleTabKeyDown}>{_['publish-cap']}</button>
    </div>
  );

  /* ── Navigation links (shared) ── */
  const navLinks = (
    <div class="home-navigate">
      <div class="label">{copy.destinationsTitle}</div>
      <nav>
        <button class="nav-row" onClick={() => go('mydata')}>
          <span class="nav-row-title">{_['nav-mydata']} <span class="nav-arrow" aria-hidden="true">→</span></span>
          <span class="nav-row-desc">{_['nav-mydata-desc']}</span>
        </button>
        <button class="nav-row" onClick={() => go('explore')}>
          <span class="nav-row-title">{_['nav-explore']} <span class="nav-arrow" aria-hidden="true">→</span></span>
          <span class="nav-row-desc">{_['nav-explore-desc']}</span>
        </button>
        <button class="nav-row" onClick={() => go('network')}>
          <span class="nav-row-title">{_['nav-network']} <span class="nav-arrow" aria-hidden="true">→</span></span>
          <span class="nav-row-desc">{_['nav-network-desc']}</span>
        </button>
      </nav>
    </div>
  );

  // ── Veteran view ──
  if (isVeteran && !done) {
    return (
      <main class="page home-page">
        {/* NetworkGrid */}
        <div class="home-grid-wrap">
          <NetworkGrid />
        </div>

        {/* Hero text */}
        <div class="home-hero">
          <h1 class="display">
            <span class="home-title-light">{_['hero-title-light']}</span>{' '}
            <strong>{_['hero-title-bold']}</strong>
          </h1>
          <p class="body-text mt-8">{_['hero-sub']}</p>
          <div class="row gap-8 mt-16">
            <button class="btn btn-primary" onClick={() => go('explore')}>
              {copy.heroActionPrimary}
            </button>
            <button class="btn btn-ghost" onClick={() => go('network')}>
              {copy.heroActionSecondary}
            </button>
          </div>
        </div>

        <div class="home-overview">
          <div class="home-status">
            <div class="kv">
              <span class="kv-key">{copy.statusWallet}</span>
              <span class="kv-val mono">{mask(walletAddr, 8, 6)}</span>
            </div>
            <div class="kv">
              <span class="kv-key">{copy.statusBalance}</span>
              <span class="kv-val mono">{currentBalance.toFixed(1)} OAS</span>
            </div>
            <div class="kv">
              <span class="kv-key">{copy.statusInventory}</span>
              <span class="kv-val mono">{assetCount}</span>
            </div>
            <div class="kv">
              <span class="kv-key">{copy.earningsTitle}</span>
              <span class="kv-val mono">{fmtPrice(ownerEarnings?.total_earned)} OAS</span>
            </div>
          </div>

          <div class="home-trades">
            <div class="label">{copy.recentTitle}</div>
            {earningsLoading ? (
              <div class="item-list">
                {[0, 1, 2].map(i => (
                  <div key={i} class="item-row cursor-default">
                    <div class="grow"><div class="skeleton" style="width:120px;height:14px" /></div>
                    <div class="skeleton" style="width:80px;height:14px" />
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
                      </div>
                    </div>
                    <span class="mono item-price">{fmtPrice(tx.amount)} <span class="oas-unit">OAS</span></span>
                  </div>
                ))}
              </div>
            ) : (
              <p class="caption fg-muted mt-8">{copy.noActivity}</p>
            )}
          </div>
        </div>

        {navLinks}

        {/* Register more — collapsed by default for veterans */}
        <Section id="home-register" title={copy.vetRegisterMore} desc={zh ? '登记数据资产或发布 AI 能力' : 'Register data assets or publish AI capabilities'}>
          {modeSwitch(copy.vetRegisterMore)}
          <div id="home-tabpanel" role="tabpanel">
            <RegisterForm mode={mode} onSuccess={handleSuccess} />
          </div>
        </Section>
      </main>
    );
  }

  // ── Onboarding / registration flow ──
  return (
    <main class="page home-page">
      {/* NetworkGrid */}
      <div class="home-grid-wrap">
        <NetworkGrid />
      </div>

      {/* Hero */}
      <div class="home-hero">
        <h1 class="display">
          <span class="home-title-light">{_['hero-title-light']}</span>{' '}
          <strong>{_['hero-title-bold']}</strong>
        </h1>
        <p class="body-text mt-8">{_['hero-sub']}</p>
        <div class="row gap-8 mt-16">
          <button class="btn btn-primary"
            onClick={() => { if (walletExists) go('explore'); else handleCreateWallet(); }}
            disabled={creatingWallet}>
            {creatingWallet ? '…' : copy.heroActionPrimary}
          </button>
        </div>
      </div>

      <div class="home-onboard">
        <div class="label">{_['onboard-welcome']}</div>
        <p class="caption fg-muted mb-12">{_['onboard-welcome-hint']}</p>
        <ol class="home-steps">
          {steps.map(step => (
            <li key={step.index}
              class={`home-step ${step.done ? 'is-done' : ''} ${step.active ? 'is-active' : ''}`}>
              <span class="home-step-idx mono" aria-hidden="true">{step.done ? '✓' : step.index}</span>
              <div class="home-step-copy">
                <strong>{step.title}</strong>
                <small class="caption">{step.detail}</small>
              </div>
            </li>
          ))}
        </ol>
      </div>

      <div class="home-gate">
        {!walletExists && (
          <>
            <h2 class="home-section-title" ref={gateRef} tabIndex={-1}>{copy.walletGateTitle}</h2>
            <p class="body-text mt-8 mb-16">{copy.walletGateBody}</p>
            <button class="btn btn-primary" onClick={handleCreateWallet} disabled={creatingWallet}>
              {creatingWallet ? '…' : _['create-wallet']}
            </button>
          </>
        )}

        {walletExists && !hasStarterFunds && (
          <>
            <h2 class="home-section-title" ref={gateRef} tabIndex={-1}>{copy.fundsGateTitle}</h2>
            <p class="body-text mt-8 mb-16">{copy.fundsGateBody}</p>
            <button class="btn btn-primary"
              onClick={handleSelfRegister}
              disabled={claiming || powProgress.value.mining}>
              {powProgress.value.mining
                ? (_['onboard-step2-mining'] || 'Mining…')
                : (_['onboard-step2-btn'] || 'Register')}
            </button>
          </>
        )}

        {walletExists && hasStarterFunds && (
          <>
            {done ? (
              <>
                <div class="home-success-banner">
                  <span class="home-success-check color-green" aria-hidden="true">✓</span>
                  <h2 class="home-section-title" ref={successRef} tabIndex={-1}>{done.capability ? copy.successTitleCap : copy.successTitleData}</h2>
                </div>
                <p class="body-text mt-8">{copy.successBody}</p>
                <div class="mt-16">
                  {resultRows.map(row => (
                    <div key={row.label} class="kv">
                      <span class="kv-key">{row.label}</span>
                      <span class={`kv-val ${row.mono ? 'mono' : ''}`}>{row.value}</span>
                    </div>
                  ))}
                </div>
                <div class="row gap-8 wrap mt-16">
                  <button class="btn btn-primary" onClick={() => go('mydata')}>{_['view-mydata']}</button>
                  <button class="btn btn-ghost" onClick={() => go('explore')}>{_['nav-explore']}</button>
                  <button class="btn btn-ghost" onClick={handleCopyAssetId}>{_['copy']}</button>
                  <button class="btn btn-ghost" onClick={() => setDone(null)}>{_['again']}</button>
                </div>
              </>
            ) : (
              <>
                {modeSwitch(copy.registerTitle)}
                <div id="home-tabpanel" role="tabpanel">
                  <RegisterForm mode={mode} onSuccess={handleSuccess} />
                </div>
              </>
            )}
          </>
        )}
      </div>

      {navLinks}
    </main>
  );
}
