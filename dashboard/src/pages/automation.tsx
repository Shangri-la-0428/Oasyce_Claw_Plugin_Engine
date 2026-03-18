/**
 * Automation — Agent Scheduler + 自动注册/交易管控 + 手动确认队列
 */
import { useEffect, useState, useCallback } from 'preact/hooks';
import { showToast, i18n, lang } from '../store/ui';
import { get, post } from '../api/client';
import {
  inboxItems, trustConfig, scanning, lastScan,
  loadInbox, loadTrust, scanDirectory, approveItem, rejectItem, editItem, setTrust,
} from '../store/scanner';
import './automation.css';

type Tab = 'queue' | 'rules';

/* ── Agent Scheduler types ── */
interface AgentStatus {
  running: boolean;
  enabled: boolean;
  last_run: string | null;
  next_run: string | null;
  last_result: string | null;
  total_runs: number;
  total_registered: number;
  total_errors: number;
}

interface AgentCfg {
  enabled: boolean;
  interval_hours: number;
  scan_paths: string[];
  auto_register: boolean;
  auto_trade: boolean;
  trade_tags: string[];
  trade_max_spend: number;
}

interface HistoryRun {
  timestamp: string;
  scan_count: number;
  register_count: number;
  trade_count: number;
  errors: number;
  duration_ms: number;
}

/* ── Collapsible section (reused from network pattern) ── */
function Section({ id, title, desc, defaultOpen = false, children }: {
  id: string; title: string; desc?: string; defaultOpen?: boolean; children: any;
}) {
  const storageKey = `auto-section-${id}`;
  const [open, setOpen] = useState(() => {
    try {
      const saved = localStorage.getItem(storageKey);
      return saved !== null ? saved === '1' : defaultOpen;
    } catch { return defaultOpen; }
  });
  const toggle = useCallback(() => {
    setOpen(prev => {
      try { localStorage.setItem(storageKey, prev ? '0' : '1'); } catch {}
      return !prev;
    });
  }, [storageKey]);
  return (
    <div class="card mb-24">
      <button class="auto-section-toggle" onClick={toggle} aria-expanded={open} aria-controls={`section-${id}`}>
        <div class="auto-section-header">
          <div class="label label-flush">{title}</div>
          {desc && !open && <span class="caption auto-section-peek">{desc}</span>}
        </div>
        <span class={`auto-section-chevron ${open ? 'auto-section-chevron-open' : ''}`}>›</span>
      </button>
      {open && (
        <div id={`section-${id}`} class="auto-section-body">
          {desc && <p class="caption mb-16">{desc}</p>}
          {children}
        </div>
      )}
    </div>
  );
}

interface AgentConfig {
  id: string;
  name: string;
  icon: string;
  desc_zh: string;
  desc_en: string;
  status: 'connected' | 'available' | 'unavailable';
}

const KNOWN_AGENTS: AgentConfig[] = [
  { id: 'openclaw', name: 'OpenClaw', icon: 'O', desc_zh: '本地 Agent Runtime，全功能', desc_en: 'Local agent runtime, full-featured', status: 'connected' },
  { id: 'cursor', name: 'Cursor', icon: 'C', desc_zh: 'AI 代码编辑器，擅长代码类资产', desc_en: 'AI code editor, great for code assets', status: 'available' },
  { id: 'claude-code', name: 'Claude Code', icon: 'CC', desc_zh: 'Anthropic CLI Agent', desc_en: 'Anthropic CLI Agent', status: 'available' },
  { id: 'custom', name: 'Custom', icon: '?', desc_zh: '自定义 Agent（通过 API 接入）', desc_en: 'Custom agent (via API)', status: 'available' },
];

