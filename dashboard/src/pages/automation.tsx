/**
 * Automation — Agent Scheduler + 自动注册/交易管控 + 手动确认队列
 */
import { useEffect, useState } from 'preact/hooks';
import { showToast, i18n } from '../store/ui';
import { get, post } from '../api/client';
import { Section } from '../components/section';
import { EmptyState } from '../components/empty-state';
import {
  inboxItems, trustConfig, scanning, lastScan,
  loadInbox, loadTrust, scanDirectory, approveItem, rejectItem, editItem, setTrust,
  approveAll as storeApproveAll, rejectAll as storeRejectAll,
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

/* Section component imported from ../components/section */

const TRUST_LEVELS = [0, 1, 2] as const;
const TRUST_ICONS = ['I', 'II', 'III'] as const;

const THRESHOLD_TIERS = [
  { value: 0.9, key: 'threshold-strict' as const },
  { value: 0.7, key: 'threshold-balanced' as const },
  { value: 0.5, key: 'threshold-permissive' as const },
] as const;

export default function Automation() {
  const [tab, setTab] = useState<Tab>('queue');
  const [scanPath, setScanPath] = useState('~/Documents');
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState('');
  const [editTags, setEditTags] = useState('');
  const [editDesc, setEditDesc] = useState('');
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
    const res = await get<AgentStatus>('/agent/status');
    if (res.success && res.data) setAgentStatus(res.data);
  };
  const loadAgentConfig = async () => {
    const res = await get<AgentCfg>('/agent/config');
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
    const res = await get<{ runs: HistoryRun[] }>('/agent/history?limit=10');
    if (res.success && res.data) setAgentHistory(res.data.runs || []);
  };

  const toggleEnabled = async () => {
    const next = !(agentConfig?.enabled ?? false);
    const res = await post<AgentCfg>('/agent/config', { enabled: next });
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
    const res = await post<{ ok: boolean; result: string }>('/agent/run', {});
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
    const res = await post<AgentCfg>('/agent/config', payload);
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

  const onApproveAll = async () => {
    await storeApproveAll();
    showToast(_['all-approved'], 'success');
  };

  const onRejectAll = async () => {
    await storeRejectAll();
    showToast(_['all-rejected'], 'success');
  };

  return (
    <div class="page">
      <div class="row between mb-8">
        <h1 class="label m-0">{_['automation']}</h1>
        {pendingItems.length > 0 && <span class="auto-badge-pending">{pendingItems.length}</span>}
      </div>
      <p class="caption mb-24">{_['automation-desc']}</p>

      {/* ══ Queue / Rules — actionable items first ══ */}
      <div class="tabs mb-24" role="tablist" aria-label={_['automation']}>
        <button role="tab" aria-selected={tab === 'queue'} class={`tab ${tab === 'queue' ? 'active' : ''}`} onClick={() => setTab('queue')}>
          {_['auto-queue']}
          {pendingItems.length > 0 && <span class="tab-count">{pendingItems.length}</span>}
        </button>
        <button role="tab" aria-selected={tab === 'rules'} class={`tab ${tab === 'rules' ? 'active' : ''}`} onClick={() => setTab('rules')}>
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

          {scanning.value && (
            <div class="col gap-8 mb-16">
              <div class="skeleton skeleton-sm" />
              <div class="skeleton skeleton-sm" style={{ width: '75%' }} />
              <div class="skeleton skeleton-sm" style={{ width: '50%' }} />
            </div>
          )}

          {lastScan.value && !scanning.value && (
            <div class="auto-scan-result mb-16">
              <span class="caption">{_['scan-found']} <strong class="mono">{lastScan.value.scanned}</strong></span>
              <span class="caption">→ {_['scan-added']} <strong class="mono">{lastScan.value.added}</strong></span>
            </div>
          )}

          {pendingItems.length > 0 && (
            <div class="mb-24">
              <div class="row between mb-12">
                <span class="label m-0">{_['pending-tasks']}</span>
                <div class="row gap-8">
                  <button class="btn btn-ghost btn-sm" onClick={onRejectAll}>{_['reject-all']}</button>
                  <button class="btn btn-ghost btn-sm" onClick={onApproveAll}>{_['approve-all']}</button>
                </div>
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
                        <button class="btn btn-ghost btn-sm auto-action-approve" onClick={() => onApprove(item.item_id)} title={_['approve']} aria-label={_['approve']}>✓</button>
                        <button class="btn btn-ghost btn-sm" onClick={() => startEdit(item)} title={_['edit']} aria-label={_['edit']}>✎</button>
                        <button class="btn btn-ghost btn-sm auto-action-reject" onClick={() => onReject(item.item_id)} title={_['reject']} aria-label={_['reject']}>✕</button>
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
            <EmptyState icon="—" title={_['queue-empty']} hint={_['queue-empty-hint']} />
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
          <Section id="trust-level" title={_['trust-level']} desc={_['trust-level-desc']} forceOpen>
            <div class="auto-trust-levels">
              {TRUST_LEVELS.map(lv => (
                <button key={lv} class={`auto-trust-card ${trustConfig.value.trust_level === lv ? 'active' : ''}`} onClick={() => setTrust(lv)}>
                  <div class="auto-trust-icon">{TRUST_ICONS[lv]}</div>
                  <div class="auto-trust-name">{_[`trust-${lv}`]}</div>
                  <div class="caption">{_[`trust-${lv}-desc`]}</div>
                </button>
              ))}
            </div>
          </Section>

          {/* Threshold */}
          <Section id="auto-threshold" title={_['auto-threshold']} desc={_['auto-threshold-desc']} forceOpen>
            <div class="auto-trust-levels">
              {THRESHOLD_TIERS.map(tier => (
                <button key={tier.key} class={`auto-trust-card ${Math.abs(trustConfig.value.auto_threshold - tier.value) < 0.05 ? 'active' : ''}`} onClick={() => setTrust(undefined, tier.value)}>
                  <div class="auto-trust-icon">{tier.value === 0.9 ? '90' : tier.value === 0.7 ? '70' : '50'}</div>
                  <div class="auto-trust-name">{_[tier.key]}</div>
                  <div class="caption">{_[`${tier.key}-desc`]}</div>
                  <div class="mono auto-threshold-val">≥ {(tier.value * 100).toFixed(0)}%</div>
                </button>
              ))}
            </div>
          </Section>

          {/* Scan */}
          <Section id="scan-directory" title={_['scan-directory']} desc={_['scan-directory-desc']} forceOpen>
            <div class="auto-scan-bar">
              <input class="input" value={scanPath} onInput={e => setScanPath((e.target as HTMLInputElement).value)} placeholder={_['scan-path-hint']} />
              <button class="btn btn-ghost btn-sm" onClick={onScan} disabled={scanning.value}>
                {scanning.value ? _['scanning'] : _['scan-btn']}
              </button>
            </div>
          </Section>
        </div>
      )}

      {/* ══ Agent Scheduler (collapsible, below the fold) ══ */}
      <Section id="agent-status" title={_['agent-schedule']} desc={_['agent-schedule-desc']}>
        <div class="row between mb-16">
          <div class="row gap-8 align-center">
            <span class={`auto-status-dot ${agentStatus?.running ? 'auto-dot-running' : 'auto-dot-disabled'}`} aria-hidden="true" />
            <span class="caption">{agentStatus?.running ? _['agent-running'] : _['agent-disabled']}</span>
          </div>
          <div class="row gap-8">
            <button class={`btn btn-sm ${agentConfig?.enabled ? 'btn-active' : 'btn-ghost'}`} onClick={toggleEnabled}>
              {_['agent-enabled']}
            </button>
            <button class="btn btn-sm btn-ghost" onClick={runNow} disabled={runningNow}>
              {runningNow ? _['loading'] : _['agent-run-now']}
            </button>
          </div>
        </div>
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

      <Section id="agent-config" title={_['agent-save-config']}>
        <div class="col gap-12">
          <div>
            <div class="caption mb-4">{_['agent-interval']}</div>
            <div class="row gap-8 align-center">
              <input class="input auto-input-sm" type="number" min={1} value={cfgInterval} onInput={e => setCfgInterval(Number((e.target as HTMLInputElement).value))} />
              <span class="caption">{_['agent-interval-hours']}</span>
            </div>
          </div>
          <div>
            <div class="caption mb-4">{_['agent-scan-paths']}</div>
            <textarea class="input auto-textarea" rows={3} value={cfgScanPaths} onInput={e => setCfgScanPaths((e.target as HTMLTextAreaElement).value)} placeholder={_['agent-scan-paths-hint']} />
          </div>
          <label class="row gap-8 align-center auto-check-row">
            <input type="checkbox" checked={cfgAutoRegister} onChange={e => setCfgAutoRegister((e.target as HTMLInputElement).checked)} />
            <span>{_['agent-auto-register']}</span>
          </label>
          <label class="row gap-8 align-center auto-check-row">
            <input type="checkbox" checked={cfgAutoTrade} onChange={e => setCfgAutoTrade((e.target as HTMLInputElement).checked)} />
            <span>{_['agent-auto-trade']}</span>
          </label>
          <div class="caption auto-trade-warning">{_['agent-auto-trade-desc']}</div>
          {cfgAutoTrade && (
            <div>
              <div class="caption mb-4">{_['agent-trade-tags']}</div>
              <input class="input" value={cfgTradeTags} onInput={e => setCfgTradeTags((e.target as HTMLInputElement).value)} placeholder={_['agent-trade-tags-hint']} />
            </div>
          )}
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

      <Section id="agent-history" title={_['agent-history']}>
        {agentHistory.length === 0 && (
          <EmptyState icon="▷" title={_['agent-no-history']} hint={_['agent-no-history-hint']} />
        )}
        {agentHistory.length > 0 && (
          <div class="auto-history-list">
            {agentHistory.map((run) => (
              <div key={run.timestamp} class="auto-history-row">
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
    </div>
  );
}
