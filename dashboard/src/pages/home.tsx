/**
 * Home — formal launch console
 */
import { useEffect, useState } from 'preact/hooks';
import { post } from '../api/client';
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
} from '../store/ui';
import RegisterForm from '../components/register-form';
import NetworkGrid from '../components/network-grid';
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

function maskValue(value: string | undefined | null, head = 10, tail = 6) {
  if (!value) return '--';
  if (value.length <= head + tail + 1) return value;
  return `${value.slice(0, head)}…${value.slice(-tail)}`;
}

export default function Home({ go }: { go: (p: Page, sub?: string) => void }) {
  const _ = i18n.value;
  const zh = lang.value === 'zh';

  const [mode, setMode] = useState<Mode>('data');
  const [creatingWallet, setCreatingWallet] = useState(false);
  const [claiming, setClaiming] = useState(false);
  const [done, setDone] = useState<LaunchResult | null>(null);

  useEffect(() => {
    loadAssets();
  }, []);

  const walletExists = !!identity.value?.exists;
  const walletAddress = identity.value?.address || '';
  const currentBalance = balance.value ?? 0;
  const hasStarterFunds = currentBalance > 0;
  const assetCount = assets.value.length;

  const copy = zh
    ? {
        heroKicker: '正式版操作台',
        heroNote: '正式模式下，首页不再是宣传页，而是新用户和正式用户共用的链上入口。',
        heroActionPrimary: walletExists ? '进入市场' : _['create-wallet'],
        heroActionSecondary: walletExists ? '查看网络状态' : '查看协议路径',
        statusWallet: '钱包状态',
        statusBalance: _['balance-label'],
        statusInventory: '已登记资产',
        statusRoute: '当前阶段',
        routeWallet: '创建身份',
        routeFunds: '领取启动资金',
        routeLaunch: '登记并进入市场',
        launchTitle: '首日路径',
        launchBody: '按钱包、资金、登记三个阶段顺序推进，避免前端状态先于后端真实能力。',
        walletGateTitle: '先创建你的链上身份',
        walletGateBody: 'GUI 和后端现在都以本地钱包为唯一默认身份。创建后，后续登记、余额和通知都会围绕同一地址闭合。',
        fundsGateTitle: '补足启动资金',
        fundsGateBody: '完成算力验证，获取进入市场所需的启动资金。',
        registerTitle: '登记工作台',
        registerBody: '登记数据资产或 AI 能力。成功态只展示后端真实会返回的字段。',
        successTitleData: '数据资产已登记',
        successTitleCap: '能力已上架',
        successBody: '资产已经进入本地账本与市场索引路径，下一步可以去资产页或市场页验证可见性。',
        checklistTitle: '快速指南',
        checklistBody: '按顺序完成以下三步，即可开始交易。',
        checklistWallet: '创建钱包 — 所有操作将关联到你的链上身份地址',
        checklistFunds: '完成算力注册 — 获得启动资金进入市场',
        checklistRegister: '登记资产或能力 — 开始赚取收益',
        destinationsTitle: '下一站',
        summaryHash: '文件哈希',
        summaryFiles: '打包文件数',
        summaryPricing: '定价方式',
        summaryType: '登记类型',
        dataType: '数据资产',
        capType: 'AI 能力',
        walletExisting: '钱包已存在',
      }
    : {
        heroKicker: 'Formal Launch Console',
        heroNote: 'The home screen now acts as the shared chain-backed entrypoint for both first-time and returning users.',
        heroActionPrimary: walletExists ? 'Open market' : _['create-wallet'],
        heroActionSecondary: walletExists ? 'View network' : 'Review launch path',
        statusWallet: 'Wallet',
        statusBalance: _['balance-label'],
        statusInventory: 'Registered assets',
        statusRoute: 'Current phase',
        routeWallet: 'Create identity',
        routeFunds: 'Claim starter funds',
        routeLaunch: 'Register and enter market',
        launchTitle: 'Day-one route',
        launchBody: 'Move through identity, funding, and registration in order so GUI state never gets ahead of backend truth.',
        walletGateTitle: 'Create your on-chain identity first',
        walletGateBody: 'The GUI and backend now share the same wallet-first identity contract. Once created, registration, balance, and notifications all resolve to one address.',
        fundsGateTitle: 'Earn starter funds',
        fundsGateBody: 'Complete proof-of-work verification to receive starter OAS for market entry.',
        registerTitle: 'Registration workspace',
        registerBody: 'Register a data asset or list an AI capability. The success state only renders fields the backend actually returns.',
        successTitleData: 'Data asset registered',
        successTitleCap: 'Capability listed',
        successBody: 'The asset is now on the local ledger and market index path. Next, verify visibility in My Data or Market.',
        checklistTitle: 'Quick Guide',
        checklistBody: 'Complete these three steps to start trading.',
        checklistWallet: 'Create wallet — all operations tie to your on-chain identity',
        checklistFunds: 'Complete PoW registration — earn starter funds for the market',
        checklistRegister: 'Register an asset or capability — start earning',
        destinationsTitle: 'Next destinations',
        summaryHash: 'File hash',
        summaryFiles: 'Bundled files',
        summaryPricing: 'Pricing model',
        summaryType: 'Registration type',
        dataType: 'Data asset',
        capType: 'AI capability',
        walletExisting: 'Wallet already exists',
      };

  const phaseLabel = !walletExists
    ? copy.routeWallet
    : !hasStarterFunds
      ? copy.routeFunds
      : copy.routeLaunch;

  const currentStep = !walletExists ? 1 : !hasStarterFunds ? 2 : 3;
  const onboardingDone = walletExists && hasStarterFunds && (assetCount > 0 || !!done);

  const steps = [
    {
      index: '01',
      title: _['onboard-step1'],
      detail: walletExists ? maskValue(walletAddress, 8, 6) : _['wallet-needed'],
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
    { label: _['id'], value: maskValue(done.asset_id, 12, 8) },
    ...(done.file_hash ? [{ label: copy.summaryHash, value: maskValue(done.file_hash, 14, 8) }] : []),
    ...(done.file_count != null ? [{ label: copy.summaryFiles, value: String(done.file_count) }] : []),
    ...(done.price_model ? [{ label: copy.summaryPricing, value: _[`price-model-${done.price_model}`] || done.price_model }] : []),
    { label: copy.summaryType, value: done.capability ? copy.capType : copy.dataType },
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

  return (
    <div class="page home-page">
      <section class="home-hero-panel shell-panel">
        <div class="home-grid-wrap home-grid-top">
          <NetworkGrid />
        </div>

        <div class="home-hero-body">
          <div class="home-hero-copy">
            <span class="label">{copy.heroKicker}</span>
            <h1 class="display">
              <span class="home-title-light">{_['hero-title-light']}</span>
              <br />
              <strong>{_['hero-title-bold']}</strong>
            </h1>
            <p class="body-text home-hero-sub">{_['hero-sub']}</p>
            <p class="caption home-hero-note">{copy.heroNote}</p>

            <div class="home-hero-actions">
              <button
                class="btn btn-primary"
                onClick={() => {
                  if (walletExists) go('explore');
                  else handleCreateWallet();
                }}
                disabled={creatingWallet}
              >
                {creatingWallet ? '…' : copy.heroActionPrimary}
              </button>
              <button
                class="btn btn-ghost"
                onClick={() => go(walletExists ? 'network' : 'mydata')}
              >
                {copy.heroActionSecondary}
              </button>
            </div>
          </div>

          <div class="home-hero-status">
            <div class="home-status-card">
              <span class="label">{copy.statusWallet}</span>
              <div class="home-status-value mono">{walletExists ? maskValue(walletAddress, 8, 6) : '--'}</div>
              <div class="caption">{walletExists ? _['identity'] : _['wallet-needed']}</div>
            </div>
            <div class="home-status-card">
              <span class="label">{copy.statusBalance}</span>
              <div class="home-status-value mono">{currentBalance.toFixed(1)} OAS</div>
              <div class="caption">{hasStarterFunds ? copy.routeLaunch : copy.routeFunds}</div>
            </div>
            <div class="home-status-card">
              <span class="label">{copy.statusInventory}</span>
              <div class="home-status-value mono">{assetCount}</div>
              <div class="caption">{done?.capability ? copy.capType : copy.dataType}</div>
            </div>
            <div class="home-status-card">
              <span class="label">{copy.statusRoute}</span>
              <div class="home-status-value">{phaseLabel}</div>
              <div class="caption">Step {currentStep} / 3</div>
            </div>
          </div>
        </div>
      </section>

      <div class="home-workspace">
        <section class="home-launch-panel shell-panel">
          <div class="home-panel-head">
            <div>
              <span class="label">{copy.launchTitle}</span>
              <h2 class="home-panel-title">{walletExists && hasStarterFunds ? copy.registerTitle : copy.launchTitle}</h2>
              <p class="body-text home-panel-body">
                {walletExists && hasStarterFunds ? copy.registerBody : copy.launchBody}
              </p>
            </div>

            <div class="home-step-strip" aria-label={copy.launchTitle}>
              {steps.map(step => (
                <div
                  key={step.index}
                  class={`home-step-chip ${step.done ? 'is-done' : ''} ${step.active ? 'is-active' : ''}`}
                >
                  <span class="home-step-index mono">{step.index}</span>
                  <span class="home-step-copy">
                    <strong>{step.title}</strong>
                    <small>{step.detail}</small>
                  </span>
                </div>
              ))}
            </div>
          </div>

          {!walletExists && (
            <div class="home-gate">
              <div>
                <h3 class="home-gate-title">{copy.walletGateTitle}</h3>
                <p class="body-text home-gate-body">{copy.walletGateBody}</p>
              </div>
              <div class="home-gate-actions">
                <button class="btn btn-primary" onClick={handleCreateWallet} disabled={creatingWallet}>
                  {creatingWallet ? '…' : _['create-wallet']}
                </button>
              </div>
            </div>
          )}

          {walletExists && !hasStarterFunds && (
            <div class="home-gate">
              <div>
                <h3 class="home-gate-title">{copy.fundsGateTitle}</h3>
                <p class="body-text home-gate-body">{copy.fundsGateBody}</p>
              </div>
              <div class="home-gate-actions">
                <button
                  class="btn btn-primary"
                  onClick={handleSelfRegister}
                  disabled={claiming || powProgress.value.mining}
                >
                  {powProgress.value.mining
                    ? (_['onboard-step2-mining'] || 'Mining…')
                    : (_['onboard-step2-btn'] || 'Register')}
                </button>
              </div>
            </div>
          )}

          {walletExists && hasStarterFunds && (
            <>
              {done ? (
                <div class="home-success">
                  <div class="home-success-header">
                    <div class="home-success-icon">✓</div>
                    <div>
                      <h3 class="home-success-title">{done.capability ? copy.successTitleCap : copy.successTitleData}</h3>
                      <p class="body-text home-success-body">{copy.successBody}</p>
                    </div>
                  </div>

                  <div class="home-success-grid">
                    {resultRows.map(row => (
                      <div key={row.label} class="home-success-row">
                        <span class="label">{row.label}</span>
                        <span class={`home-success-value ${row.label === _['id'] || row.label === copy.summaryHash ? 'mono' : ''}`}>
                          {row.value}
                        </span>
                      </div>
                    ))}
                  </div>

                  <div class="home-success-actions">
                    <button class="btn btn-primary" onClick={() => go('mydata')}>
                      {_['view-mydata']}
                    </button>
                    <button class="btn btn-ghost" onClick={() => go('explore')}>
                      {_['nav-explore']}
                    </button>
                    <button class="btn btn-ghost" onClick={handleCopyAssetId}>
                      {_['copy']}
                    </button>
                    <button class="btn btn-ghost" onClick={() => setDone(null)}>
                      {_['again']}
                    </button>
                  </div>
                </div>
              ) : (
                <div class="home-register-console">
                  <div class="home-mode-switch" role="tablist" aria-label={copy.registerTitle}>
                    <button
                      role="tab"
                      aria-selected={mode === 'data'}
                      class={`home-mode-tab ${mode === 'data' ? 'active' : ''}`}
                      onClick={() => setMode('data')}
                    >
                      {_['register-data']}
                    </button>
                    <span class="home-mode-sep" aria-hidden="true">/</span>
                    <button
                      role="tab"
                      aria-selected={mode === 'capability'}
                      class={`home-mode-tab ${mode === 'capability' ? 'active' : ''}`}
                      onClick={() => setMode('capability')}
                    >
                      {_['publish-cap']}
                    </button>
                  </div>

                  <RegisterForm mode={mode} onSuccess={handleSuccess} />
                </div>
              )}
            </>
          )}
        </section>

        <aside class="home-side-rail">
          <section class="home-briefing shell-panel">
            <span class="label">{copy.checklistTitle}</span>
            <h2 class="home-panel-title">{copy.checklistTitle}</h2>
            <p class="body-text home-panel-body">{copy.checklistBody}</p>

            <div class="home-briefing-list">
              <div class="home-briefing-item">
                <span class="home-briefing-marker">01</span>
                <p>{copy.checklistWallet}</p>
              </div>
              <div class="home-briefing-item">
                <span class="home-briefing-marker">02</span>
                <p>{copy.checklistFunds}</p>
              </div>
              <div class="home-briefing-item">
                <span class="home-briefing-marker">03</span>
                <p>{copy.checklistRegister}</p>
              </div>
            </div>
          </section>

          <section class="home-destinations shell-panel">
            <span class="label">{copy.destinationsTitle}</span>
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
          </section>
        </aside>
      </div>
    </div>
  );
}