export default function Automation() {
  const [tab, setTab] = useState<Tab>('queue');
  const [scanPath, setScanPath] = useState('~/Documents');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editTags, setEditTags] = useState('');
  const [editDesc, setEditDesc] = useState('');
  const [selectedAgent, setSelectedAgent] = useState('openclaw');
  const [customEndpoint, setCustomEndpoint] = useState('');
  const [customName, setCustomName] = useState('');
  const _ = i18n.value;

  /* ── Agent Scheduler state ── */
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [agentConfig, setAgentConfig] = useState<AgentCfg | null>(null);
  const [agentHistory, setAgentHistory] = useState<HistoryRun[]>([]);
  const [runningNow, setRunningNow] = useState(false);
  const [savingCfg, setSavingCfg] = useState(false);
  // editable config fields
  const [cfgInterval, setCfgInterval] = useState(6);
  const [cfgScanPaths, setCfgScanPaths] = useState('');
  const [cfgAutoRegister, setCfgAutoRegister] = useState(false);
  const [cfgAutoTrade, setCfgAutoTrade] = useState(false);
  const [cfgTradeTags, setCfgTradeTags] = useState('');
  const [cfgTradeMax, setCfgTradeMax] = useState(0);

  const loadAgentStatus = async () => {
    const res = await get<AgentStatus>('/api/agent/status');
    if (res.success && res.data) setAgentStatus(res.data);
  };
  const loadAgentConfig = async () => {
    const res = await get<AgentCfg>('/api/agent/config');
    if (res.success && res.data) {
      setAgentConfig(res.data);
      setCfgInterval(res.data.interval_hours);
      setCfgScanPaths((res.data.scan_paths || []).join('\n'));
      setCfgAutoRegister(res.data.auto_register);
      setCfgAutoTrade(res.data.auto_trade);
      setCfgTradeTags((res.data.trade_tags || []).join(', '));
      setCfgTradeMax(res.data.trade_max_spend);
    }
  };
  const loadAgentHistory = async () => {
    const res = await get<{ runs: HistoryRun[] }>('/api/agent/history?limit=10');
    if (res.success && res.data) setAgentHistory(res.data.runs || []);
  };

  const toggleEnabled = async () => {
    const next = !(agentConfig?.enabled ?? false);
    const res = await post<AgentCfg>('/api/agent/config', { enabled: next });
    if (res.success && res.data) {
      setAgentConfig(res.data);
      showToast(next ? _['agent-enabled'] : _['agent-disabled'], 'success');
      loadAgentStatus();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
  };

  const runNow = async () => {
    setRunningNow(true);
    const res = await post<{ ok: boolean; result: string }>('/api/agent/run', {});
    setRunningNow(false);
    if (res.success) {
      showToast(res.data?.result || 'OK', 'success');
      loadAgentStatus();
      loadAgentHistory();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
  };

  const saveConfig = async () => {
    setSavingCfg(true);
    const payload: Partial<AgentCfg> = {
      interval_hours: cfgInterval,
      scan_paths: cfgScanPaths.split('\n').map(s => s.trim()).filter(Boolean),
      auto_register: cfgAutoRegister,
      auto_trade: cfgAutoTrade,
      trade_tags: cfgTradeTags.split(/[,，\s]+/).filter(Boolean),
      trade_max_spend: cfgTradeMax,
    };
    const res = await post<AgentCfg>('/api/agent/config', payload);
    setSavingCfg(false);
    if (res.success && res.data) {
      setAgentConfig(res.data);
      showToast(_['saved'], 'success');
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
  };

  useEffect(() => { loadInbox(); loadTrust(); loadAgentStatus(); loadAgentConfig(); loadAgentHistory(); }, []);

  const pendingItems = inboxItems.value.filter(i => i.status === 'pending');
  const doneItems = inboxItems.value.filter(i => i.status !== 'pending');

  const onScan = async () => {
    if (!scanPath.trim()) return;
    const res = await scanDirectory(scanPath.trim());
    if (res.success) showToast(_['scan-done'], 'success');
    else showToast(res.error || _['error-generic'], 'error');
  };

  const onApprove = async (id: string) => {
    const res = await approveItem(id);
    if (res.success) showToast(_['approved'], 'success');
    else showToast(res.error || _['error-generic'], 'error');
  };

  const onReject = async (id: string) => {
    const res = await rejectItem(id);
    if (res.success) showToast(_['rejected'], 'success');
    else showToast(res.error || _['error-generic'], 'error');
  };

  const startEdit = (item: typeof inboxItems.value[0]) => {
    setEditingId(item.item_id);
    setEditName(item.suggested_name);
    setEditTags((item.suggested_tags || []).join(', '));
    setEditDesc(item.suggested_description || '');
  };

  const saveEdit = async (id: string) => {
    await editItem(id, {
      suggested_name: editName,
      suggested_tags: editTags.split(/[,，\s]+/).filter(Boolean),
      suggested_description: editDesc,
    });
    setEditingId(null);
    showToast(_['saved'], 'success');
  };

  const approveAll = async () => {
    for (const item of pendingItems) {
      await approveItem(item.item_id);
    }
    showToast(_['all-approved'], 'success');
  };

  return (
    <div class="page">
      <div class="row between mb-8">
        <h1 class="label m-0">{_['automation']}</h1>
        {pendingItems.length > 0 && <span class="auto-badge-pending">{pendingItems.length}</span>}
      </div>
      <p class="caption mb-24">{_['automation-desc']}</p>

      {/* ══ Agent Scheduler ══ */}
      <Section id="agent-status" title={_['agent-schedule']} desc={_['agent-schedule-desc']} defaultOpen={true}>
        {/* Status + toggle */}
        <div class="row between mb-16">
          <div class="row gap-8 align-center">
            <span class={`auto-status-dot ${agentStatus?.running ? 'auto-dot-running' : 'auto-dot-disabled'}`} />
            <span class="caption">{agentStatus?.running ? _['agent-running'] : _['agent-disabled']}</span>
          </div>
          <div class="row gap-8">
            <button class={`btn btn-sm ${agentConfig?.enabled ? 'btn-active' : 'btn-ghost'}`} onClick={toggleEnabled}>
              {_['agent-enabled']}
            </button>
            <button class="btn btn-sm btn-ghost" onClick={runNow} disabled={runningNow}>
              {runningNow ? '...' : _['agent-run-now']}
            </button>
          </div>
        </div>

        {/* Quick stats */}
        {agentStatus && (
          <div class="auto-agent-stats mb-16">
            <div class="kv"><span class="caption">{_['agent-last-run']}</span><span class="mono">{agentStatus.last_run || '—'}</span></div>
            <div class="kv"><span class="caption">{_['agent-next-run']}</span><span class="mono">{agentStatus.next_run || '—'}</span></div>
            <div class="kv"><span class="caption">{_['agent-total-runs']}</span><span class="mono">{agentStatus.total_runs}</span></div>
            <div class="kv"><span class="caption">{_['agent-total-registered']}</span><span class="mono">{agentStatus.total_registered}</span></div>
            <div class="kv"><span class="caption">{_['agent-total-errors']}</span><span class="mono">{agentStatus.total_errors}</span></div>
          </div>
        )}
      </Section>

      {/* Scheduler Config */}
      <Section id="agent-config" title={_['agent-save-config']}>
        <div class="col gap-12">
          {/* Interval */}
          <div>
            <div class="caption mb-4">{_['agent-interval']}</div>
            <div class="row gap-8 align-center">
              <input class="input auto-input-sm" type="number" min={1} value={cfgInterval} onInput={e => setCfgInterval(Number((e.target as HTMLInputElement).value))} />
              <span class="caption">{_['agent-interval-hours']}</span>
            </div>
          </div>

          {/* Scan paths */}
          <div>
            <div class="caption mb-4">{_['agent-scan-paths']}</div>
            <textarea class="input auto-textarea" rows={3} value={cfgScanPaths} onInput={e => setCfgScanPaths((e.target as HTMLTextAreaElement).value)} placeholder={_['agent-scan-paths-hint']} />
          </div>

          {/* Auto register */}
          <label class="row gap-8 align-center auto-check-row">
            <input type="checkbox" checked={cfgAutoRegister} onChange={e => setCfgAutoRegister((e.target as HTMLInputElement).checked)} />
            <span>{_['agent-auto-register']}</span>
          </label>

          {/* Auto trade */}
          <label class="row gap-8 align-center auto-check-row">
            <input type="checkbox" checked={cfgAutoTrade} onChange={e => setCfgAutoTrade((e.target as HTMLInputElement).checked)} />
            <span>{_['agent-auto-trade']}</span>
          </label>
          <div class="caption auto-trade-warning">{_['agent-auto-trade-desc']}</div>

          {/* Trade tags */}
          {cfgAutoTrade && (
            <div>
              <div class="caption mb-4">{_['agent-trade-tags']}</div>
              <input class="input" value={cfgTradeTags} onInput={e => setCfgTradeTags((e.target as HTMLInputElement).value)} placeholder={_['agent-trade-tags-hint']} />
            </div>
          )}

          {/* Max spend */}
          {cfgAutoTrade && (
            <div>
              <div class="caption mb-4">{_['agent-trade-max']} (OAS)</div>
              <input class="input auto-input-sm" type="number" min={0} value={cfgTradeMax} onInput={e => setCfgTradeMax(Number((e.target as HTMLInputElement).value))} />
            </div>
          )}

          <button class="btn btn-primary btn-sm self-start" onClick={saveConfig} disabled={savingCfg}>
            {savingCfg ? '...' : _['agent-save-config']}
          </button>
        </div>
      </Section>

      {/* Run History */}
      <Section id="agent-history" title={_['agent-history']}>
        {agentHistory.length === 0 && (
          <div class="caption">{_['agent-no-history']}</div>
        )}
        {agentHistory.length > 0 && (
          <div class="auto-history-list">
            {agentHistory.map((run, i) => (
              <div key={i} class="auto-history-row">
                <span class="mono caption">{run.timestamp}</span>
                <span class="caption">scan {run.scan_count}</span>
                <span class="caption">reg {run.register_count}</span>
                <span class="caption">trade {run.trade_count}</span>
                {run.errors > 0 && <span class="caption auto-history-err">err {run.errors}</span>}
                <span class="mono caption">{run.duration_ms}ms</span>
              </div>
            ))}
          </div>
        )}
      </Section>

      <div class="tabs mb-24">
        <button class={`tab ${tab === 'queue' ? 'active' : ''}`} onClick={() => setTab('queue')}>
          {_['auto-queue']}
          {pendingItems.length > 0 && <span class="tab-count">{pendingItems.length}</span>}
        </button>
        <button class={`tab ${tab === 'rules' ? 'active' : ''}`} onClick={() => setTab('rules')}>
          {_['auto-rules']}
        </button>
      </div>

      {/* ══ Queue ══ */}
      {tab === 'queue' && (
        <div>
          <div class="auto-scan-bar mb-24">
            <input class="input" value={scanPath} onInput={e => setScanPath((e.target as HTMLInputElement).value)} placeholder={_['scan-path-hint']} />
            <button class="btn btn-ghost btn-sm" onClick={onScan} disabled={scanning.value}>
              {scanning.value ? _['scanning'] : _['scan-btn']}
            </button>
          </div>

          {lastScan.value && (
            <div class="auto-scan-result mb-16">
              <span class="caption">{_['scan-found']} <strong class="mono">{lastScan.value.scanned}</strong></span>
              <span class="caption">→ {_['scan-added']} <strong class="mono">{lastScan.value.added}</strong></span>
            </div>
          )}

          {pendingItems.length > 0 && (
            <div class="mb-24">
              <div class="row between mb-12">
                <span class="label m-0">{_['pending-tasks']}</span>
                <button class="btn btn-ghost btn-sm" onClick={approveAll}>{_['approve-all']}</button>
              </div>
              {pendingItems.map(item => (
                <div key={item.item_id} class="auto-item">
                  <div class="auto-item-main">
                    <div class="grow">
                      <div class="auto-item-name">{item.suggested_name}</div>
                      <div class="auto-item-path">{item.file_path}</div>
                      {item.suggested_description && <div class="auto-item-desc">{item.suggested_description}</div>}
                      <div class="auto-item-meta">
                        {(item.suggested_tags || []).map(tag => <span key={tag} class="badge">{tag}</span>)}
                        <span class={`badge badge-${item.sensitivity || 'safe'}`}>{item.sensitivity || '--'}</span>
                        <span class="caption mono">{item.confidence != null ? (item.confidence * 100).toFixed(0) + '%' : '--'}</span>
                      </div>
                    </div>
                    {editingId !== item.item_id && (
                      <div class="auto-item-actions">
                        <button class="auto-action-btn auto-action-approve" onClick={() => onApprove(item.item_id)} title={_['approve']}>✓</button>
                        <button class="auto-action-btn auto-action-edit" onClick={() => startEdit(item)} title={_['edit']}>✎</button>
                        <button class="auto-action-btn auto-action-reject" onClick={() => onReject(item.item_id)} title={_['reject']}>✕</button>
                      </div>
                    )}
                  </div>
                  {editingId === item.item_id && (
                    <div class="auto-edit">
                      <input class="input" value={editName} onInput={e => setEditName((e.target as HTMLInputElement).value)} placeholder={_['edit-name']} />
                      <input class="input" value={editTags} onInput={e => setEditTags((e.target as HTMLInputElement).value)} placeholder={_['edit-tags']} />
                      <input class="input" value={editDesc} onInput={e => setEditDesc((e.target as HTMLInputElement).value)} placeholder={_['edit-desc']} />
                      <div class="row gap-8">
                        <button class="btn btn-primary btn-sm" onClick={() => saveEdit(item.item_id)}>{_['save']}</button>
                        <button class="btn btn-ghost btn-sm" onClick={() => setEditingId(null)}>{_['cancel']}</button>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {pendingItems.length === 0 && inboxItems.value.length === 0 && (
            <div class="auto-empty">
              <div class="auto-empty-icon">—</div>
              <div>{_['queue-empty']}</div>
              <div class="caption">{_['queue-empty-hint']}</div>
            </div>
          )}

          {doneItems.length > 0 && (
            <div>
              <div class="label">{_['completed-tasks']} <span class="mono fg-muted">{doneItems.length}</span></div>
              {doneItems.slice(0, 10).map(item => (
                <div key={item.item_id} class="auto-item auto-item-done">
                  <div class="auto-item-main">
                    <div class="grow">
                      <div class="auto-item-name">{item.suggested_name}</div>
                      <div class="auto-item-path">{item.file_path}</div>
                    </div>
                    <span class={`badge badge-${item.status === 'approved' ? 'safe' : 'sensitive'}`}>
                      {_[`status-${item.status}`]}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ══ Rules ══ */}
      {tab === 'rules' && (
        <div>
          {/* Trust Level */}
          <div class="card mb-16">
            <div class="label">{_['trust-level']}</div>
            <div class="caption mb-16">{_['trust-level-desc']}</div>
            <div class="auto-trust-levels">
              {([0, 1, 2] as const).map(lv => (
                <button key={lv} class={`auto-trust-card ${trustConfig.value.trust_level === lv ? 'active' : ''}`} onClick={() => setTrust(lv)}>
                  <div class="auto-trust-icon">{['I', 'II', 'III'][lv]}</div>
                  <div class="auto-trust-name">{_[`trust-${lv}`]}</div>
                  <div class="caption">{_[`trust-${lv}-desc`]}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Agent Executor */}
          <div class="card mb-16">
            <div class="label">{_['agent-executor']}</div>
            <div class="caption mb-16">{_['agent-executor-desc']}</div>
            <div class="agent-grid">
              {KNOWN_AGENTS.map(agent => (
                <button key={agent.id} class={`agent-card ${selectedAgent === agent.id ? 'active' : ''}`} onClick={() => setSelectedAgent(agent.id)}>
                  <div class="agent-card-top">
                    <span class="agent-icon">{agent.icon}</span>
                    <span class={`agent-status-dot agent-dot-${agent.status}`} />
                  </div>
                  <div class="agent-name">{agent.name}</div>
                  <div class="caption">{lang.value === 'zh' ? agent.desc_zh : agent.desc_en}</div>
                  {agent.status === 'connected' && <div class="agent-connected-tag">{_['agent-connected']}</div>}
                </button>
              ))}
            </div>
            {selectedAgent === 'custom' && (
              <div class="auto-custom-agent mt-16">
                <div class="caption mb-8">{_['custom-agent-config']}</div>
                <div class="col gap-8">
                  <input class="input" value={customName} onInput={e => setCustomName((e.target as HTMLInputElement).value)} placeholder={_['custom-agent-name']} />
                  <input class="input input-mono" value={customEndpoint} onInput={e => setCustomEndpoint((e.target as HTMLInputElement).value)} placeholder={_['custom-agent-endpoint']} />
                  <button class="btn btn-primary btn-sm self-start" disabled={!customEndpoint.trim()}>
                    {_['custom-agent-test']}
                  </button>
                </div>
              </div>
            )}
            {selectedAgent !== 'openclaw' && selectedAgent !== 'custom' && (
              <div class="auto-agent-hint mt-16">
                <span class="caption">{_['agent-setup-hint']}</span>
              </div>
            )}
          </div>

          {/* Threshold */}
          <div class="card mb-16">
            <div class="label">{_['auto-threshold']}</div>
            <div class="caption mb-16">{_['auto-threshold-desc']}</div>
            <div class="auto-trust-levels">
              {([
                { value: 0.9, key: 'threshold-strict' as const },
                { value: 0.7, key: 'threshold-balanced' as const },
                { value: 0.5, key: 'threshold-permissive' as const },
              ]).map(tier => (
                <button key={tier.key} class={`auto-trust-card ${Math.abs(trustConfig.value.auto_threshold - tier.value) < 0.05 ? 'active' : ''}`} onClick={() => setTrust(undefined, tier.value)}>
                  <div class="auto-trust-icon">{tier.value === 0.9 ? '90' : tier.value === 0.7 ? '70' : '50'}</div>
                  <div class="auto-trust-name">{_[tier.key]}</div>
                  <div class="caption">{_[`${tier.key}-desc`]}</div>
                  <div class="mono auto-threshold-val">≥ {(tier.value * 100).toFixed(0)}%</div>
                </button>
              ))}
            </div>
          </div>

          {/* Scan */}
          <div class="card">
            <div class="label">{_['scan-directory']}</div>
            <div class="caption mb-12">{_['scan-directory-desc']}</div>
            <div class="auto-scan-bar">
              <input class="input" value={scanPath} onInput={e => setScanPath((e.target as HTMLInputElement).value)} placeholder={_['scan-path-hint']} />
              <button class="btn btn-primary" onClick={onScan} disabled={scanning.value}>
                {scanning.value ? _['scanning'] : _['scan-btn']}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
