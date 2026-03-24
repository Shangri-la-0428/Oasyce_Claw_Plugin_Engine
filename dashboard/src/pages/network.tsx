/**
 * Network — 节点身份、AI 算力配置、角色管理、水印工具
 * Sections are collapsible to reduce visual overload.
 * Heavy independent sections extracted to sub-components to reduce re-render scope.
 */
import { useEffect, useState, useRef } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n, identity, loadIdentity, walletAddress } from '../store/ui';
import { fmtDate } from '../utils';
import { safeNum, safePct } from '../utils';
import { useChain } from '../hooks/useChain';
import { getValidators, type Validator } from '../api/chain';
import { Section } from '../components/section';
import { GovernanceSection } from '../components/network/governance';
import { WatermarkSection } from '../components/network/watermark';
import { FingerprintsSection } from '../components/network/fingerprints';
import { ContributionSection } from '../components/network/contribution';
import { LeakageSection } from '../components/network/leakage';
import { CacheSection } from '../components/network/cache';
import { FeedbackSection } from '../components/network/feedback';
import './network.css';

type CsAction = null | 'delegate' | 'undelegate';

interface ConsensusStatus {
  current_epoch: number;
  current_slot: number;
  slots_per_epoch: number;
  active_validators: number;
  total_staked: number;
  time_until_next_epoch: number;
}

interface NodeRole {
  node_id: string;
  public_key: string;
  roles: string[];
  validator_stake: number;
  arbitrator_tags: string[];
  api_provider: string;
  api_key_set: boolean;
  api_endpoint: string;
  chain_height: number;
  peers: number;
}

interface NetworkProps { subpath?: string; }

