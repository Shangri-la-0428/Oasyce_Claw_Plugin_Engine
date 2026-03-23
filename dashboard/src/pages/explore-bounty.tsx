/**
 * Bounty tab — AHRP Task Market: post tasks, bid, select winner, complete
 */
import { useEffect, useState } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n, walletAddress } from '../store/ui';
import { maskIdShort, fmtPrice } from '../utils';
import { EmptyState } from '../components/empty-state';
import './explore-bounty.css';

type TaskStatus = 'open' | 'bidding' | 'assigned' | 'completed' | 'cancelled';
type SelectionStrategy = 'weighted_score' | 'lowest_price' | 'best_reputation' | 'requester_choice';

interface Bid {
  agent_id: string;
  price: number;
  estimated_seconds: number;
  reputation_score: number;
}

interface Task {
  task_id: string;
  description: string;
  budget: number;
  status: TaskStatus;
  requester_id: string;
  deadline: number;
  required_capabilities: string[];
  bids: Bid[];
  assigned_agent?: string;
  selection_strategy: SelectionStrategy;
  min_reputation: number;
}

export default function ExploreBounty() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  /* Post form state */
  const [showPost, setShowPost] = useState(false);
  const [postDesc, setPostDesc] = useState('');
  const [postBudget, setPostBudget] = useState('');
  const [postDeadline, setPostDeadline] = useState('1');
  const [postCaps, setPostCaps] = useState('');
  const [postStrategy, setPostStrategy] = useState<SelectionStrategy>('weighted_score');
  const [postMinRep, setPostMinRep] = useState('0');
  const [posting, setPosting] = useState(false);

  /* Bid form state (keyed by task id) */
  const [bidTaskId, setBidTaskId] = useState<string | null>(null);
  const [bidPrice, setBidPrice] = useState('');
  const [bidSeconds, setBidSeconds] = useState('');
  const [bidding, setBidding] = useState(false);

  /* Action loading */
  const [actionId, setActionId] = useState<string | null>(null);

  const _ = i18n.value;
  const me = walletAddress();

  useEffect(() => { loadTasks(); }, []);

  const loadTasks = async () => {
    setLoading(true);
    const res = await get<{ tasks: Task[] }>('/tasks');
    if (res.success && Array.isArray(res.data?.tasks)) setTasks(res.data.tasks);
    setLoading(false);
  };

  /* ── Post Task ── */
  const onPost = async () => {
    if (!postDesc.trim() || !postBudget) return;
    setPosting(true);
    const res = await post<{ success: boolean }>('/task/post', {
      description: postDesc.trim(),
      budget: parseFloat(postBudget),
      deadline_seconds: parseFloat(postDeadline) * 3600,
      required_capabilities: postCaps.split(',').map(s => s.trim()).filter(Boolean),
      selection_strategy: postStrategy,
      min_reputation: parseFloat(postMinRep) || 0,
    });
    if (res.success && res.data?.success) {
      showToast(_['bounty-post-success'], 'success');
      setPostDesc(''); setPostBudget(''); setPostDeadline('1'); setPostCaps(''); setPostMinRep('0');
      setShowPost(false);
      loadTasks();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setPosting(false);
  };

  /* ── Submit Bid ── */
  const onBid = async (taskId: string) => {
    if (!bidPrice || !bidSeconds) return;
    setBidding(true);
    const res = await post<{ success: boolean }>(`/task/${taskId}/bid`, {
      price: parseFloat(bidPrice),
      estimated_seconds: parseInt(bidSeconds, 10),
    });
    if (res.success && res.data?.success) {
      showToast(_['bounty-bid-success'], 'success');
      setBidTaskId(null); setBidPrice(''); setBidSeconds('');
      loadTasks();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setBidding(false);
  };

  /* ── Select Winner ── */
  const onSelect = async (taskId: string, agentId: string) => {
    setActionId(taskId);
    const res = await post<{ success: boolean }>(`/task/${taskId}/select`, { agent_id: agentId });
    if (res.success && res.data?.success) {
      showToast(_['bounty-select-success'], 'success');
      loadTasks();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setActionId(null);
  };

  /* ── Complete ── */
  const onComplete = async (taskId: string) => {
    setActionId(taskId);
    const res = await post<{ success: boolean }>(`/task/${taskId}/complete`);
    if (res.success && res.data?.success) {
      showToast(_['bounty-complete-success'], 'success');
      loadTasks();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setActionId(null);
  };

  /* ── Cancel ── */
  const onCancel = async (taskId: string) => {
    setActionId(taskId);
    const res = await post<{ success: boolean }>(`/task/${taskId}/cancel`);
    if (res.success && res.data?.success) {
      showToast(_['bounty-cancel-success'], 'success');
      loadTasks();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setActionId(null);
  };

  const isOwner = (t: Task) => t.requester_id === me;
  const statusColor = (s: TaskStatus) => {
    if (s === 'completed') return 'var(--green)';
    if (s === 'cancelled') return 'var(--red)';
    return 'var(--fg-2)';
  };

  return (
    <>
      {/* ── Post Task (collapsible) ── */}
      <div class="section mb-24">
        <button class="btn btn-ghost" onClick={() => setShowPost(!showPost)}>
          {showPost ? '−' : '+'} {_['bounty-post']}
        </button>

        {showPost && (
          <div class="card mt-8 bounty-post-form">
            <div class="col gap-8">
              <label class="caption" htmlFor="bounty-description">{_['bounty-description']}</label>
              <textarea
                id="bounty-description"
                class="input input-textarea"
                value={postDesc}
                onInput={e => setPostDesc((e.target as HTMLTextAreaElement).value)}
                rows={3}
                required
                aria-required="true"
              />

              <div class="row gap-16">
                <div class="col gap-4 grow">
                  <label class="caption" htmlFor="bounty-budget">{_['bounty-budget']}</label>
                  <input id="bounty-budget" class="input" type="number" min="0" step="0.01"
                    value={postBudget}
                    onInput={e => setPostBudget((e.target as HTMLInputElement).value)}
                    required
                    aria-required="true"
                  />
                </div>
                <div class="col gap-4 grow">
                  <label class="caption" htmlFor="bounty-deadline">{_['bounty-deadline']}</label>
                  <input id="bounty-deadline" class="input" type="number" min="0.1" step="0.5"
                    value={postDeadline}
                    onInput={e => setPostDeadline((e.target as HTMLInputElement).value)}
                  />
                </div>
              </div>

              <label class="caption" htmlFor="bounty-capabilities">{_['bounty-capabilities']}</label>
              <input id="bounty-capabilities" class="input" type="text"
                placeholder={_['bounty-capabilities-hint']}
                value={postCaps}
                onInput={e => setPostCaps((e.target as HTMLInputElement).value)}
              />

              <div class="row gap-16">
                <div class="col gap-4 grow">
                  <label class="caption" htmlFor="bounty-strategy">{_['bounty-strategy']}</label>
                  <select id="bounty-strategy" class="input"
                    value={postStrategy}
                    onChange={e => setPostStrategy((e.target as HTMLSelectElement).value as SelectionStrategy)}
                  >
                    <option value="weighted_score">{_['bounty-strategy-weighted']}</option>
                    <option value="lowest_price">{_['bounty-strategy-price']}</option>
                    <option value="best_reputation">{_['bounty-strategy-reputation']}</option>
                    <option value="requester_choice">{_['bounty-strategy-requester']}</option>
                  </select>
                </div>
                <div class="col gap-4 grow">
                  <label class="caption" htmlFor="bounty-min-rep">{_['bounty-min-rep']}</label>
                  <input id="bounty-min-rep" class="input" type="number" min="0" step="1"
                    value={postMinRep}
                    onInput={e => setPostMinRep((e.target as HTMLInputElement).value)}
                  />
                </div>
              </div>

              <button class="btn btn-primary mt-8" onClick={onPost} disabled={posting || !postDesc.trim() || !postBudget}>
                {posting ? _['bounty-posting'] : _['bounty-post']}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ── Task List ── */}
      <h2 class="label-inline mb-16">{_['bounty-list']}</h2>

      {loading && <div class="caption fg-muted">{_['loading']}</div>}

      {!loading && tasks.length === 0 && (
        <EmptyState icon="◎" title={_['bounty-no-tasks']} hint={_['bounty-no-tasks-hint']} />
      )}

      <div class="col gap-8">
        {tasks.map(t => {
          const expanded = expandedId === t.task_id;
          const owner = isOwner(t);
          return (
            <div key={t.task_id} class="card bounty-task-card">
              {/* Summary row */}
              <button class="bounty-task-summary" onClick={() => setExpandedId(expanded ? null : t.task_id)} aria-expanded={expanded}>
                <span class="mono bounty-task-id">{maskIdShort(t.task_id)}</span>
                <span class="bounty-task-desc">{t.description}</span>
                <span class="mono">{fmtPrice(t.budget)} OAS</span>
                <span class="bounty-status-badge" style={{ color: statusColor(t.status) }}>{t.status}</span>
                <span class="caption">{_['bounty-bids-count']}: {t.bids?.length ?? 0}</span>
              </button>

              {/* Expanded detail */}
              {expanded && (
                <div class="bounty-task-detail">
                  <div class="kv"><span class="kv-key">{_['bounty-requester']}</span><span class="kv-val mono">{maskIdShort(t.requester_id)}</span></div>
                  <div class="kv"><span class="kv-key">{_['bounty-deadline']}</span><span class="kv-val mono">{(t.deadline / 3600).toFixed(1)}h</span></div>
                  <div class="kv"><span class="kv-key">{_['bounty-capabilities']}</span><span class="kv-val">{t.required_capabilities?.join(', ') || '--'}</span></div>
                  <div class="kv"><span class="kv-key">{_['bounty-strategy']}</span><span class="kv-val">{t.selection_strategy}</span></div>
                  <div class="kv"><span class="kv-key">{_['bounty-min-rep']}</span><span class="kv-val mono">{t.min_reputation}</span></div>
                  {t.assigned_agent && (
                    <div class="kv"><span class="kv-key">{_['bounty-assigned']}</span><span class="kv-val mono">{maskIdShort(t.assigned_agent)}</span></div>
                  )}

                  {/* Bids list */}
                  {t.bids && t.bids.length > 0 && (
                    <div class="mt-12">
                      <div class="caption mb-4">{_['bounty-bids']} ({t.bids.length})</div>
                      <div class="col gap-4">
                        {t.bids.map((b) => (
                          <div key={b.agent_id} class="bounty-bid-row">
                            <span class="mono">{maskIdShort(b.agent_id)}</span>
                            <span class="mono">{fmtPrice(b.price)} OAS</span>
                            <span class="caption">{b.estimated_seconds}s</span>
                            <span class="caption">{_['bounty-bid-rep']}: {b.reputation_score}</span>
                            {owner && (t.status === 'open' || t.status === 'bidding') && (
                              <button class="btn btn-sm" onClick={() => onSelect(t.task_id, b.agent_id)} disabled={actionId === t.task_id}>
                                {actionId === t.task_id ? _['bounty-selecting'] : _['bounty-select']}
                              </button>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Actions */}
                  <div class="row gap-8 mt-12">
                    {/* Bid button — available on open/bidding for non-owners */}
                    {(t.status === 'open' || t.status === 'bidding') && !owner && (
                      <button class="btn btn-sm btn-primary"
                        onClick={() => setBidTaskId(bidTaskId === t.task_id ? null : t.task_id)}>
                        {_['bounty-bid']}
                      </button>
                    )}

                    {/* Complete — owner on assigned */}
                    {t.status === 'assigned' && owner && (
                      <button class="btn btn-sm btn-primary" onClick={() => onComplete(t.task_id)} disabled={actionId === t.task_id}>
                        {actionId === t.task_id ? _['bounty-completing'] : _['bounty-complete']}
                      </button>
                    )}

                    {/* Cancel — owner on open/bidding */}
                    {(t.status === 'open' || t.status === 'bidding') && owner && (
                      <button class="btn btn-sm btn-ghost" onClick={() => onCancel(t.task_id)} disabled={actionId === t.task_id}>
                        {actionId === t.task_id ? _['bounty-cancelling'] : _['bounty-cancel']}
                      </button>
                    )}
                  </div>

                  {/* Inline bid form */}
                  {bidTaskId === t.task_id && (
                    <div class="bounty-bid-form mt-8">
                      <div class="row gap-8">
                        <input class="input grow" type="number" min="0" step="0.01"
                          placeholder={_['bounty-bid-price']}
                          value={bidPrice}
                          onInput={e => setBidPrice((e.target as HTMLInputElement).value)}
                        />
                        <input class="input grow" type="number" min="1" step="1"
                          placeholder={_['bounty-bid-seconds']}
                          value={bidSeconds}
                          onInput={e => setBidSeconds((e.target as HTMLInputElement).value)}
                        />
                        <button class="btn btn-sm btn-primary" onClick={() => onBid(t.task_id)} disabled={bidding || !bidPrice || !bidSeconds}>
                          {bidding ? _['bounty-bidding'] : _['bounty-bid']}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}
