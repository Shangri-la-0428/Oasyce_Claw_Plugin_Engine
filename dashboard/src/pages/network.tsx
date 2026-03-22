/**
 * Network — 节点身份、AI 算力配置、角色管理、水印工具
 * Sections are collapsible to reduce visual overload.
 */
import { useEffect, useState } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n, identity, loadIdentity, walletAddress } from '../store/ui';
import { safeNum, safePct } from '../utils';
import { useChain } from '../hooks/useChain';
import { getValidators, type Validator } from '../api/chain';
import { Section } from '../components/section';
import './network.css';

type WmTool = null | 'embed' | 'extract' | 'trace';
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

/* Section component imported from ../components/section */

interface NetworkProps { subpath?: string; }

export default function Network({ subpath }: NetworkProps) {
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

  // Watermark tool state
  const [activeTool, setActiveTool] = useState<WmTool>(null);
  const [wmFilePath, setWmFilePath] = useState('');
  const [wmCallerId, setWmCallerId] = useState('');
  const [wmAssetId, setWmAssetId] = useState('');
  const [wmLoading, setWmLoading] = useState(false);
  const [wmResult, setWmResult] = useState<any>(null);

  // Wallet export/import state
  const [showImport, setShowImport] = useState(false);
  const [importData, setImportData] = useState('');
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);

  // Fingerprint list state
  const [fpAssetId, setFpAssetId] = useState('');
  const [fpRecords, setFpRecords] = useState<any[]>([]);
  const [fpLoading, setFpLoading] = useState(false);

  // Governance state
  const [proposals, setProposals] = useState<any[]>([]);
  const [proposalsLoading, setProposalsLoading] = useState(false);
  const [govAction, setGovAction] = useState<'propose' | 'vote' | null>(null);
  const [propTitle, setPropTitle] = useState('');
  const [propDesc, setPropDesc] = useState('');
  const [propDeposit, setPropDeposit] = useState('');
  const [govSubmitting, setGovSubmitting] = useState(false);
  const [govChainOnly, setGovChainOnly] = useState(false);
  const [govLoaded, setGovLoaded] = useState(false);

  // Reputation state
  const [reputation, setReputation] = useState<number | null>(null);

  // Contribution proof state
  const [cpFilePath, setCpFilePath] = useState('');
  const [cpCreatorKey, setCpCreatorKey] = useState('');
  const [cpSourceType, setCpSourceType] = useState('manual');
  const [cpProving, setCpProving] = useState(false);
  const [cpResult, setCpResult] = useState<any>(null);
  const [cpCertJson, setCpCertJson] = useState('');
  const [cpVerifyFile, setCpVerifyFile] = useState('');
  const [cpVerifying, setCpVerifying] = useState(false);
  const [cpVerifyResult, setCpVerifyResult] = useState<any>(null);

  // Leakage budget state
  const [lkAgentId, setLkAgentId] = useState('');
  const [lkAssetId, setLkAssetId] = useState('');
  const [lkChecking, setLkChecking] = useState(false);
  const [lkResult, setLkResult] = useState<any>(null);
  const [lkResetting, setLkResetting] = useState(false);

  // Cache management state
  const [cacheStats, setCacheStats] = useState<any>(null);
  const [cacheLoading, setCacheLoading] = useState(false);
  const [cachePurging, setCachePurging] = useState(false);
  const [cacheLoaded, setCacheLoaded] = useState(false);

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

  useEffect(() => { fetchData(); loadIdentity(); }, []);

  // Lazy-load governance proposals on mount
  useEffect(() => {
    if (govLoaded) return;
    setGovLoaded(true);
    setProposalsLoading(true);
    get<any>('/governance/proposals').then(res => {
      if (res.success && res.data) {
        setProposals(Array.isArray(res.data) ? res.data : (res.data.proposals || []));
      } else if (res.error && res.error.toLowerCase().includes('go chain')) {
        setGovChainOnly(true);
      }
      setProposalsLoading(false);
    }).catch(() => setProposalsLoading(false));
  }, []);

  // Lazy-load cache stats on mount
  useEffect(() => {
    if (cacheLoaded) return;
    setCacheLoaded(true);
    setCacheLoading(true);
    get<any>('/cache/stats').then(res => {
      if (res.success && res.data) setCacheStats(res.data);
      setCacheLoading(false);
    }).catch(() => setCacheLoading(false));
  }, []);

  // Load reputation from staking if not in nodeRole
  useEffect(() => {
    if ((nodeRole as any)?.reputation !== undefined) {
      setReputation((nodeRole as any).reputation);
    } else if (nodeRole) {
      get<any>('/staking').then(res => {
        if (res.success && res.data?.reputation !== undefined) {
          setReputation(res.data.reputation);
        }
      });
    }
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
    if (!apiKey.trim() && !apiEndpoint.trim()) return;
    setSavingKey(true);
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
    setSavingKey(false);
  };

  const becomeValidator = async () => {
    setRoleAction(true);
    const body: any = {};
    if (stakeAmount) body.amount = parseFloat(stakeAmount);
    if (apiKey.trim()) { body.api_key = apiKey.trim(); body.api_provider = apiProvider; }
    if (apiEndpoint.trim()) body.api_endpoint = apiEndpoint.trim();
    const res = await post<any>('/node/become-validator', body);
    if (res.success && res.data?.ok) {
      showToast(_['net-role-validator-ok'], 'success');
      setStakeAmount(''); setApiKey('');
      fetchData();
    } else {
      showToast(res.error || res.data?.error || _['error-generic'], 'error');
    }
    setRoleAction(false);
  };

  const becomeArbitrator = async () => {
    setRoleAction(true);
    const body: any = {};
    if (arbTags.trim()) body.tags = arbTags.trim();
    if (apiKey.trim()) { body.api_key = apiKey.trim(); body.api_provider = apiProvider; }
    if (apiEndpoint.trim()) body.api_endpoint = apiEndpoint.trim();
    const res = await post<any>('/node/become-arbitrator', body);
    if (res.success && res.data?.ok) {
      showToast(_['net-role-arbitrator-ok'], 'success');
      setArbTags(''); setApiKey('');
      fetchData();
    } else {
      showToast(res.error || res.data?.error || _['error-generic'], 'error');
    }
    setRoleAction(false);
  };

  // Watermark handlers
  const onEmbed = async () => {
    if (!wmFilePath.trim()) return;
    setWmLoading(true); setWmResult(null);
    const res = await post<any>('/fingerprint/embed', { file_path: wmFilePath.trim(), caller_id: wmCallerId.trim() || undefined });
    if (res.success && res.data) { setWmResult(res.data); showToast(_['wm-embed-btn'], 'success'); }
    else showToast(res.error || _['error-generic'], 'error');
    setWmLoading(false);
  };

  const onExtract = async () => {
    if (!wmFilePath.trim()) return;
    setWmLoading(true); setWmResult(null);
    const res = await post<any>('/fingerprint/extract', { file_path: wmFilePath.trim() });
    if (res.success && res.data) setWmResult(res.data);
    else showToast(res.error || _['error-generic'], 'error');
    setWmLoading(false);
  };

  const onTrace = async () => {
    if (!wmAssetId.trim()) return;
    setWmLoading(true); setWmResult(null);
    const res = await get<any>(`/fingerprint/distributions?asset_id=${encodeURIComponent(wmAssetId.trim())}`);
    if (res.success && res.data) setWmResult(res.data);
    else showToast(res.error || _['error-generic'], 'error');
    setWmLoading(false);
  };

  const selectTool = (tool: WmTool) => {
    setActiveTool(activeTool === tool ? null : tool);
    setWmResult(null); setWmFilePath(''); setWmCallerId(''); setWmAssetId('');
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

      {/* ── 身份卡片 — always visible ── */}
      {pubkey ? (
        <div class="card mb-24">
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
              <span class="kv-key">Wallet</span>
              <span class="kv-val mono row gap-8">
                <span>{identity.value.address.slice(0, 16)}...{identity.value.address.slice(-8)}</span>
                <button class="btn-copy" onClick={() => copyText(identity.value!.address, 'Wallet')}>{_['copy']}</button>
              </span>
            </div>
          ) : (
            <div class="kv">
              <span class="kv-key">Wallet</span>
              <span class="kv-val row gap-8">
                <span class="caption fg-muted">{_['no-key']}</span>
                <button class="btn btn-sm btn-ghost" onClick={async () => {
                  const res = await post<any>('/identity/create', {});
                  if (res.success && res.data?.ok) {
                    showToast('Wallet created', 'success');
                    loadIdentity();
                    fetchData();
                  } else {
                    showToast(res.error || res.data?.error || _['error-generic'], 'error');
                  }
                }}>Create Wallet</button>
              </span>
            </div>
          )}

          {nodeIdentity?.created_at && (
            <div class="kv">
              <span class="kv-key">{_['net-created']}</span>
              <span class="kv-val">{new Date(nodeIdentity.created_at * 1000).toLocaleDateString()}</span>
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
        <div class="card mb-24">
          <div class="label">{_['net-identity']}</div>
          {identity.value?.exists ? (
            <>
              <div class="kv">
                <span class="kv-key">Wallet</span>
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
                  showToast('Wallet created', 'success');
                  loadIdentity();
                  fetchData();
                } else {
                  showToast(res.error || res.data?.error || _['error-generic'], 'error');
                }
              }}>Create Wallet</button>
            </>
          )}
          <button class="btn btn-ghost btn-sm mt-12" onClick={fetchData}>{_['net-retry']}</button>
        </div>
      )}

      {/* ── AI 算力配置 — collapsible, default open ── */}
      <Section id="ai" title={_['net-ai']} desc={_['net-ai-desc']} defaultOpen={true} forceOpen={subpath === 'ai'}>
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
      <Section id="role" title={_['net-role']} desc={_['net-role-desc']} defaultOpen={true} forceOpen={subpath === 'role'}>
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
            <div class="caption fg-muted">{_['net-work-no-tasks']}</div>
          )}

          {workTasks.length > 0 && (
            <div class="net-work-recent-wrap">
              <div class="label-inline mb-8">{_['net-work-recent']}</div>
              {workTasks.map((t: any) => (
                <div key={t.task_id} class="kv kv-sm">
                  <span class="kv-key mono kv-key-xs">{t.task_id.slice(0, 12)}</span>
                  <span class="kv-val">
                    <span>{_[`net-work-type-${t.task_type}`] || t.task_type}</span>
                    {' · '}
                    <span class={t.status === 'settled' ? 'color-green' : ''}>{t.status}</span>
                    {t.final_value > 0 && <span class="mono"> &middot; {safeNum(t.final_value)} OAS</span>}
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
        title="Cosmos Chain"
        desc={chain.isChainConnected ? `Connected — Block #${chain.blockHeight ?? '...'}` : 'Checking chain...'}
        defaultOpen={chain.isChainConnected}
        forceOpen={subpath === 'chain'}
      >
        {chain.loading && !chain.isChainConnected && (
          <div class="caption fg-muted">Connecting to Cosmos chain REST API...</div>
        )}

        {!chain.loading && !chain.isChainConnected && (
          <div>
            <div class="caption fg-muted mb-8">
              Cosmos chain REST API is not reachable (localhost:1317).
              Showing Python backend data as fallback.
            </div>
            {chain.error && <div class="caption fg-muted">Error: {chain.error}</div>}
            <button class="btn btn-ghost btn-sm mt-8" onClick={chain.refresh}>Retry</button>
          </div>
        )}

        {chain.isChainConnected && (
          <div>
            {/* Node info */}
            {chain.chainInfo && (
              <>
                <div class="kv">
                  <span class="kv-key">Chain ID</span>
                  <span class="kv-val mono">{chain.chainId}</span>
                </div>
                <div class="kv">
                  <span class="kv-key">Node ID</span>
                  <span class="kv-val mono">{chain.chainInfo.default_node_info.default_node_id.slice(0, 16)}...</span>
                </div>
                <div class="kv">
                  <span class="kv-key">Moniker</span>
                  <span class="kv-val">{chain.chainInfo.default_node_info.moniker}</span>
                </div>
                <div class="kv">
                  <span class="kv-key">Cosmos SDK</span>
                  <span class="kv-val mono">{chain.chainInfo.application_version.cosmos_sdk_version}</span>
                </div>
                <div class="kv">
                  <span class="kv-key">App Version</span>
                  <span class="kv-val mono">{chain.chainInfo.application_version.version}</span>
                </div>
              </>
            )}

            {/* Latest block */}
            {chain.latestBlock && (
              <>
                <div class="kv">
                  <span class="kv-key">Block Height</span>
                  <span class="kv-val mono">{chain.latestBlock.block.header.height}</span>
                </div>
                <div class="kv">
                  <span class="kv-key">Block Time</span>
                  <span class="kv-val">{new Date(chain.latestBlock.block.header.time).toLocaleString()}</span>
                </div>
                <div class="kv">
                  <span class="kv-key">Block Hash</span>
                  <span class="kv-val mono">{chain.latestBlock.block_id.hash.slice(0, 16)}...</span>
                </div>
              </>
            )}

            {/* Cosmos validators */}
            <div class="label-inline mt-16 mb-8">Cosmos Validators ({cosmosValidators.length})</div>
            {cosmosValLoading && <div class="caption fg-muted">Loading validators...</div>}
            {!cosmosValLoading && cosmosValidators.length === 0 && (
              <div class="caption fg-muted">No bonded validators found.</div>
            )}
            {cosmosValidators.map((v) => (
              <div key={v.operator_address} class="kv kv-sm">
                <span class="kv-key">
                  {v.description.moniker || v.operator_address.slice(0, 12) + '...'}
                  {v.jailed && <span class="caption fg-muted"> (jailed)</span>}
                </span>
                <span class="kv-val mono">
                  {(Number(v.tokens) / 1_000_000).toFixed(2)} OAS
                  <span class="caption fg-muted"> · {(Number(v.commission.commission_rates.rate) * 100).toFixed(1)}%</span>
                </span>
              </div>
            ))}

            <button class="btn btn-ghost btn-sm mt-12" onClick={chain.refresh}>Refresh</button>
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

      {/* ── 水印工具 — collapsible, default collapsed ── */}
      <Section id="watermark" title={_['net-watermark']} desc={_['net-watermark-desc']} forceOpen={subpath === 'watermark'}>
        <div class="net-tools">
          <button class={`nav-item ${activeTool === 'embed' ? 'nav-item-active' : ''}`} onClick={() => selectTool('embed')}>
            <span class="nav-item-title">{_['net-embed']} {activeTool === 'embed' ? '↓' : '→'}</span>
            <span class="nav-item-desc">{_['net-embed-desc']}</span>
          </button>
          {activeTool === 'embed' && (
            <div class="net-tool-form">
              <input class="input" value={wmFilePath} onInput={e => setWmFilePath((e.target as HTMLInputElement).value)} placeholder={_['wm-file-path']} />
              <input class="input" value={wmCallerId} onInput={e => setWmCallerId((e.target as HTMLInputElement).value)} placeholder={_['wm-caller-id']} />
              <button class="btn btn-primary btn-full" onClick={onEmbed} disabled={wmLoading || !wmFilePath.trim()}>
                {wmLoading ? _['wm-embedding'] : _['wm-embed-btn']}
              </button>
              {wmResult && (
                <div class="net-tool-result">
                  {wmResult.watermarked_path && <div class="kv"><span class="kv-key">{_['wm-watermarked-path']}</span><span class="kv-val mono kv-val-xs">{wmResult.watermarked_path}</span></div>}
                  {wmResult.fingerprint && <div class="kv"><span class="kv-key">{_['wm-fingerprint']}</span><span class="kv-val mono kv-val-xs-nowrap">{wmResult.fingerprint.slice(0, 16)}…</span></div>}
                </div>
              )}
            </div>
          )}

          <button class={`nav-item ${activeTool === 'extract' ? 'nav-item-active' : ''}`} onClick={() => selectTool('extract')}>
            <span class="nav-item-title">{_['net-extract']} {activeTool === 'extract' ? '↓' : '→'}</span>
            <span class="nav-item-desc">{_['net-extract-desc']}</span>
          </button>
          {activeTool === 'extract' && (
            <div class="net-tool-form">
              <input class="input" value={wmFilePath} onInput={e => setWmFilePath((e.target as HTMLInputElement).value)} placeholder={_['wm-file-path']} />
              <button class="btn btn-primary btn-full" onClick={onExtract} disabled={wmLoading || !wmFilePath.trim()}>
                {wmLoading ? _['wm-extracting'] : _['wm-extract-btn']}
              </button>
              {wmResult && (
                <div class="net-tool-result">
                  {wmResult.fingerprint && <div class="kv"><span class="kv-key">{_['wm-fingerprint']}</span><span class="kv-val mono kv-val-xs-nowrap">{wmResult.fingerprint}</span></div>}
                  {wmResult.caller_id && <div class="kv"><span class="kv-key">{_['wm-caller']}</span><span class="kv-val mono">{wmResult.caller_id}</span></div>}
                  {wmResult.timestamp && <div class="kv"><span class="kv-key">{_['wm-timestamp']}</span><span class="kv-val">{new Date(wmResult.timestamp * 1000).toLocaleString()}</span></div>}
                  {!wmResult.fingerprint && !wmResult.caller_id && <div class="caption fg-muted">{_['wm-no-records']}</div>}
                </div>
              )}
            </div>
          )}

          <button class={`nav-item ${activeTool === 'trace' ? 'nav-item-active' : ''}`} onClick={() => selectTool('trace')}>
            <span class="nav-item-title">{_['net-trace']} {activeTool === 'trace' ? '↓' : '→'}</span>
            <span class="nav-item-desc">{_['net-trace-desc']}</span>
          </button>
          {activeTool === 'trace' && (
            <div class="net-tool-form">
              <input class="input" value={wmAssetId} onInput={e => setWmAssetId((e.target as HTMLInputElement).value)} placeholder={_['wm-asset-id']} />
              <button class="btn btn-primary btn-full" onClick={onTrace} disabled={wmLoading || !wmAssetId.trim()}>
                {wmLoading ? _['wm-listing'] : _['wm-list-btn']}
              </button>
              {wmResult && (
                <div class="net-tool-result">
                  {Array.isArray(wmResult.distributions) && wmResult.distributions.length > 0 ? (
                    wmResult.distributions.map((d: any, i: number) => (
                      <div key={i} class="kv">
                        <span class="kv-key mono kv-key-xs">{d.caller_id?.slice(0, 12) || '—'}</span>
                        <span class="kv-val">{d.timestamp ? new Date(d.timestamp * 1000).toLocaleString() : '—'}</span>
                      </div>
                    ))
                  ) : (
                    <div class="caption fg-muted">{_['wm-no-records']}</div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </Section>

      {/* ── Fingerprint List — collapsible ── */}
      <Section id="fingerprints" title={_['fingerprint-list']}>
        <div class="net-tool-form net-tool-form-flush">
          <input class="input" value={fpAssetId}
            onInput={e => setFpAssetId((e.target as HTMLInputElement).value)}
            placeholder={_['fingerprint-asset']} />
          <button class="btn btn-primary btn-full" disabled={fpLoading || !fpAssetId.trim()}
            onClick={async () => {
              setFpLoading(true);
              const res = await get<any>(`/fingerprints?asset_id=${encodeURIComponent(fpAssetId.trim())}`);
              if (res.success && res.data) {
                setFpRecords(Array.isArray(res.data) ? res.data : (res.data.records || []));
              } else {
                showToast(res.error || _['error-generic'], 'error');
                setFpRecords([]);
              }
              setFpLoading(false);
            }}>
            {fpLoading ? '...' : _['fingerprint-list']}
          </button>
        </div>
        {fpRecords.length > 0 ? (
          <div class="mt-12">
            {fpRecords.map((r: any, i: number) => (
              <div key={i} class="kv kv-sm">
                <span class="kv-key mono kv-key-xs">{(r.fingerprint || r.hash || '—').slice(0, 16)}…</span>
                <span class="kv-val">
                  <span class="mono">{r.caller || r.caller_id || '—'}</span>
                  {' · '}
                  <span>{r.timestamp ? new Date(r.timestamp * 1000).toLocaleString() : '—'}</span>
                </span>
              </div>
            ))}
          </div>
        ) : (
          fpAssetId && !fpLoading && <div class="caption fg-muted mt-8">{_['fingerprint-no-records']}</div>
        )}
      </Section>

      {/* ── Governance — collapsible ── */}
      <Section id="governance" title={_['governance']} desc={_['governance-desc']}>
        {govChainOnly && (
          <div class="caption fg-muted mb-12">{_['gov-chain-only']}</div>
        )}

        {proposalsLoading && <div class="caption fg-muted">{_['gov-proposals']}...</div>}

        {!proposalsLoading && !govChainOnly && proposals.length === 0 && (
          <div class="caption fg-muted mb-12">{_['gov-no-proposals']}</div>
        )}

        {proposals.length > 0 && (
          <div class="mb-16">
            <div class="label-inline mb-8">{_['gov-proposals']}</div>
            {proposals.map((p: any) => (
              <div key={p.proposal_id} class="card mb-8" style="padding: 12px;">
                <div class="kv">
                  <span class="kv-key">#{p.proposal_id}</span>
                  <span class="kv-val">{p.title}</span>
                </div>
                <div class="kv">
                  <span class="kv-key">{_['gov-status']}</span>
                  <span class="kv-val mono">{p.status}</span>
                </div>
                {p.description && (
                  <p class="caption mt-4">{p.description}</p>
                )}
                <div class="row gap-8 mt-8">
                  <button class="btn btn-sm btn-ghost" disabled={govSubmitting}
                    onClick={async () => {
                      setGovSubmitting(true);
                      const res = await post<any>('/governance/vote', { proposal_id: p.proposal_id, voter: walletAddress(), option: 'yes' });
                      if (res.success && res.data?.ok) showToast(_['gov-vote-success'], 'success');
                      else showToast(res.error || res.data?.error || _['error-generic'], 'error');
                      setGovSubmitting(false);
                    }}>
                    {_['gov-vote-yes']}
                  </button>
                  <button class="btn btn-sm btn-ghost" disabled={govSubmitting}
                    onClick={async () => {
                      setGovSubmitting(true);
                      const res = await post<any>('/governance/vote', { proposal_id: p.proposal_id, voter: walletAddress(), option: 'no' });
                      if (res.success && res.data?.ok) showToast(_['gov-vote-success'], 'success');
                      else showToast(res.error || res.data?.error || _['error-generic'], 'error');
                      setGovSubmitting(false);
                    }}>
                    {_['gov-vote-no']}
                  </button>
                  <button class="btn btn-sm btn-ghost" disabled={govSubmitting}
                    onClick={async () => {
                      setGovSubmitting(true);
                      const res = await post<any>('/governance/vote', { proposal_id: p.proposal_id, voter: walletAddress(), option: 'abstain' });
                      if (res.success && res.data?.ok) showToast(_['gov-vote-success'], 'success');
                      else showToast(res.error || res.data?.error || _['error-generic'], 'error');
                      setGovSubmitting(false);
                    }}>
                    {_['gov-vote-abstain']}
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Submit Proposal toggle */}
        <div class="net-tools">
          <button class={`nav-item ${govAction === 'propose' ? 'nav-item-active' : ''}`}
            onClick={() => setGovAction(govAction === 'propose' ? null : 'propose')}>
            <span class="nav-item-title">{_['gov-propose']} {govAction === 'propose' ? '↓' : '→'}</span>
          </button>
          {govAction === 'propose' && (
            <div class="net-tool-form">
              <input class="input" value={propTitle}
                onInput={e => setPropTitle((e.target as HTMLInputElement).value)}
                placeholder={_['gov-title']} />
              <textarea class="input" rows={3} value={propDesc}
                onInput={e => setPropDesc((e.target as HTMLTextAreaElement).value)}
                placeholder={_['gov-description']} />
              <input class="input" type="number" value={propDeposit}
                onInput={e => setPropDeposit((e.target as HTMLInputElement).value)}
                placeholder={_['gov-deposit']} />
              <button class="btn btn-primary btn-full" disabled={govSubmitting || !propTitle.trim()}
                onClick={async () => {
                  setGovSubmitting(true);
                  const res = await post<any>('/governance/propose', {
                    title: propTitle.trim(),
                    description: propDesc.trim(),
                    deposit: parseFloat(propDeposit) || 0,
                    proposer: walletAddress(),
                  });
                  if (res.success && res.data?.ok) {
                    showToast(_['gov-propose-success'], 'success');
                    setPropTitle(''); setPropDesc(''); setPropDeposit('');
                    setGovAction(null);
                    // Reload proposals
                    setProposalsLoading(true);
                    const pRes = await get<any>('/governance/proposals');
                    if (pRes.success && pRes.data) setProposals(Array.isArray(pRes.data) ? pRes.data : (pRes.data.proposals || []));
                    setProposalsLoading(false);
                  } else {
                    showToast(res.error || res.data?.error || _['error-generic'], 'error');
                  }
                  setGovSubmitting(false);
                }}>
                {govSubmitting ? _['gov-proposing'] : _['gov-propose']}
              </button>
            </div>
          )}
        </div>
      </Section>

      {/* ── Contribution Proof — collapsible ── */}
      <Section id="contribution" title={_['contribution']} desc={_['contribution-desc']} forceOpen={subpath === 'contribution'}>
        {/* Generate proof form */}
        <div class="net-tool-form net-tool-form-flush">
          <label class="label">{_['contribution-file']}</label>
          <input class="input" value={cpFilePath}
            onInput={e => setCpFilePath((e.target as HTMLInputElement).value)}
            placeholder={_['contribution-file']} />
          <label class="label">{_['contribution-creator']}</label>
          <input class="input" value={cpCreatorKey}
            onInput={e => setCpCreatorKey((e.target as HTMLInputElement).value)}
            placeholder={_['contribution-creator']} />
          <label class="label">{_['contribution-source']}</label>
          <select class="input" value={cpSourceType}
            onChange={e => setCpSourceType((e.target as HTMLSelectElement).value)}>
            <option value="manual">manual</option>
            <option value="tee_capture">tee_capture</option>
            <option value="api_log">api_log</option>
            <option value="sensor_sig">sensor_sig</option>
            <option value="git_commit">git_commit</option>
          </select>
          <button class="btn btn-primary btn-full" disabled={cpProving || !cpFilePath.trim()}
            onClick={async () => {
              setCpProving(true); setCpResult(null);
              const res = await post<any>('/contribution/prove', {
                file_path: cpFilePath.trim(),
                creator_key: cpCreatorKey.trim() || undefined,
                source_type: cpSourceType,
              });
              if (res.success && res.data) {
                setCpResult(res.data);
                showToast(_['contribution-prove-success'], 'success');
              } else {
                showToast(res.error || _['error-generic'], 'error');
              }
              setCpProving(false);
            }}>
            {cpProving ? _['contribution-proving'] : _['contribution-prove']}
          </button>
        </div>

        {cpResult && (
          <div class="net-tool-result mt-12">
            <div class="label-inline mb-8">{_['contribution-result']}</div>
            {cpResult.content_hash && (
              <div class="kv"><span class="kv-key">{_['contribution-content-hash']}</span><span class="kv-val mono kv-val-xs-nowrap">{cpResult.content_hash}</span></div>
            )}
            {cpResult.semantic_fingerprint && (
              <div class="kv"><span class="kv-key">{_['contribution-semantic']}</span><span class="kv-val mono kv-val-xs-nowrap">{cpResult.semantic_fingerprint}</span></div>
            )}
            {cpResult.timestamp && (
              <div class="kv"><span class="kv-key">{_['contribution-timestamp']}</span><span class="kv-val">{new Date(cpResult.timestamp * 1000).toLocaleString()}</span></div>
            )}
          </div>
        )}

        {/* Verify proof form */}
        <div class="net-tool-form net-tool-form-flush mt-16">
          <div class="label-inline mb-8">{_['contribution-verify']}</div>
          <label class="label">{_['contribution-certificate']}</label>
          <textarea class="input" rows={4} value={cpCertJson}
            onInput={e => setCpCertJson((e.target as HTMLTextAreaElement).value)}
            placeholder={_['contribution-certificate']} />
          <label class="label">{_['contribution-file']}</label>
          <input class="input" value={cpVerifyFile}
            onInput={e => setCpVerifyFile((e.target as HTMLInputElement).value)}
            placeholder={_['contribution-file']} />
          <button class="btn btn-primary btn-full" disabled={cpVerifying || !cpCertJson.trim()}
            onClick={async () => {
              setCpVerifying(true); setCpVerifyResult(null);
              let certData: any;
              try { certData = JSON.parse(cpCertJson.trim()); } catch {
                showToast('Invalid JSON', 'error');
                setCpVerifying(false);
                return;
              }
              const res = await post<any>('/contribution/verify', {
                certificate: certData,
                file_path: cpVerifyFile.trim() || undefined,
              });
              if (res.success && res.data) {
                setCpVerifyResult(res.data);
              } else {
                showToast(res.error || _['error-generic'], 'error');
              }
              setCpVerifying(false);
            }}>
            {cpVerifying ? _['contribution-verifying'] : _['contribution-verify']}
          </button>
        </div>

        {cpVerifyResult && (
          <div class="net-tool-result mt-12">
            <div class="kv">
              <span class="kv-key">{_['contribution-result']}</span>
              <span class={`kv-val mono ${cpVerifyResult.valid ? 'color-green' : 'color-red'}`}>
                {cpVerifyResult.valid ? _['contribution-valid'] : _['contribution-invalid']}
              </span>
            </div>
          </div>
        )}
      </Section>

      {/* ── Leakage Budget — collapsible ── */}
      <Section id="leakage" title={_['leakage']} desc={_['leakage-desc']} forceOpen={subpath === 'leakage'}>
        <div class="net-tool-form net-tool-form-flush">
          <label class="label">{_['leakage-agent']}</label>
          <input class="input" value={lkAgentId}
            onInput={e => setLkAgentId((e.target as HTMLInputElement).value)}
            placeholder={_['leakage-agent']} />
          <label class="label">{_['leakage-asset']}</label>
          <input class="input" value={lkAssetId}
            onInput={e => setLkAssetId((e.target as HTMLInputElement).value)}
            placeholder={_['leakage-asset']} />
          <div class="row gap-8">
            <button class="btn btn-primary grow" disabled={lkChecking || !lkAgentId.trim() || !lkAssetId.trim()}
              onClick={async () => {
                setLkChecking(true); setLkResult(null);
                const res = await get<any>(`/leakage?agent_id=${encodeURIComponent(lkAgentId.trim())}&asset_id=${encodeURIComponent(lkAssetId.trim())}`);
                if (res.success && res.data) {
                  setLkResult(res.data);
                } else {
                  showToast(res.error || _['error-generic'], 'error');
                }
                setLkChecking(false);
              }}>
              {lkChecking ? _['leakage-checking'] : _['leakage-check']}
            </button>
            <button class="btn btn-ghost grow" disabled={lkResetting || !lkAgentId.trim() || !lkAssetId.trim()}
              onClick={async () => {
                setLkResetting(true);
                const res = await post<any>('/leakage/reset', {
                  agent_id: lkAgentId.trim(),
                  asset_id: lkAssetId.trim(),
                });
                if (res.success) {
                  showToast(_['leakage-reset-success'], 'success');
                  setLkResult(null);
                } else {
                  showToast(res.error || _['error-generic'], 'error');
                }
                setLkResetting(false);
              }}>
              {lkResetting ? _['leakage-resetting'] : _['leakage-reset']}
            </button>
          </div>
        </div>

        {lkResult && (
          <div class="net-tool-result mt-12">
            <div class="kv"><span class="kv-key">{_['leakage-remaining']}</span><span class="kv-val mono">{lkResult.remaining}</span></div>
            <div class="kv"><span class="kv-key">{_['leakage-used']}</span><span class="kv-val mono">{lkResult.used}</span></div>
            <div class="kv"><span class="kv-key">{_['leakage-budget-total']}</span><span class="kv-val mono">{lkResult.budget}</span></div>
            <div class="kv"><span class="kv-key">{_['leakage-queries']}</span><span class="kv-val mono">{lkResult.queries}</span></div>
            <div class="kv">
              <span class="kv-key">{_['leakage-exhausted']}</span>
              <span class={`kv-val mono ${lkResult.exhausted ? 'color-red' : 'color-green'}`}>
                {lkResult.exhausted ? 'Yes' : 'No'}
              </span>
            </div>
          </div>
        )}
      </Section>

      {/* ── Cache Management — collapsible ── */}
      <Section id="cache" title={_['cache']} desc={_['cache-stats']} forceOpen={subpath === 'cache'}>
        {cacheLoading && <div class="caption fg-muted">{_['cache-stats']}...</div>}

        {!cacheLoading && cacheStats && (
          <div>
            <div class="kv"><span class="kv-key">{_['cache-total']}</span><span class="kv-val mono">{cacheStats.total}</span></div>
            <div class="kv"><span class="kv-key">{_['cache-active']}</span><span class="kv-val mono">{cacheStats.active}</span></div>
            <div class="kv"><span class="kv-key">{_['cache-expired']}</span><span class="kv-val mono">{cacheStats.expired}</span></div>
            {cacheStats.db_path && (
              <div class="kv"><span class="kv-key">{_['cache-db-path']}</span><span class="kv-val mono kv-val-xs">{cacheStats.db_path}</span></div>
            )}
            <button class="btn btn-primary btn-full mt-12" disabled={cachePurging}
              onClick={async () => {
                setCachePurging(true);
                const res = await post<any>('/cache/purge', {});
                if (res.success) {
                  showToast(_['cache-purge-success'], 'success');
                  // Reload stats
                  const sRes = await get<any>('/cache/stats');
                  if (sRes.success && sRes.data) setCacheStats(sRes.data);
                } else {
                  showToast(res.error || _['error-generic'], 'error');
                }
                setCachePurging(false);
              }}>
              {cachePurging ? _['cache-purging'] : _['cache-purge']}
            </button>
          </div>
        )}

        {!cacheLoading && !cacheStats && (
          <div class="caption fg-muted">{_['cache-stats']}...</div>
        )}
      </Section>
    </div>
  );
}