export default function Network({ subpath }: NetworkProps) {
  const mountedRef = useRef(true);
  const busyRef = useRef(false);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const [nodeIdentity, setNodeIdentity] = useState<any>(null);
  const [nodeRole, setNodeRole] = useState<NodeRole | null>(null);
  const [loading, setLoading] = useState(true);
  const [showPubkey, setShowPubkey] = useState(false);
  const [showApiKey, setShowApiKey] = useState(false);

  // Role action state
  const [rolePanel, setRolePanel] = useState<null | 'validator' | 'arbitrator'>(null);
  const [roleAction, setRoleAction] = useState(false);
  const [stakeAmount, setStakeAmount] = useState('');
  const [arbTags, setArbTags] = useState('');

  // AI provider config
  const [apiProvider, setApiProvider] = useState('claude');
  const [apiKey, setApiKey] = useState('');
  const [apiEndpoint, setApiEndpoint] = useState('');
  const [savingKey, setSavingKey] = useState(false);

  // Work stats
  const [workStats, setWorkStats] = useState<any>(null);
  const [workTasks, setWorkTasks] = useState<any[]>([]);

  // Consensus state
  const [consensus, setConsensus] = useState<ConsensusStatus | null>(null);
  const [csAction, setCsAction] = useState<CsAction>(null);
  const [csValidatorId, setCsValidatorId] = useState('');
  const [csAmount, setCsAmount] = useState('');
  const [csSubmitting, setCsSubmitting] = useState(false);

  // Wallet export/import state
  const [showImport, setShowImport] = useState(false);
  const [importData, setImportData] = useState('');
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);

  // Reputation state
  const [reputation, setReputation] = useState<number | null>(null);

  // Cosmos chain connectivity
  const chain = useChain(true);
  const [cosmosValidators, setCosmosValidators] = useState<Validator[]>([]);
  const [cosmosValLoading, setCosmosValLoading] = useState(false);

  // Fetch Cosmos validators when chain becomes available
  useEffect(() => {
    if (!chain.isChainConnected) { setCosmosValidators([]); return; }
    let cancelled = false;
    setCosmosValLoading(true);
    getValidators('BOND_STATUS_BONDED')
      .then(res => { if (!cancelled) setCosmosValidators(res.validators || []); })
      .catch(() => { if (!cancelled) setCosmosValidators([]); })
      .finally(() => { if (!cancelled) setCosmosValLoading(false); });
    return () => { cancelled = true; };
  }, [chain.isChainConnected, chain.blockHeight]);

  const _ = i18n.value;

  const fetchData = async () => {
    setLoading(true);
    const [idRes, roleRes, statsRes, tasksRes, csRes] = await Promise.all([
      get('/identity'),
      get<NodeRole>('/node/role'),
      get<any>('/work/stats'),
      get<any>('/work/tasks?limit=5'),
      get<ConsensusStatus>('/consensus/status'),
    ]);
    if (!mountedRef.current) return;
    if (idRes.success && idRes.data) setNodeIdentity(idRes.data);
    if (roleRes.success && roleRes.data) {
      setNodeRole(roleRes.data);
      if (roleRes.data.api_provider) setApiProvider(roleRes.data.api_provider);
      if (roleRes.data.api_endpoint) setApiEndpoint(roleRes.data.api_endpoint);
    }
    if (statsRes.success && statsRes.data) setWorkStats(statsRes.data);
    if (tasksRes.success && tasksRes.data?.tasks) setWorkTasks(tasksRes.data.tasks);
    if (csRes.success && csRes.data) setConsensus(csRes.data);
    setLoading(false);
  };

  useEffect(() => {
    let cancelled = false;
    const doFetch = async () => {
      setLoading(true);
      const [idRes, roleRes, statsRes, tasksRes, csRes] = await Promise.all([
        get('/identity'),
        get<NodeRole>('/node/role'),
        get<any>('/work/stats'),
        get<any>('/work/tasks?limit=5'),
        get<ConsensusStatus>('/consensus/status'),
      ]);
      if (cancelled) return;
      if (idRes.success && idRes.data) setNodeIdentity(idRes.data);
      if (roleRes.success && roleRes.data) {
        setNodeRole(roleRes.data);
        if (roleRes.data.api_provider) setApiProvider(roleRes.data.api_provider);
        if (roleRes.data.api_endpoint) setApiEndpoint(roleRes.data.api_endpoint);
      }
      if (statsRes.success && statsRes.data) setWorkStats(statsRes.data);
      if (tasksRes.success && tasksRes.data?.tasks) setWorkTasks(tasksRes.data.tasks);
      if (csRes.success && csRes.data) setConsensus(csRes.data);
      setLoading(false);
    };
    doFetch();
    loadIdentity();
    const pollTimer = setInterval(async () => {
      const csRes = await get<ConsensusStatus>('/consensus/status');
      if (cancelled) return;
      if (csRes.success && csRes.data) setConsensus(csRes.data);
    }, 30_000);
    return () => { cancelled = true; clearInterval(pollTimer); };
  }, []);

  // Load reputation from staking if not in nodeRole
  useEffect(() => {
    if ((nodeRole as any)?.reputation !== undefined) {
      setReputation((nodeRole as any).reputation);
      return;
    }
    if (!nodeRole) return;
    let cancelled = false;
    get<any>('/staking').then(res => {
      if (!cancelled && res.success && res.data?.reputation !== undefined) {
        setReputation(res.data.reputation);
      }
    }).catch(() => {});
    return () => { cancelled = true; };
  }, [nodeRole]);

  const copyText = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      showToast(label + ' ' + _['copied'], 'success');
    } catch {
      showToast(_['error-generic'], 'error');
    }
  };

  const isValidator = nodeRole?.roles?.includes('validator') ?? false;
  const isArbitrator = nodeRole?.roles?.includes('arbitrator') ?? false;
  const hasApiKey = nodeRole?.api_key_set ?? false;

  const saveApiKey = async () => {
    if (busyRef.current) return;
    if (!apiKey.trim() && !apiEndpoint.trim()) return;
    busyRef.current = true;
    setSavingKey(true);
    try {
      const res = await post<any>('/node/api-key', {
        api_provider: apiProvider,
        api_key: apiKey.trim() || undefined,
        api_endpoint: apiEndpoint.trim() || undefined,
      });
      if (res.success && res.data?.ok) {
        showToast(_['net-key-saved'], 'success');
        setApiKey('');
        fetchData();
      } else {
        showToast(res.error || res.data?.error || _['error-generic'], 'error');
      }
    } finally {
      setSavingKey(false);
      busyRef.current = false;
    }
  };

  const becomeValidator = async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setRoleAction(true);
    try {
      const body: Record<string, string | number> = {};
      if (stakeAmount) body.amount = parseFloat(stakeAmount);
      if (apiKey.trim()) { body.api_key = apiKey.trim(); body.api_provider = apiProvider; }
      if (apiEndpoint.trim()) body.api_endpoint = apiEndpoint.trim();
      const res = await post<{ ok?: boolean; error?: string }>('/node/become-validator', body);
      if (res.success && res.data?.ok) {
        showToast(_['net-role-validator-ok'], 'success');
        setStakeAmount(''); setApiKey('');
        fetchData();
      } else {
        showToast(res.error || res.data?.error || _['error-generic'], 'error');
      }
    } finally {
      setRoleAction(false);
      busyRef.current = false;
    }
  };

  const becomeArbitrator = async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setRoleAction(true);
    try {
      const body: Record<string, string | number> = {};
      if (arbTags.trim()) body.tags = arbTags.trim();
      if (apiKey.trim()) { body.api_key = apiKey.trim(); body.api_provider = apiProvider; }
      if (apiEndpoint.trim()) body.api_endpoint = apiEndpoint.trim();
      const res = await post<{ ok?: boolean; error?: string }>('/node/become-arbitrator', body);
      if (res.success && res.data?.ok) {
        showToast(_['net-role-arbitrator-ok'], 'success');
        setArbTags(''); setApiKey('');
        fetchData();
      } else {
        showToast(res.error || res.data?.error || _['error-generic'], 'error');
      }
    } finally {
      setRoleAction(false);
      busyRef.current = false;
    }
  };

  if (loading) {
    return (
      <div class="page">
        <h1 class="label">{_['network']}</h1>
        <div class="skeleton skeleton-lg" />
      </div>
    );
  }

  const pubkey = nodeIdentity?.public_key || nodeRole?.public_key || '';
  const nodeId = nodeIdentity?.node_id || nodeRole?.node_id || pubkey.slice(0, 16);

  // Provider select helper
  const providerSelect = (
    <select class="input" value={apiProvider} onChange={e => setApiProvider((e.target as HTMLSelectElement).value)}>
      <option value="claude">Anthropic Claude</option>
      <option value="openai">OpenAI</option>
      <option value="local">Local Model</option>
      <option value="ollama">Ollama</option>
      <option value="custom">Custom Endpoint</option>
    </select>
  );

  const apiKeyInput = (
    <div class="net-key-field">
      <input class="input" type={showApiKey ? 'text' : 'password'} value={apiKey}
        onInput={e => setApiKey((e.target as HTMLInputElement).value)}
        placeholder={hasApiKey ? _['net-key-placeholder-set'] : _['net-key-placeholder']} />
      <button class="btn-copy net-toggle" onClick={() => setShowApiKey(!showApiKey)}>
        {showApiKey ? _['net-hide'] : _['net-show']}
      </button>
    </div>
  );

  const endpointInput = (apiProvider === 'local' || apiProvider === 'ollama' || apiProvider === 'custom') ? (
    <input class="input" value={apiEndpoint}
      onInput={e => setApiEndpoint((e.target as HTMLInputElement).value)}
      placeholder={apiProvider === 'ollama' ? 'http://localhost:11434' : _['net-endpoint-placeholder']} />
  ) : null;

  return (
    <div class="page">
      <div class="spacer-48" />

      {/* Hero */}
      <div class="net-hero">
        <h1 class="display">
          <span class="net-hero-light">{_['net-hero-light']}</span>
          <br />
          <strong>{_['net-hero-bold']}</strong>
        </h1>
        <p class="body-text mt-16">{_['net-hero-sub']}</p>
      </div>

      <div class="spacer-48" />

      {/* ── 身份 — flat, no card ── */}
      {pubkey ? (
        <div class="mb-24">
          <div class="label">{_['net-identity']}</div>

          <div class="kv">
            <span class="kv-key">{_['net-node-id']}</span>
            <span class="kv-val mono row gap-8">
              <span>{nodeId}</span>
              <button class="btn-copy" onClick={() => copyText(nodeId, 'Node ID')}>{_['copy']}</button>
            </span>
          </div>

          <div class="kv">
            <span class="kv-key">{_['net-pubkey']}</span>
            <span class="kv-val mono row gap-8">
              <span>{showPubkey ? pubkey : '••••' + pubkey.slice(-8)}</span>
              <button class="btn-copy net-toggle" onClick={() => setShowPubkey(!showPubkey)}>
                {showPubkey ? _['net-hide'] : _['net-show']}
              </button>
              <button class="btn-copy" onClick={() => copyText(pubkey, _['net-pubkey'])}>{_['copy']}</button>
            </span>
          </div>

          {/* Wallet address */}
          {identity.value?.exists ? (
            <div class="kv">
              <span class="kv-key">{_['wallet']}</span>
              <span class="kv-val mono row gap-8">
                <span>{identity.value.address.slice(0, 16)}...{identity.value.address.slice(-8)}</span>
                <button class="btn-copy" onClick={() => copyText(identity.value!.address, 'Wallet')}>{_['copy']}</button>
              </span>
            </div>
          ) : (
            <div class="kv">
              <span class="kv-key">{_['wallet']}</span>
              <span class="kv-val row gap-8">
                <span class="caption fg-muted">{_['no-key']}</span>
                <button class="btn btn-sm btn-ghost" onClick={async () => {
                  const res = await post<any>('/identity/create', {});
                  if (res.success && res.data?.ok) {
                    showToast(_['wallet-created'], 'success');
                    loadIdentity();
                    fetchData();
                  } else {
                    showToast(res.error || res.data?.error || _['error-generic'], 'error');
                  }
                }}>{_['create-wallet']}</button>
              </span>
            </div>
          )}

          {nodeIdentity?.created_at && (
            <div class="kv">
              <span class="kv-key">{_['net-created']}</span>
              <span class="kv-val">
                <time dateTime={new Date(nodeIdentity.created_at * 1000).toISOString()}>
                  {fmtDate(nodeIdentity.created_at, 'date')}
                </time>
              </span>
            </div>
          )}

          {nodeRole && (
            <>
              <div class="kv">
                <span class="kv-key">{_['net-chain-height']}</span>
                <span class="kv-val mono">{nodeRole.chain_height}</span>
              </div>
              <div class="kv">
                <span class="kv-key">{_['net-peers']}</span>
                <span class="kv-val mono">{nodeRole.peers}</span>
              </div>
              {reputation !== null && (
                <div class="kv">
                  <span class="kv-key">{_['node-reputation']}</span>
                  <span class="kv-val mono">{reputation}</span>
                </div>
              )}
            </>
          )}

          {/* Wallet Export / Import */}
          <div class="row gap-8 mt-12">
            <button class="btn btn-sm btn-ghost" disabled={exporting} onClick={async () => {
              setExporting(true);
              const res = await post<any>('/identity/export', {});
              if (res.success && res.data) {
                const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'oasyce-wallet.json';
                a.click();
                URL.revokeObjectURL(url);
                showToast(_['wallet-exported'], 'success');
              } else {
                showToast(res.error || _['error-generic'], 'error');
              }
              setExporting(false);
            }}>
              {exporting ? '...' : _['wallet-export']}
            </button>
            <button class="btn btn-sm btn-ghost" onClick={() => setShowImport(!showImport)}>
              {_['wallet-import']}
            </button>
          </div>
          {showImport && (
            <div class="net-tool-form mt-12">
              <p class="caption mb-8">{_['wallet-import-hint']}</p>
              <textarea class="input" rows={4} value={importData}
                onInput={e => setImportData((e.target as HTMLTextAreaElement).value)}
                placeholder={_['wallet-import-desc']} />
              <button class="btn btn-primary btn-full mt-8" disabled={importing || !importData.trim()}
                onClick={async () => {
                  setImporting(true);
                  const res = await post<any>('/identity/import', { key_data: importData.trim() });
                  if (res.success && res.data?.ok) {
                    showToast(_['wallet-imported'], 'success');
                    setShowImport(false);
                    setImportData('');
                    loadIdentity();
                    fetchData();
                  } else {
                    showToast(res.error || res.data?.error || _['error-generic'], 'error');
                  }
                  setImporting(false);
                }}>
                {importing ? '...' : _['wallet-import']}
              </button>
            </div>
          )}
        </div>
      ) : (
        <div class="mb-24">
          <div class="label">{_['net-identity']}</div>
          {identity.value?.exists ? (
            <>
              <div class="kv">
                <span class="kv-key">{_['wallet']}</span>
                <span class="kv-val mono row gap-8">
                  <span>{identity.value.address.slice(0, 16)}...{identity.value.address.slice(-8)}</span>
                  <button class="btn-copy" onClick={() => copyText(identity.value!.address, 'Wallet')}>{_['copy']}</button>
                </span>
              </div>
              <p class="caption mt-8">{_['net-init-hint']}</p>
            </>
          ) : (
            <>
              <p class="body-text fg-muted">{_['net-no-identity']}</p>
              <p class="caption mt-8">{_['net-init-hint']}</p>
              <button class="btn btn-primary btn-sm mt-12" onClick={async () => {
                const res = await post<any>('/identity/create', {});
                if (res.success && res.data?.ok) {
                  showToast(_['wallet-created'], 'success');
                  loadIdentity();
                  fetchData();
                } else {
                  showToast(res.error || res.data?.error || _['error-generic'], 'error');
                }
              }}>{_['create-wallet']}</button>
            </>
          )}
          <button class="btn btn-ghost btn-sm mt-12" onClick={fetchData}>{_['net-retry']}</button>
        </div>
      )}

      {/* ═══ Configuration ═══ */}
      <div class="label net-cat-label">{_['net-cat-config']}</div>

      {/* ── AI 算力配置 ── */}
      <Section id="ai" title={_['net-ai']} desc={_['net-ai-desc']} forceOpen={subpath === 'ai'}>
        {/* 当前状态 */}
        {hasApiKey && (
          <div class="net-role-badge mb-16 net-role-badge-active">
            <span class="net-role-badge-icon net-role-badge-icon-active">✓</span>
            <div>
              <div class="net-role-badge-title">{_['net-key-active']}</div>
              <div class="caption">
                {nodeRole?.api_provider === 'claude' && 'Anthropic Claude'}
                {nodeRole?.api_provider === 'openai' && 'OpenAI'}
                {nodeRole?.api_provider === 'local' && 'Local Model'}
                {nodeRole?.api_provider === 'ollama' && 'Ollama'}
                {nodeRole?.api_provider === 'custom' && 'Custom'}
                {!nodeRole?.api_provider && '—'}
                {nodeRole?.api_endpoint ? ` · ${nodeRole.api_endpoint}` : ''}
              </div>
            </div>
          </div>
        )}

        <div class="net-explain mb-16">
          <div class="net-explain-title">{_['net-ai-what']}</div>
          <p class="caption">{_['net-ai-what-body']}</p>
          <ul class="net-explain-list caption">
            <li>{_['net-ai-use-1']}</li>
            <li>{_['net-ai-use-2']}</li>
            <li>{_['net-ai-use-3']}</li>
          </ul>
          <div class="net-explain-title mt-12">{_['net-ai-supported']}</div>
          <p class="caption">{_['net-ai-supported-body']}</p>
        </div>

        <div class="net-tool-form net-tool-form-flush">
          <label class="label">{_['net-ai-provider']}</label>
          {providerSelect}
          <label class="label">{_['net-ai-key']}</label>
          {apiKeyInput}
          {endpointInput && (
            <>
              <label class="label">{_['net-ai-endpoint']}</label>
              {endpointInput}
            </>
          )}
          <button class="btn btn-primary btn-full" onClick={saveApiKey} disabled={savingKey || (!apiKey.trim() && !apiEndpoint.trim())}>
            {savingKey ? '...' : (hasApiKey ? _['net-key-update'] : _['net-key-save'])}
          </button>
        </div>
      </Section>

      {/* ── 节点角色 — collapsible, default open ── */}
      <Section id="role" title={_['net-role']} desc={_['net-role-desc']} forceOpen={subpath === 'role'}>
        {/* 当前角色 */}
        {(isValidator || isArbitrator) && (
          <div class="net-roles-current mb-16">
            {isValidator && (
              <div class="net-role-badge net-role-validator">
                <span class="net-role-badge-icon">V</span>
                <div>
                  <div class="net-role-badge-title">{_['net-role-validator']}</div>
                  <div class="caption">{_['net-staked']}: {nodeRole?.validator_stake ?? 0} OAS</div>
                </div>
              </div>
            )}
            {isArbitrator && (
              <div class="net-role-badge net-role-arbitrator">
                <span class="net-role-badge-icon">A</span>
                <div>
                  <div class="net-role-badge-title">{_['net-role-arbitrator']}</div>
                  <div class="caption">{(nodeRole?.arbitrator_tags ?? []).join(', ')}</div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 成为验证者 */}
        {!isValidator && (
          <div class="net-tools">
            <button class={`nav-item ${rolePanel === 'validator' ? 'nav-item-active' : ''}`}
              onClick={() => setRolePanel(rolePanel === 'validator' ? null : 'validator')}>
              <span class="nav-item-title">{_['net-become-validator']} {rolePanel === 'validator' ? '↓' : '→'}</span>
              <span class="nav-item-desc">{_['net-become-validator-desc']}</span>
            </button>
            {rolePanel === 'validator' && (
              <div class="net-tool-form">
                <div class="net-explain">
                  <div class="net-explain-title">{_['net-val-what']}</div>
                  <p class="caption">{_['net-val-what-body']}</p>
                  <div class="net-explain-title mt-12">{_['net-val-earn']}</div>
                  <ul class="net-explain-list caption">
                    <li>{_['net-val-earn-1']}</li>
                    <li>{_['net-val-earn-2']}</li>
                    <li>{_['net-val-earn-3']}</li>
                  </ul>
                  <div class="net-explain-title mt-12">{_['net-val-need']}</div>
                  <ul class="net-explain-list caption">
                    <li>{_['net-val-need-1']}</li>
                    <li>{_['net-val-need-2']}</li>
                    <li>{_['net-val-need-3']}</li>
                  </ul>
                </div>
                {!hasApiKey && (
                  <div class="net-warn caption">{_['net-key-required']}</div>
                )}
                <div class="caption">{_['net-validator-min']}: 10,000 OAS</div>
                <input class="input" type="number" value={stakeAmount}
                  onInput={e => setStakeAmount((e.target as HTMLInputElement).value)}
                  placeholder={_['stake-amount']} />
                <button class="btn btn-primary btn-full" onClick={becomeValidator} disabled={roleAction}>
                  {roleAction ? _['staking'] : _['net-become-validator']}
                </button>
              </div>
            )}
          </div>
        )}

        {/* 成为仲裁者 */}
        {!isArbitrator && (
          <div class="net-tools net-tools-gap">
            <button class={`nav-item ${rolePanel === 'arbitrator' ? 'nav-item-active' : ''}`}
              onClick={() => setRolePanel(rolePanel === 'arbitrator' ? null : 'arbitrator')}>
              <span class="nav-item-title">{_['net-become-arbitrator']} {rolePanel === 'arbitrator' ? '↓' : '→'}</span>
              <span class="nav-item-desc">{_['net-become-arbitrator-desc']}</span>
            </button>
            {rolePanel === 'arbitrator' && (
              <div class="net-tool-form">
                <div class="net-explain">
                  <div class="net-explain-title">{_['net-arb-what']}</div>
                  <p class="caption">{_['net-arb-what-body']}</p>
                  <div class="net-explain-title mt-12">{_['net-arb-earn']}</div>
                  <ul class="net-explain-list caption">
                    <li>{_['net-arb-earn-1']}</li>
                    <li>{_['net-arb-earn-2']}</li>
                  </ul>
                  <div class="net-explain-title mt-12">{_['net-arb-need']}</div>
                  <ul class="net-explain-list caption">
                    <li>{_['net-arb-need-1']}</li>
                    <li>{_['net-arb-need-2']}</li>
                  </ul>
                </div>
                {!hasApiKey && (
                  <div class="net-warn caption">{_['net-key-required']}</div>
                )}
                <input class="input" value={arbTags}
                  onInput={e => setArbTags((e.target as HTMLInputElement).value)}
                  placeholder={_['net-arb-tags-hint']} />
                <button class="btn btn-primary btn-full" onClick={becomeArbitrator} disabled={roleAction}>
                  {roleAction ? '...' : _['net-become-arbitrator']}
                </button>
              </div>
            )}
          </div>
        )}

        {!isValidator && !isArbitrator && rolePanel === null && (
          <div class="caption fg-muted mt-8">{_['net-role-none']}</div>
        )}
      </Section>

      {/* ═══ Network & Consensus ═══ */}
      <div class="label net-cat-label">{_['net-cat-chain']}</div>

      {/* ── 工作收益 — collapsible, default collapsed ── */}
      {(isValidator || isArbitrator) && (
        <Section id="work" title={_['net-work']} desc={_['net-work-desc']} forceOpen={subpath === 'work'}>
          {workStats?.worker ? (
            <div>
              <div class="kv">
                <span class="kv-key">{_['net-work-total']}</span>
                <span class="kv-val mono">{workStats.worker.total_tasks}</span>
              </div>
              <div class="kv">
                <span class="kv-key">{_['net-work-settled']}</span>
                <span class="kv-val mono">{workStats.worker.settled}</span>
              </div>
              <div class="kv">
                <span class="kv-key">{_['net-work-earned']}</span>
                <span class="kv-val mono color-green">{safeNum(workStats.worker.total_earned, 4)} OAS</span>
              </div>
              <div class="kv">
                <span class="kv-key">{_['net-work-quality']}</span>
                <span class="kv-val mono">{safePct(workStats.worker.avg_quality)}</span>
              </div>
              <div class="kv">
                <span class="kv-key">{_['net-work-failed']}</span>
                <span class="kv-val mono">{workStats.worker.failed}</span>
              </div>
            </div>
          ) : (
            <div class="caption fg-muted">
              <div class="mb-4">{_['net-work-no-tasks']}</div>
              <div>{_['net-work-no-tasks-hint']}</div>
            </div>
          )}

          {workTasks.length > 0 && (
            <div class="net-work-recent-wrap">
              <div class="label-inline mb-8">{_['net-work-recent']}</div>
              {workTasks.map((t: { task_id: string; task_type: string; status: string; final_value?: number }) => (
                <div key={t.task_id} class="kv kv-sm">
                  <span class="kv-key mono kv-key-xs">{t.task_id.slice(0, 12)}</span>
                  <span class="kv-val">
                    <span>{_[`net-work-type-${t.task_type}`] || t.task_type}</span>
                    {' · '}
                    <span class={t.status === 'settled' ? 'color-green' : ''}>{t.status}</span>
                    {t.final_value != null && t.final_value > 0 && <span class="mono"> &middot; {safeNum(t.final_value)} OAS</span>}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Section>
      )}

      {/* ── Cosmos Chain Info — shown when chain REST API is available ── */}
      <Section
        id="cosmos-chain"
        title={_['net-cosmos']}
        desc={chain.isChainConnected ? (_['net-cosmos-connected'] || '').replace('{height}', String(chain.blockHeight ?? '...')) : _['net-cosmos-checking']}
        defaultOpen={chain.isChainConnected}
        forceOpen={subpath === 'chain'}
      >
        {chain.loading && !chain.isChainConnected && (
          <div class="caption fg-muted">{_['net-cosmos-connecting']}</div>
        )}

        {!chain.loading && !chain.isChainConnected && (
          <div>
            <div class="caption fg-muted mb-8">
              {_['net-cosmos-unreachable']}
            </div>
            {chain.error && <div class="caption fg-muted">{_['net-cosmos-error']}: {chain.error}</div>}
            <button class="btn btn-ghost btn-sm mt-8" onClick={chain.refresh}>{_['net-cosmos-retry']}</button>
          </div>
        )}

        {chain.isChainConnected && (
          <div>
            {/* Node info */}
            {chain.chainInfo && (
              <>
                <div class="kv">
                  <span class="kv-key">{_['net-cosmos-chain-id']}</span>
                  <span class="kv-val mono">{chain.chainId}</span>
                </div>
                <div class="kv">
                  <span class="kv-key">{_['net-cosmos-node-id']}</span>
                  <span class="kv-val mono">{chain.chainInfo.default_node_info.default_node_id.slice(0, 16)}...</span>
                </div>
                <div class="kv">
                  <span class="kv-key">{_['net-cosmos-moniker']}</span>
                  <span class="kv-val">{chain.chainInfo.default_node_info.moniker}</span>
                </div>
                <div class="kv">
                  <span class="kv-key">{_['net-cosmos-sdk']}</span>
                  <span class="kv-val mono">{chain.chainInfo.application_version.cosmos_sdk_version}</span>
                </div>
                <div class="kv">
                  <span class="kv-key">{_['net-cosmos-app-ver']}</span>
                  <span class="kv-val mono">{chain.chainInfo.application_version.version}</span>
                </div>
              </>
            )}

            {/* Latest block */}
            {chain.latestBlock && (
              <>
                <div class="kv">
                  <span class="kv-key">{_['net-cosmos-block-height']}</span>
                  <span class="kv-val mono">{chain.latestBlock.block.header.height}</span>
                </div>
                <div class="kv">
                  <span class="kv-key">{_['net-cosmos-block-time']}</span>
                  <span class="kv-val">
                    <time dateTime={chain.latestBlock.block.header.time}>
                      {new Date(chain.latestBlock.block.header.time).toLocaleString()}
                    </time>
                  </span>
                </div>
                <div class="kv">
                  <span class="kv-key">{_['net-cosmos-block-hash']}</span>
                  <span class="kv-val mono">{chain.latestBlock.block_id.hash.slice(0, 16)}...</span>
                </div>
              </>
            )}

            {/* Cosmos validators */}
            <div class="label-inline mt-16 mb-8">{_['net-cosmos-validators']} ({cosmosValidators.length})</div>
            {cosmosValLoading && <div class="caption fg-muted">{_['net-cosmos-val-loading']}</div>}
            {!cosmosValLoading && cosmosValidators.length === 0 && (
              <div class="caption fg-muted">{_['net-cosmos-no-validators']}</div>
            )}
            {cosmosValidators.map((v) => (
              <div key={v.operator_address} class="kv kv-sm">
                <span class="kv-key">
                  {v.description.moniker || v.operator_address.slice(0, 12) + '...'}
                  {v.jailed && <span class="caption fg-muted"> ({_['net-cosmos-jailed']})</span>}
                </span>
                <span class="kv-val mono">
                  {(Number(v.tokens) / 1_000_000).toFixed(2)} OAS
                  <span class="caption fg-muted"> · {(Number(v.commission.commission_rates.rate) * 100).toFixed(1)}%</span>
                </span>
              </div>
            ))}

            <button class="btn btn-ghost btn-sm mt-12" onClick={chain.refresh}>{_['net-cosmos-refresh']}</button>
          </div>
        )}
      </Section>

      {/* ── 共识状态 — collapsible, default collapsed ── */}
      <Section id="consensus" title={_['net-consensus']} desc={_['net-consensus-desc']} forceOpen={subpath === 'consensus'}>
        {consensus ? (
          <div>
            <div class="kv">
              <span class="kv-key">{_['net-consensus-epoch']}</span>
              <span class="kv-val mono">{consensus.current_epoch}</span>
            </div>
            <div class="kv">
              <span class="kv-key">{_['net-consensus-slot']}</span>
              <span class="kv-val mono">{consensus.current_slot} / {consensus.slots_per_epoch}</span>
            </div>
            <div class="kv">
              <span class="kv-key">{_['net-consensus-validators']}</span>
              <span class="kv-val mono">{consensus.active_validators}</span>
            </div>
            <div class="kv">
              <span class="kv-key">{_['net-consensus-staked']}</span>
              <span class="kv-val mono">{safeNum(consensus.total_staked)} OAS</span>
            </div>
            <div class="kv">
              <span class="kv-key">{_['net-consensus-next-epoch']}</span>
              <span class="kv-val mono">{consensus.time_until_next_epoch}s</span>
            </div>
          </div>
        ) : (
          <div class="caption fg-muted">{_['net-consensus-loading'] || (_['net-consensus'] + '...')}</div>
        )}

        {/* Delegate / Undelegate actions */}
        <div class="net-tools net-tools-gap-md">
          <button class={`nav-item ${csAction === 'delegate' ? 'nav-item-active' : ''}`}
            onClick={() => { setCsAction(csAction === 'delegate' ? null : 'delegate'); setCsValidatorId(''); setCsAmount(''); }}>
            <span class="nav-item-title">{_['net-consensus-delegate']} {csAction === 'delegate' ? '↓' : '→'}</span>
            <span class="nav-item-desc">{_['net-consensus-delegate-desc']}</span>
          </button>
          {csAction === 'delegate' && (
            <div class="net-tool-form">
              <input class="input" value={csValidatorId}
                onInput={e => setCsValidatorId((e.target as HTMLInputElement).value)}
                placeholder={_['net-consensus-validator-id']} />
              <input class="input" type="number" value={csAmount}
                onInput={e => setCsAmount((e.target as HTMLInputElement).value)}
                placeholder={_['net-consensus-amount']} />
              <button class="btn btn-primary btn-full" disabled={csSubmitting || !csValidatorId.trim() || !csAmount.trim()}
                onClick={async () => {
                  setCsSubmitting(true);
                  const res = await post<any>('/consensus/delegate', { validator_id: csValidatorId.trim(), amount: parseFloat(csAmount) });
                  if (res.success && res.data?.ok) { showToast(_['net-consensus-delegate'] + ' OK', 'success'); fetchData(); }
                  else showToast(res.error || res.data?.error || _['error-generic'], 'error');
                  setCsSubmitting(false);
                }}>
                {csSubmitting ? _['net-consensus-submitting'] : _['net-consensus-submit']}
              </button>
            </div>
          )}

          <button class={`nav-item ${csAction === 'undelegate' ? 'nav-item-active' : ''}`}
            onClick={() => { setCsAction(csAction === 'undelegate' ? null : 'undelegate'); setCsValidatorId(''); setCsAmount(''); }}>
            <span class="nav-item-title">{_['net-consensus-undelegate']} {csAction === 'undelegate' ? '↓' : '→'}</span>
            <span class="nav-item-desc">{_['net-consensus-undelegate-desc']}</span>
          </button>
          {csAction === 'undelegate' && (
            <div class="net-tool-form">
              <input class="input" value={csValidatorId}
                onInput={e => setCsValidatorId((e.target as HTMLInputElement).value)}
                placeholder={_['net-consensus-validator-id']} />
              <input class="input" type="number" value={csAmount}
                onInput={e => setCsAmount((e.target as HTMLInputElement).value)}
                placeholder={_['net-consensus-amount']} />
              <button class="btn btn-primary btn-full" disabled={csSubmitting || !csValidatorId.trim() || !csAmount.trim()}
                onClick={async () => {
                  setCsSubmitting(true);
                  const res = await post<any>('/consensus/undelegate', { validator_id: csValidatorId.trim(), amount: parseFloat(csAmount) });
                  if (res.success && res.data?.ok) { showToast(_['net-consensus-undelegate'] + ' OK', 'success'); fetchData(); }
                  else showToast(res.error || res.data?.error || _['error-generic'], 'error');
                  setCsSubmitting(false);
                }}>
                {csSubmitting ? _['net-consensus-submitting'] : _['net-consensus-submit']}
              </button>
            </div>
          )}
        </div>
      </Section>

      {/* ═══ Tools ═══ */}
      <div class="label net-cat-label">{_['net-cat-tools']}</div>

      <WatermarkSection forceOpen={subpath === 'watermark'} />
      <FingerprintsSection forceOpen={subpath === 'fingerprints'} />
      <ContributionSection forceOpen={subpath === 'contribution'} />
      <LeakageSection forceOpen={subpath === 'leakage'} />
      <CacheSection forceOpen={subpath === 'cache'} />

      {/* ═══ Community ═══ */}
      <div class="label net-cat-label">{_['net-cat-community']}</div>

      <GovernanceSection forceOpen={subpath === 'governance'} />
      <FeedbackSection forceOpen={subpath === 'feedback'} />
    </div>
  );
}
