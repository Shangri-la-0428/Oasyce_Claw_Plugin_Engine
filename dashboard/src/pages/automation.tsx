/**
 * Automation — 自动注册/交易管控 + 手动确认队列
 */
import { useEffect, useState } from 'preact/hooks';
import { showToast, i18n, lang } from '../store/ui';
import {
  inboxItems, trustConfig, scanning, lastScan,
  loadInbox, loadTrust, scanDirectory, approveItem, rejectItem, editItem, setTrust,
} from '../store/scanner';
import './automation.css';

type Tab = 'queue' | 'rules';

interface AgentConfig {
  id: string;
  name: string;
  icon: string;
  desc_zh: string;
  desc_en: string;
  status: 'connected' | 'available' | 'unavailable';
}

const KNOWN_AGENTS: AgentConfig[] = [
  { id: 'openclaw', name: 'OpenClaw', icon: '🐾', desc_zh: '本地 Agent Runtime，全功能', desc_en: 'Local agent runtime, full-featured', status: 'connected' },
  { id: 'cursor', name: 'Cursor', icon: '▢', desc_zh: 'AI 代码编辑器，擅长代码类资产', desc_en: 'AI code editor, great for code assets', status: 'available' },
  { id: 'claude-code', name: 'Claude Code', icon: '◉', desc_zh: 'Anthropic CLI Agent', desc_en: 'Anthropic CLI Agent', status: 'available' },
  { id: 'custom', name: 'Custom', icon: '⬡', desc_zh: '自定义 Agent（通过 API 接入）', desc_en: 'Custom agent (via API)', status: 'available' },
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

  useEffect(() => { loadInbox(); loadTrust(); }, []);

  const pendingItems = inboxItems.value.filter(i => i.status === 'pending');
  const doneItems = inboxItems.value.filter(i => i.status !== 'pending');

  const onScan = async () => {
    if (!scanPath.trim()) return;
    const res = await scanDirectory(scanPath.trim());
    if (res.success) showToast(_['scan-done'], 'success');
    else showToast(res.error || 'Failed', 'error');
  };

  const onApprove = async (id: string) => {
    const res = await approveItem(id);
    if (res.success) showToast(_['approved'], 'success');
    else showToast(res.error || 'Failed', 'error');
  };

  const onReject = async (id: string) => {
    const res = await rejectItem(id);
    if (res.success) showToast(_['rejected'], 'success');
    else showToast(res.error || 'Failed', 'error');
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
        <h1 class="heading" style="margin:0">{_['automation']}</h1>
        {pendingItems.length > 0 && <span class="auto-badge-pending">{pendingItems.length}</span>}
      </div>
      <p class="caption mb-24">{_['automation-desc']}</p>

      <div class="auto-tabs mb-24">
        <button class={`auto-tab ${tab === 'queue' ? 'active' : ''}`} onClick={() => setTab('queue')}>
          {_['auto-queue']}
          {pendingItems.length > 0 && <span class="auto-tab-count">{pendingItems.length}</span>}
        </button>
        <button class={`auto-tab ${tab === 'rules' ? 'active' : ''}`} onClick={() => setTab('rules')}>
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
                <span class="label" style="margin:0">{_['pending-tasks']}</span>
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
                        <span class={`badge badge-${item.sensitivity}`}>{item.sensitivity}</span>
                        <span class="caption mono">{(item.confidence * 100).toFixed(0)}%</span>
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
              <div class="auto-empty-icon">⚡</div>
              <div>{_['queue-empty']}</div>
              <div class="caption">{_['queue-empty-hint']}</div>
            </div>
          )}

          {doneItems.length > 0 && (
            <div>
              <div class="label">{_['completed-tasks']} <span class="mono" style="color:var(--fg-2)">{doneItems.length}</span></div>
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
                  <div class="auto-trust-icon">{['🔒', '⚡', '🤖'][lv]}</div>
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
                  <button class="btn btn-primary btn-sm" style="align-self:flex-start" disabled={!customEndpoint.trim()}>
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
                  <div class="auto-trust-icon">{tier.value === 0.9 ? '🛡' : tier.value === 0.7 ? '⚖' : '🚀'}</div>
                  <div class="auto-trust-name">{_[tier.key]}</div>
                  <div class="caption">{_[`${tier.key}-desc`]}</div>
                  <div class="mono" style="margin-top:6px;font-size:11px;color:var(--fg-2)">≥ {(tier.value * 100).toFixed(0)}%</div>
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
