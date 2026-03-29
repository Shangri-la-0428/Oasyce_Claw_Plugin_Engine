/**
 * UI Store
 * i18n 用 computed signal 确保语言切换触发重渲染
 */
import { signal, computed } from '@preact/signals';

export const theme = signal<'dark' | 'light' | 'system'>('system');
export const lang = signal<'zh' | 'en' | 'system'>('system');

/** Resolved values — what's actually applied, never 'system' */
function systemTheme(): 'dark' | 'light' {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}
function systemLang(): 'zh' | 'en' {
  return navigator.language?.startsWith('zh') ? 'zh' : 'en';
}
export const resolvedTheme = computed<'dark' | 'light'>(() =>
  theme.value === 'system' ? systemTheme() : theme.value
);
export const resolvedLang = computed<'zh' | 'en'>(() =>
  lang.value === 'system' ? systemLang() : lang.value
);
export const toasts = signal<{ id: string; message: string; type: string }[]>([]);

/** Wallet identity state */
export const identity = signal<{ address: string; exists: boolean } | null>(null);

/** Canonical account state */
export interface AccountStatus {
  configured: boolean;
  account_address: string;
  account_mode: string;
  device_id: string;
  device_authorization_status: string;
  device_authorization_expires_at: number;
  can_sign: boolean;
  signer_name: string;
  signer_address: string;
  wallet_address: string;
  wallet_present: boolean;
  wallet_matches_account: boolean;
  signer_matches_account: boolean;
}
export const account = signal<AccountStatus | null>(null);

/** OAS balance */
export const balance = signal<number | null>(null);

/** Notification state */
export interface Notification {
  id: string;
  event_type: string;
  message: string;
  data: any;
  read: boolean;
  created_at: number;
}
export const notifications = signal<Notification[]>([]);
export const unreadCount = signal<number>(0);

async function readJsonSafe(res: Response): Promise<any> {
  try {
    return await res.json();
  } catch {
    return null; // Response body not valid JSON
  }
}

/** Load notifications from backend */
export async function loadNotifications(): Promise<void> {
  const addr = walletAddress();
  if (addr === 'anonymous') {
    notifications.value = [];
    unreadCount.value = 0;
    return;
  }
  try {
    const res = await fetch(`/api/notifications?address=${encodeURIComponent(addr)}&limit=50`);
    if (res.ok) {
      const data = await readJsonSafe(res);
      notifications.value = data?.notifications || [];
    }
  } catch {
    // Backend not available
  }
  // Also load unread count
  try {
    const res = await fetch(`/api/notifications/count?address=${encodeURIComponent(addr)}`);
    if (res.ok) {
      const data = await res.json();
      unreadCount.value = data.unread_count ?? 0;
    }
  } catch {
    // Backend not available
  }
}

/** Mark notification(s) as read */
export async function markNotificationsRead(notificationId?: string): Promise<void> {
  const addr = walletAddress();
  const body: any = notificationId ? { notification_id: notificationId } : { address: addr };
  try {
    const res = await fetch('/api/notifications/read', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await readJsonSafe(res);
    if (!res.ok || !data?.ok) return;
    if (notificationId) {
      notifications.value = notifications.value.map(n =>
        n.id === notificationId ? { ...n, read: true } : n
      );
      unreadCount.value = Math.max(0, unreadCount.value - 1);
    } else {
      notifications.value = notifications.value.map(n => ({ ...n, read: true }));
      unreadCount.value = 0;
    }
  } catch {
    // Best effort
  }
}

/** Load wallet identity from backend */
export async function loadIdentity(): Promise<void> {
  try {
    const res = await fetch('/api/identity/wallet');
    if (res.ok) {
      const data = await res.json();
      identity.value = { address: data.address || '', exists: !!data.exists };
    }
  } catch {
    // Backend not available — leave identity as null
  }
}

/** Load canonical economic account status from backend */
export async function loadAccountStatus(): Promise<void> {
  try {
    const res = await fetch('/api/account/status');
    if (res.ok) {
      const data = await res.json();
      account.value = {
        configured: !!data.configured,
        account_address: data.account_address || '',
        account_mode: data.account_mode || 'unconfigured',
        device_id: data.device_id || '',
        device_authorization_status: data.device_authorization_status || 'unconfigured',
        device_authorization_expires_at: Number(data.device_authorization_expires_at || 0),
        can_sign: !!data.can_sign,
        signer_name: data.signer_name || '',
        signer_address: data.signer_address || '',
        wallet_address: data.wallet_address || '',
        wallet_present: !!data.wallet_present,
        wallet_matches_account: !!data.wallet_matches_account,
        signer_matches_account: !!data.signer_matches_account,
      };
    }
  } catch {
    // Backend not available — leave account state as null
  }
}

/** Get the local wallet address only, falling back to 'anonymous' */
export function localWalletAddress(): string {
  return identity.value?.exists ? identity.value.address : 'anonymous';
}

/** Get the current economic account address, falling back to wallet or 'anonymous'. */
export function currentAccountAddress(): string {
  if (account.value?.configured && account.value.account_address) {
    return account.value.account_address;
  }
  return localWalletAddress();
}

/** Backward-compatible alias for the current actor address used across the dashboard. */
export function walletAddress(): string {
  return currentAccountAddress();
}

/** Whether the current canonical account can sign write actions on this device. */
export function currentAccountCanSign(): boolean {
  return !!account.value?.can_sign;
}

export async function prepareLocalAccount(): Promise<ApiActionResult> {
  const res = await fetch('/api/account/bootstrap', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  const data = await readJsonSafe(res);
  if (!res.ok || !data?.ok) {
    return {
      ok: false,
      error: data?.error || 'error-generic',
      issues: data?.verify?.issues || [],
      warnings: data?.verify?.warnings || [],
    };
  }
  await refreshAccountContext();
  return { ok: true, data };
}

export async function joinExistingAccount(params: {
  accountAddress: string;
  signerName?: string;
  readonly: boolean;
}): Promise<ApiActionResult> {
  const res = await fetch('/api/device/join', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      account_address: params.accountAddress,
      signer_name: params.signerName,
      readonly: params.readonly,
    }),
  });
  const data = await readJsonSafe(res);
  if (!res.ok || !data?.ok) {
    return {
      ok: false,
      error: data?.error || 'error-generic',
      issues: data?.verify?.issues || [],
      warnings: data?.verify?.warnings || [],
      data,
    };
  }
  await refreshAccountContext();
  return { ok: true, data };
}

export async function exportDeviceBundle(params?: {
  readonly?: boolean;
}): Promise<ApiActionResult> {
  const res = await fetch('/api/device/export', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      readonly: !!params?.readonly,
    }),
  });
  const data = await readJsonSafe(res);
  if (!res.ok || !data?.ok) {
    return {
      ok: false,
      error: data?.error || 'error-generic',
      issues: data?.verify?.issues || [],
      warnings: data?.verify?.warnings || [],
      data,
    };
  }
  return { ok: true, data };
}

export async function joinDeviceBundle(bundle: Record<string, unknown>): Promise<ApiActionResult> {
  const res = await fetch('/api/device/join', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ bundle }),
  });
  const data = await readJsonSafe(res);
  if (!res.ok || !data?.ok) {
    return {
      ok: false,
      error: data?.error || 'error-generic',
      issues: data?.verify?.issues || [],
      warnings: data?.verify?.warnings || [],
      data,
    };
  }
  await refreshAccountContext();
  return { ok: true, data };
}

export async function revokeCurrentDevice(): Promise<ApiActionResult> {
  const res = await fetch('/api/device/revoke', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  });
  const data = await readJsonSafe(res);
  if (!res.ok || !data?.ok) {
    return {
      ok: false,
      error: data?.error || 'error-generic',
      issues: data?.verify?.issues || [],
      warnings: data?.verify?.warnings || [],
      data,
    };
  }
  await refreshAccountContext();
  return { ok: true, data };
}

interface ApiActionResult {
  ok: boolean;
  error?: string;
  issues?: string[];
  warnings?: string[];
  data?: any;
}

export async function refreshAccountContext(): Promise<void> {
  await loadIdentity();
  await loadAccountStatus();
  await loadBalance();
  await loadNotifications();
}

/** Load OAS balance from backend */
export async function loadBalance(): Promise<void> {
  const addr = currentAccountAddress();
  if (addr === 'anonymous') { balance.value = 0; return; }
  try {
    const res = await fetch(`/api/balance?address=${encodeURIComponent(addr)}`);
    if (res.ok) {
      const data = await res.json();
      balance.value = data.balance_oas ?? 0;
    }
  } catch {
    // Backend not available
  }
}

/** PoW self-registration progress signal */
export const powProgress = signal<{ mining: boolean; attempts: number; found: boolean }>({
  mining: false, attempts: 0, found: false,
});

/** Self-register via PoW — computes nonce client-side, then submits to backend */
export async function selfRegister(): Promise<{ ok: boolean; amount?: number; error?: string }> {
  const addr = localWalletAddress();
  if (addr === 'anonymous') return { ok: false, error: 'no wallet' };

  powProgress.value = { mining: true, attempts: 0, found: false };

  try {
    // Backend computes PoW and registers (blocking but server-side is faster)
    const res = await fetch('/api/onboarding/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ address: addr }),
    });
    const data = await res.json();
    powProgress.value = { mining: false, attempts: data.attempts ?? 0, found: data.ok };

    if (data.ok) {
      balance.value = data.new_balance ?? balance.value;
      return { ok: true, amount: data.amount };
    }
    return { ok: false, error: data.error };
  } catch {
    powProgress.value = { mining: false, attempts: 0, found: false };
    return { ok: false, error: 'network error' };
  }
}

/** Safe localStorage wrapper for private browsing / quota errors */
function safeGetItem(key: string): string | null {
  try { return localStorage.getItem(key); } catch { return null; }
}
function safeSetItem(key: string, value: string): void {
  try { localStorage.setItem(key, value); } catch { /* quota/private mode */ }
}

/** Apply theme to DOM — 'system' removes data-theme so CSS @media takes over */
function applyTheme() {
  if (theme.value === 'system') {
    document.documentElement.removeAttribute('data-theme');
  } else {
    document.documentElement.setAttribute('data-theme', theme.value);
  }
}

/** Apply lang to DOM */
function applyLang() {
  document.documentElement.lang = resolvedLang.value === 'zh' ? 'zh-CN' : 'en';
}

export function initUI() {
  const savedTheme = safeGetItem('oasyce-theme') as 'dark' | 'light' | 'system' | null;
  const savedLang = safeGetItem('oasyce-lang') as 'zh' | 'en' | 'system' | null;

  theme.value = savedTheme ?? 'system';
  lang.value = savedLang ?? 'system';

  applyTheme();
  applyLang();

  // Listen for OS theme changes — re-trigger reactivity when system preference changes
  window.matchMedia?.('(prefers-color-scheme: dark)')
    .addEventListener?.('change', () => {
      if (theme.value === 'system') applyTheme();
    });

  // Load wallet identity then balance + notifications in background
  refreshAccountContext().catch(() => {});
}

/** Cycle: system → dark → light → system */
export function toggleTheme() {
  const order: Array<'system' | 'dark' | 'light'> = ['system', 'dark', 'light'];
  const idx = order.indexOf(theme.value);
  theme.value = order[(idx + 1) % order.length];
  applyTheme();
  safeSetItem('oasyce-theme', theme.value);
}

/** Cycle: system → zh → en → system */
export function toggleLang() {
  const order: Array<'system' | 'zh' | 'en'> = ['system', 'zh', 'en'];
  const idx = order.indexOf(lang.value);
  lang.value = order[(idx + 1) % order.length];
  applyLang();
  safeSetItem('oasyce-lang', lang.value);
}

export function showToast(message: string, type = 'info') {
  // Unique ID: base-36 timestamp + 5 random chars to avoid collisions
  const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  // Resolve i18n key if the message matches a known key (e.g. error keys from client.ts)
  const resolved = i18n.value[message] || message;
  toasts.value = [...toasts.value, { id, message: resolved, type }];
  setTimeout(() => toasts.value = toasts.value.filter(t => t.id !== id), 3000); // 3s auto-dismiss
}

const dict: Record<string, Record<string, string>> = {
  zh: {
    home: '首页', mydata: '资产', explore: '市场', auto: '自动化', network: '网络', loading: '加载中...',
    'hero-title-light': '你的数据和 AI 能力，',
    'hero-title-bold': '值得被定价',
    'hero-sub': '上传文件、发布技能，网络自动定价和结算。',
    protect: '注册数据', protecting: '注册中...', protected: '已注册',
    'drop-browse': '选择文件',
    'describe': '描述', 'describe-hint': '例如：医疗影像、研究数据、创意作品',
    'value': '当前价值', 'owner': '所有者', 'id': '编号',
    'search': '搜索你的数据...', 'no-data': '还没有数据', 'first-data': '上传你的第一份文件，开始赚取收益',
    'delete': '删除记录', 'delete-confirm': '从本地删除这份数据记录？链上状态不受影响。此操作不可恢复。',
    'get-access': '买入', 'quote': '查看报价', 'quoting': '计算中...',
    'pay': '需要支付',
    'confirm-buy': '确认买入', 'buying': '处理中...', 'back': '返回',
    // Access level system
    'al-reputation': '你的信誉', 'al-risk': '风险等级', 'al-max': '最高可用层级',
    'al-L0-name': '查询', 'al-L0-desc': '聚合统计，数据不离开安全区',
    'al-L1-name': '采样', 'al-L1-desc': '脱敏水印样本片段',
    'al-L2-name': '计算', 'al-L2-desc': '代码在安全区执行，仅输出离开',
    'al-L3-name': '交付', 'al-L3-desc': '完整数据交付',
    'al-locked': '信誉不足', 'al-reputation_too_low': '信誉不足',
    'al-exceeds_max_level': '超出资产最高访问级别',
    'al-liability': '份额锁定', 'al-days': '天',
    'al-granted': '访问层级', 'al-bond-paid': '支付金额',
    'identity': '你的身份',
    'no-key': '首次注册数据时自动生成', 'copy': '复制', 'copied': '已复制',
    'again': '继续注册',
    'nav-mydata': '资产', 'nav-mydata-desc': '查看已注册的数据资产',
    'nav-explore': '市场', 'nav-explore-desc': '浏览和交易数据与 AI 能力',
    'nav-network': '网络', 'nav-network-desc': '节点状态与网络信息',
    'cancel': '取消', 'close': '关闭', 'confirm-remove': '确认移除',
    'explore-title': '能力市场',
    'explore-desc': '浏览数据资产与 AI 能力，买入份额或调用服务',
    'explore-search': '搜索数据编号或描述...',
    'discover-hint': '输入意图描述，智能匹配能力...',
    'discover': '智能发现',
    'discover-results': '按相关度排序',
    'explore-empty': '输入编号或关键词，搜索市场中的资产与能力',
    'browse-all': '浏览全部',
    'all': '全部',
    'sort-time': '最新', 'sort-value': '价值',
    'load-more': '加载更多', 'no-more': '没有更多了',
    'view-mydata': '查看资产',
    'type-all': '全部', 'type-data': '数据', 'type-capability': '服务',
    'invoke': '调用', 'invoking': '调用中...',
    'invoke-success': '调用成功',
    'shares-minted': '获得份额',
    'spot-price': '当前价格', 'tags': '标签', 'type': '类型', 'asset-type-data': '数据',
    'buy-success': '购买成功',
    // Earnings & invocation history
    'earnings-tab': '收益', 'total-earnings': '总收益', 'total-invocations': '调用次数',
    'earnings-empty': '注册 AI 能力，开始赚取收益', 'earnings-empty-cta': '注册能力',
    'invocation-history': '调用记录', 'my-invocations': '我的调用', 'invocation-empty': '调用 AI 能力后，记录将显示在这里',
    // Sell quote
    'sell-quote': '卖出报价', 'sell-payout': '预计收入', 'sell-fee': '协议费用', 'sell-burn': '销毁',
    'sell-impact': '价格影响', 'sell-impact-warning': '价格影响较大，请确认', 'sell-confirm': '确认卖出', 'sell-quoting': '计算中...',
    'inv-complete': '确认完成', 'inv-claim': '领取收益', 'inv-completing': '处理中...', 'inv-claiming': '领取中...',
    'inv-complete-success': '已确认完成', 'inv-claim-success': '收益已领取',
    // Global disputes
    'disputes-tab': '争议', 'all-disputes': '全部争议', 'dispute-buyer': '购买者',
    'dispute-no-global': '暂无争议', 'dispute-no-global-hint': '网络运行正常，无争议记录',
    'filter-all': '全部',
    'portfolio': '持仓', 'no-holdings': '暂无持仓', 'no-holdings-hint': '在市场中购买资产后，持仓将显示在这里', 'avg-price': '均价', 'shares': '份额',
    'stake': '质押', 'staking': '质押中...', 'stake-success': '质押成功',
    'validator': '验证者', 'staked': '已质押', 'reputation': '信誉',
    'validator-id': '验证者 ID', 'stake-amount': '质押金额',
    'no-validators': '暂无验证者', 'no-validators-hint': '启动 L1 链节点后，验证者将出现在这里',
    'net-hero-light': '连接全球', 'net-hero-bold': '智能市场',
    'net-hero-sub': '运行节点，提供算力，在市场中赚取收益',
    'net-identity': '身份', 'net-node-id': '节点 ID', 'net-pubkey': '公钥', 'net-created': '创建时间',
    'net-show': '显示', 'net-hide': '隐藏',
    'net-chain-height': '链高度', 'net-peers': '已连接节点',
    'net-no-identity': '尚未生成身份', 'net-init-hint': '运行 oas bootstrap，然后 oas start',
    // AI 算力配置
    'net-ai': 'AI 算力', 'net-ai-desc': '配置你的 AI 能力，为网络提供智能服务并获得 OAS 收益',
    'net-ai-what': '为什么需要 API Key？',
    'net-ai-what-body': '你的节点通过 AI 模型为网络执行任务。你只需要提供一个 API Key（或本地模型地址），Oasyce 会自动调用它来完成工作：',
    'net-ai-use-1': '验证者：AI 自动验证数据质量、检测重复内容、审核元数据合规性',
    'net-ai-use-2': '仲裁者：AI 自动分析争议证据、比对版权信息、生成裁决建议',
    'net-ai-use-3': '你提供算力，网络付你 OAS — 你的 Key 就是你的生产工具',
    'net-ai-supported': '支持的 AI 提供商',
    'net-ai-supported-body': 'Claude (Anthropic)、OpenAI、Ollama (本地)、任意兼容 OpenAI 格式的自定义端点。本地模型无需 API Key，只需填写地址。',
    'net-ai-provider': '选择 AI 提供商',
    'net-ai-key': 'API Key',
    'net-ai-endpoint': '模型地址',
    'net-key-placeholder': '粘贴你的 API Key（sk-... 或 ant-...）',
    'net-key-placeholder-set': '已配置 · 输入新 Key 可覆盖',
    'net-key-save': '保存 Key', 'net-key-update': '更新 Key',
    'net-key-saved': 'API Key 已安全保存',
    'net-key-active': 'AI 已连接',
    'net-key-required': '请先在上方「AI 算力」卡片中配置 API Key',
    'net-endpoint-placeholder': '例如 http://localhost:8080/v1',
    // 节点角色
    'net-role': '节点角色', 'net-role-desc': '配置好 AI 后，选择你在网络中的角色开始赚取收益',
    'net-role-validator': '验证者', 'net-role-arbitrator': '仲裁者',
    'net-role-none': '当前为普通节点。配置 AI 算力后，可以申请成为验证者或仲裁者赚取收益。',
    'net-become-validator': '成为验证者', 'net-become-validator-desc': '质押 OAS + 提供 AI 算力 → 出块赚币',
    'net-become-arbitrator': '成为仲裁者', 'net-become-arbitrator-desc': '提供 AI 算力 → 裁决争议赚币',
    'net-validator-min': '最低质押',
    'net-staked': '已质押',
    'net-role-validator-ok': '验证者注册成功', 'net-role-arbitrator-ok': '仲裁者注册成功',
    'net-val-what': '验证者做什么？',
    'net-val-what-body': '你的 AI 自动完成：打包交易生成区块、验证数据质量（检测伪造/重复）、审核元数据合规性。节点持续运行，无需人工操作。',
    'net-val-earn': '你能赚多少？',
    'net-val-earn-1': '每出一个块获得 4.0 OAS（约每 2 年减半，越早越值钱）',
    'net-val-earn-2': '所有交易手续费的 20% 分给验证者',
    'net-val-earn-3': '质押越多 → 权重越高 → 出块越多 → 赚得越多',
    'net-val-need': '你需要什么？',
    'net-val-need-1': '质押至少 10,000 OAS（锁定期间不可使用）',
    'net-val-need-2': '一个 AI API Key（用于数据质量验证）',
    'net-val-need-3': '节点保持在线 — 长时间离线罚 5%，恶意行为罚 100%，解质押需 28 天',
    'net-arb-what': '仲裁者做什么？',
    'net-arb-what-body': '当有人发起争议（版权纠纷、数据造假等），你的 AI 自动：分析双方证据、比对原始数据指纹、评估版权归属，并生成裁决建议（下架、转移所有权、更正权利等）。',
    'net-arb-earn': '你能赚多少？',
    'net-arb-earn-1': '每次裁决获得仲裁费（由发起方支付，通常 50-500 OAS）',
    'net-arb-earn-2': '裁决越准确 → 信誉越高 → 匹配越多案件 → 赚得越多',
    'net-arb-need': '你需要什么？',
    'net-arb-need-1': '一个 AI API Key（用于证据分析和裁决推理）',
    'net-arb-need-2': '无需质押，但节点需保持在线接收案件',
    'net-arb-tags-hint': '擅长领域（逗号分隔），例如：版权,医疗数据,金融',
    'net-work': '工作收益', 'net-work-desc': '协议自动分配的任务和你的收益统计',
    'net-work-total': '总任务', 'net-work-settled': '已结算',
    'net-work-earned': '累计收益', 'net-work-quality': '平均质量',
    'net-work-failed': '失败', 'net-work-no-tasks': '暂无任务记录', 'net-work-no-tasks-hint': '配置 AI 算力后，协议会自动分配任务',
    'net-work-recent': '最近任务',
    'net-work-type-validation': '验证', 'net-work-type-arbitration': '仲裁',
    'net-work-type-verification': '核实', 'net-work-type-moderation': '审核',
    'net-consensus': '共识状态', 'net-consensus-desc': '当前共识状态 — 周期进度与活跃验证者',
    'net-consensus-epoch': '当前 Epoch', 'net-consensus-slot': '当前 Slot',
    'net-consensus-validators': '活跃验证者', 'net-consensus-staked': '总质押',
    'net-consensus-next-epoch': '下一 Epoch', 'net-consensus-delegate': '委托',
    'net-consensus-delegate-desc': '将 OAS 质押给一个验证者',
    'net-consensus-undelegate': '解除委托', 'net-consensus-undelegate-desc': '撤回已委托的 OAS',
    'net-consensus-amount': '金额 (OAS)', 'net-consensus-validator-id': '验证者 ID',
    'net-consensus-submit': '提交', 'net-consensus-submitting': '提交中...',
    'net-cosmos': 'Cosmos 链', 'net-cosmos-connected': '已连接 — 区块 #{height}', 'net-cosmos-checking': '检查链状态...',
    'net-cosmos-connecting': '正在连接 Cosmos 链 REST API...',
    'net-cosmos-unreachable': 'Cosmos 链 REST API 不可达 (localhost:1317)，显示 Python 后端数据。',
    'net-cosmos-error': '错误',
    'net-cosmos-retry': '重试', 'net-cosmos-refresh': '刷新',
    'net-cosmos-chain-id': '链 ID', 'net-cosmos-node-id': '节点 ID', 'net-cosmos-moniker': '名称',
    'net-cosmos-sdk': 'Cosmos SDK', 'net-cosmos-app-ver': '应用版本',
    'net-cosmos-block-height': '区块高度', 'net-cosmos-block-time': '出块时间', 'net-cosmos-block-hash': '区块哈希',
    'net-cosmos-validators': 'Cosmos 验证者', 'net-cosmos-val-loading': '加载验证者...',
    'net-cosmos-no-validators': '未找到已绑定验证者',
    'net-cosmos-jailed': '已监禁',
    'net-watermark': '水印工具', 'net-watermark-desc': '追踪数据在网络中的流转',
    'net-embed': '嵌入水印', 'net-embed-desc': '把身份信息刻进文件',
    'net-extract': '提取水印', 'net-extract-desc': '读出文件的签名信息',
    'net-trace': '追踪分发', 'net-trace-desc': '查看文件的流转记录',
    'created-at': '创建时间',
    'wm-file-path': '文件路径',
    'wm-caller-id': '调用者 ID',
    'wm-embed-btn': '嵌入水印',
    'wm-embedding': '嵌入中...',
    'wm-extract-btn': '提取水印',
    'wm-extracting': '提取中...',
    'wm-asset-id': '资产编号',
    'wm-list-btn': '查询分发记录',
    'wm-listing': '查询中...',
    'wm-fingerprint': '指纹',
    'wm-caller': '调用者',
    'wm-timestamp': '时间',
    'wm-watermarked-path': '水印文件',
    'wm-no-records': '暂无分发记录', 'wm-no-records-hint': '嵌入水印后，分发记录将出现在这里',
    'val-staked': '质押量',
    'val-reputation': '信誉',
    'automation': '自动化', 'automation-desc': '管理自动注册与交易规则，审批待确认任务',
    'auto-queue': '任务队列', 'auto-rules': '规则设置', 'coming-soon': '即将推出',
    'pending-tasks': '待确认', 'completed-tasks': '已完成',
    'approve-all': '全部通过', 'all-approved': '已全部通过',
    'reject-all': '全部否决', 'all-rejected': '已全部否决',
    'queue-empty': '没有待处理任务', 'queue-empty-hint': '扫描一个目录，或等待 Agent 提交任务',
    'trust-level-desc': '控制 Agent 的自主注册和交易权限',
    'trust-0-desc': '所有操作需手动确认',
    'trust-1-desc': '高置信度自动执行，其余需确认',
    'trust-2-desc': '全部自动执行，仅异常需确认',
    'auto-threshold-desc': '置信度高于阈值的任务将自动通过',
    'threshold-strict': '严格', 'threshold-strict-desc': '仅极高置信度自动通过，大部分需确认',
    'threshold-balanced': '均衡', 'threshold-balanced-desc': '多数可信任务自动通过，可疑任务需确认',
    'threshold-permissive': '宽松', 'threshold-permissive-desc': '大部分任务自动通过，仅低置信度需确认',
    'scan-directory': '扫描目录', 'scan-directory-desc': '扫描本地文件夹，发现可注册的数据资产',
    'agent-executor': '执行 Agent', 'agent-executor-desc': '选择执行注册和交易任务的 Agent',
    'custom-agent-config': '配置自定义 Agent',
    'custom-agent-name': 'Agent 名称',
    'custom-agent-endpoint': 'API 端点 (例如 https://api.example.com/v1)',
    'custom-agent-test': '测试连接',
    'agent-setup-hint': '需要先在本地安装并配置该 Agent，才能用于自动化任务。',
    'scan-path-hint': '输入目录路径，例如 ~/Documents',
    'scan-btn': '扫描', 'scanning': '扫描中...',
    'scan-done': '扫描完成', 'scan-found': '扫描文件', 'scan-added': '加入收件箱',
    'trust-settings': '信任设置', 'trust-level': '信任等级',
    'trust-0': '手动确认', 'trust-1': '半自动', 'trust-2': '全自动',
    'auto-threshold': '自动确认阈值',
    'inbox-no-match': '没有匹配的项目',
    'status-pending': '待确认', 'status-approved': '已通过', 'status-rejected': '已拒绝',
    'approve': '通过', 'reject': '拒绝', 'edit': '编辑', 'save': '保存',
    'approved': '已通过', 'rejected': '已拒绝', 'saved': '已保存',
    'edit-name': '资产名称', 'edit-tags': '标签（逗号分隔）', 'edit-desc': '描述',
    'rights-type': '权利类型',
    'rights-original': '原创', 'rights-co_creation': '共创', 'rights-licensed': '授权转售', 'rights-collection': '个人收藏',
    'co-creators': '共创者', 'co-creator-address': '地址',
    'add-co-creator': '添加共创者', 'remove-co-creator': '移除',
    'co-creators-hint': '共创至少需要2人，份额合计100%',
    'disputed': '争议中', 'dispute': '发起争议', 'dispute-reason': '争议原因',
    'dispute-confirm': '确认提交', 'dispute-submitting': '提交中...', 'dispute-success': '争议已提交',
    'dispute-reason-hint': '请描述争议原因',
    'arbitrators': '仲裁者', 'arbitrator-score': '匹配度',
    'no-arbitrators': '暂无可用仲裁者', 'arbitrator-auto': '系统自动匹配仲裁者',
    'dispute-status': '争议状态', 'dispute-pending': '待仲裁',
    'drop-folder-hint': '支持拖入文件夹',
    'price-model': '定价方式',
    'price-model-auto': '市场定价', 'price-model-fixed': '固定价格', 'price-model-floor': '保底价格',
    'price-model-auto-desc': '买家越多价格越高，供需自动调节',
    'price-model-fixed-desc': '你设定价格，买家按此价购买',
    'price-model-floor-desc': '市场定价，但不低于你设定的底价',
    'price-input-hint': '输入你期望的价格', 'price-floor-hint': '输入最低价格',
    'register-data': '注册数据', 'publish-cap': '上架能力',
    'cap-name': '名称', 'cap-name-hint': '例如：图像风格迁移',
    'cap-desc-hint': '输入图片，输出指定风格的新图片',
    'cap-desc-guide': '描述输入输出，帮助别人理解如何使用',
    'cap-guide': '将你的 AI 能力上架到市场，供全网发现和调用。',
    'cap-published': '能力已上架',
    'cap-endpoint': '端点 URL', 'cap-endpoint-hint': '例如：https://api.example.com/translate',
    'cap-api-key': 'API Key', 'cap-api-key-hint': '将加密存储，不会暴露给调用者',
    'cap-price': '每次调用价格 (OAS)', 'cap-tags': '标签', 'cap-tags-hint': '逗号分隔，例如：nlp,翻译',
    'cap-rate-limit': '速率限制', 'cap-rate-limit-hint': '每分钟最大调用次数',
    'cap-advanced': '高级设置',
    'my-caps': '我的能力', 'my-data-tab': '数据资产',
    'cap-total-calls': '总调用', 'cap-success-rate': '成功率', 'cap-avg-latency': '平均延迟',
    'cap-earnings': '收益统计', 'cap-total-earned': '总收益',
    'cap-endpoint-url': '端点', 'cap-no-caps': '还没有上架能力',
    'cap-no-caps-hint': '在首页上架你的第一个 AI 能力', 'cap-register-cta': '前往首页',
    'cap-invoke-input': '输入 (JSON)', 'cap-invoke-input-hint': '例如：{"text": "hello"}',
    'dispute-resolved': '已裁决', 'dispute-dismissed': '已驳回',
    'remedy-delist': '下架', 'remedy-transfer': '转移所有权', 'remedy-rights_correction': '更正权利类型', 'remedy-share_adjustment': '调整份额',
    'delisted': '已下架',
    'net-retry': '重新检测',
    'files': '个文件',
    'explore-browse': '浏览市场中的数据与 AI 能力',
    'explore-quickstart': '快速开始',
    'explore-quickstart-hint': '在终端中运行以下命令，开始使用市场',
    'explore-qs-demo': '运行协议演示',
    'explore-qs-register': '注册你的第一份资产',
    'explore-qs-capability': '注册一项 AI 能力',
    'portfolio-hint': '在市场中交易后，持仓将显示在这里', 'portfolio-browse-cta': '浏览市场',
    'stake-hint': '质押 OAS 到验证者节点，参与网络治理并获得收益',
    'co-creators-sum': '份额合计',
    'removed': '已移除',
    'hash-changed': '已变更',
    're-register': '重新注册',
    'file-missing': '文件丢失',
    'error-generic': '未能完成，请再试一次',
    'error-unauthorized': '身份验证失败 — 请确认节点正在运行',
    'error-rate-limit': '请求过于频繁，请等几秒再试',
    'error-not-found': '该内容不存在或已被移除',
    'error-server': '服务器遇到问题，请稍后再试',
    'error-timeout': '请求超时 — 请检查网络连接后重试',
    'error-network': '无法连接到节点 — 请确认已运行 oas start',
    'invoke-result': '返回结果',
    'net-cat-config': '配置', 'net-cat-chain': '网络与共识', 'net-cat-tools': '工具', 'net-cat-community': '社区',
    'net-consensus-loading': '加载共识数据...',
    // About panel
    'about-version': 'v2.3.1',
    'about-desc': 'AI-first 数据权利与能力合同网络。先 bootstrap，再让 Agent 自动扫描、注册、报价和结算。',
    'about-tab-overview': '概览',
    'about-tab-start': '快速开始',
    'about-tab-arch': '技术架构',
    'about-tab-econ': '经济模型',
    'about-tab-update': '维护更新',
    'about-tab-links': '链接',
    'about-how': 'Oasyce 让 Agent 自主注册数据资产、发现能力、完成托管结算，并把 DataVault 作为默认的本地安全筛选层。文件先经扫描和风险判定，再进入报价、购买、交付和反馈闭环。',
    'about-quickstart': '1. pip install oasyce\n2. oas bootstrap         # 自更新 + 钱包 + DataVault 就绪\n3. oas demo              # 跑一遍 register -> quote -> buy\n4. oas start             # 启动节点 + 仪表盘\n5. 可选: oas doctor      # 诊断环境',
    'about-arch': '核心层级:\n\u2022 Schema Registry \u2014 统一验证 data/capability/oracle/identity 四种资产\n\u2022 引擎管道 \u2014 扫描 \u2192 分类 \u2192 元数据 \u2192 PoPc 证书 \u2192 注册\n\u2022 发现引擎 \u2014 Recall (广召回) \u2192 Rank (信任+经济) + 反馈循环\n\u2022 结算引擎 \u2014 联合曲线定价、托管、份额分配\n\u2022 访问控制 \u2014 L0 元数据 / L1 采样 / L2 计算 / L3 完整\n\u2022 P2P 网络 \u2014 Ed25519 身份、gossip 同步、PoS 共识\n\u2022 风险引擎 \u2014 自动分级 (public / internal / sensitive)',
    'about-econ': '代币: OAS\n\n定价: 联合曲线 (储备率 0.35) \u2014 买家越多价格越高\n份额: 早期买家获利更多 (递减: 100% \u2192 80% \u2192 60% \u2192 40%)\n权利系数: 原创 1.0x / 共创 0.9x / 授权 0.7x / 收藏 0.3x\n质押: 验证者质押 OAS 出块并获得奖励\n区块奖励: 4.0 OAS (主网)，每约 100 万块减半\n托管: 执行前锁定资金，质量验证后释放',
    'about-update': '更新:\n  oas update\n  # 或: python -m pip install --upgrade --upgrade-strategy eager oasyce odv\n\n首次准备:\n  oas bootstrap\n\n从源码构建:\n  git clone https://github.com/Shangri-la-0428/oasyce-net\n  cd oasyce-net && pip install -e .\n\n运行测试:\n  python -m pytest tests/ -v\n\n贡献: Fork \u2192 Branch \u2192 PR (详见 CONTRIBUTING.md)',
    'about-link-intro': '项目介绍',
    'about-link-intro-d': '什么是 Oasyce，为什么重要',
    'about-link-whitepaper': '白皮书',
    'about-link-whitepaper-d': '完整协议设计与经济模型论文',
    'about-link-docs': '协议概览',
    'about-link-docs-d': '技术参考、API 与架构',
    'about-link-github-project': 'GitHub (项目)',
    'about-link-github-project-d': '规范、文档与路线图',
    'about-link-github-engine': 'GitHub (引擎)',
    'about-link-github-engine-d': '协议实现、CLI、Dashboard 与测试',
    'about-link-discord': 'Discord 社区',
    'about-link-discord-d': '聊天、支持与治理',
    'about-link-contact': '联系我们',
    // Agent Scheduler
    'agent-schedule': '定时任务', 'agent-schedule-desc': '让插件自主运行，定时扫描、注册和交易',
    'agent-enabled': '启用定时任务', 'agent-disabled': '已停用',
    'agent-running': '运行中', 'agent-interval': '执行间隔', 'agent-interval-hours': '小时',
    'agent-scan-paths': '扫描目录', 'agent-scan-paths-hint': '每行一个目录路径',
    'agent-auto-register': '自动注册', 'agent-auto-trade': '自动交易',
    'agent-auto-trade-desc': '自动购买匹配标签的能力',
    'agent-trade-tags': '交易标签', 'agent-trade-tags-hint': '逗号分隔，如 nlp,translation',
    'agent-trade-max': '单次最大花费',
    'agent-last-run': '上次执行', 'agent-next-run': '下次执行',
    'agent-total-runs': '总执行次数', 'agent-total-registered': '总注册数', 'agent-total-errors': '总错误数',
    'agent-run-now': '立即执行', 'agent-history': '执行历史',
    'agent-save-config': '保存配置', 'agent-no-history': '暂无执行记录', 'agent-no-history-hint': '启用定时任务并执行一次后，记录将显示在这里',
    'balance-label': '余额',
    'earnings': '收益',
    'theme-system': '跟随系统主题',
    'lang-system': '跟随系统语言',
    'recent-trades': '最近交易',
    'wallet-needed': '先准备或接入账号，才能注册和交易',
    'wallet': '本地钱包',
    'account': '账号',
    'mode': '模式',
    'create-wallet': '创建账户',
    'skip-to-content': '跳至内容',
    'wallet-created': '账户已创建',
    'onboard-step1': '准备设备',
    'onboard-step1-hint': '先决定这台设备是创建新账户，还是接入已有账户。',
    'onboard-step2': '领取新手奖励',
    'onboard-step2-hint': '完成一个小任务，获得免费积分',
    'onboard-step2-btn': '领取积分',
    'onboard-step2-mining': '正在计算...',
    'register-success': '获得 {amount} OAS',
    'onboard-step3': '上传你的第一个文件',
    'onboard-step3-hint': '拖入文件即可，高级选项以后再说',
    'onboard-welcome': '三步开始',
    'onboard-welcome-hint': '先准备这台设备的账号，再进入市场和注册流程。',
    'gate-create-body': '先把这台设备接入正确的经济账号。第一次使用就创建本机账号；如果你已经有主设备，就导入它导出的连接文件。',
    'gate-funds-body': '完成一个小计算任务，获取你的第一笔积分。',
    'account-entry-title': '连接这台设备',
    'account-entry-question': '这台设备要创建新账户吗？',
    'account-entry-hint': '你可以创建一个新账户，或者接入另一台设备上已经在用的账户。',
    'account-entry-create': '创建新账户',
    'account-entry-create-hint': '把这台设备作为主设备，生成可交易的本地账户。',
    'account-entry-existing': '使用已有账户',
    'account-entry-existing-hint': '从主设备导入连接文件，或在你明确知道信息时手动接入。',
    'account-entry-back': '返回上一步',
    'account-entry-cancel': '先不处理',
    'account-entry-advanced': '手动接入',
    'prepare-device': '在这台设备创建',
    'prepare-device-hint': '为这台设备创建可签名的公测身份，并连接默认环境。',
    'join-existing': '接入已有账号',
    'join-existing-bundle': '导入连接文件',
    'join-existing-advanced': '高级手动接入',
    'join-existing-readonly': '只读接入',
    'join-existing-signing': '带 signer 接入',
    'join-bundle-file': '连接文件',
    'join-bundle-file-hint': '选择主设备导出的 oasyce-device.json',
    'join-bundle-hint': '推荐路径。导入主设备导出的连接文件后，这台设备会自动接入同一账号。',
    'join-bundle-warning': '连接文件可能包含可交易凭据。请只通过你信任的渠道传输，并在导入后删除文件。',
    'join-bundle-invalid': '连接文件不是有效的 JSON 文件',
    'join-bundle-submit': '导入连接文件',
    'join-bundle-selected': '已选择',
    'join-advanced-hint': '只有在你明确知道账号地址，或这台机器本地已经有同一个 signer 时，才使用高级手动接入。',
    'join-account-address': '账号地址',
    'join-account-address-hint': '输入已有账号地址，例如 oasyce1...',
    'join-signer-name': 'Signer 名称',
    'join-signer-name-hint': '输入这台机器本地已有的 signer 名称',
    'join-readonly-hint': '适合浏览市场、查看持仓和 AI 协作，不会直接发起链上交易。',
    'join-signing-hint': '只有这台机器本地已经存在同一个 signer，才能用此模式手动交易。',
    'device-prepare-success': '这台设备的账号已就绪',
    'device-join-success': '设备已接入该账号',
    'device-export-title': '连接另一台设备',
    'device-export-hint': '主设备可以导出一个连接文件。另一台设备导入后，就会接入同一账号。',
    'device-export-signing': '导出可交易连接文件',
    'device-export-readonly': '导出只读连接文件',
    'device-export-success': '连接文件已导出',
    'device-export-readonly-success': '只读连接文件已导出',
    'device-export-signer-warning': '可交易连接文件包含签名凭据。请只通过你信任的渠道传输，并在导入后删除文件。',
    'device-manage-title': '管理这台设备',
    'device-manage-hint': '你可以改接其他账户，或撤回这台设备当前的访问。',
    'device-switch-account': '改用其他账户',
    'device-revoke': '断开这台设备',
    'device-revoke-body': '如果刚才点错了，先断开这台设备，再重新接入正确的账户。',
    'device-revoke-confirm': '确认断开',
    'device-revoke-success': '这台设备已断开当前账户',
    'readonly-device-title': '已接入现有账户',
    'readonly-device-body': '这台设备已经连接到同一个经济账号，但当前是只读模式。',
    'readonly-device-upgrade': '如果要在这台设备上手动注册、买卖或质押，重新导入主设备导出的可交易连接文件即可。',
    'readonly-device-cta-market': '浏览市场',
    'readonly-device-cta-network': '查看网络',
    'account-mode-readonly': '只读',
    'account-mode-signing': '可签名',
    'success-outcome': '已上线',
    'success-outcome-body': '你的文件现在可以被发现和购买了。收益会自动到账。',
    'success-cta-market': '去市场看看',
    'success-cta-more': '再上传一个',
    'advanced-options-hint': '高级选项可以在"我的数据"页面修改',
    'vet-register-cta': '上传更多',
    'total-earned': '总收入',
    'recent-transactions': '最近交易',
    'no-transactions': '暂无交易记录', 'no-transactions-hint': '买入或卖出资产后，交易记录将显示在这里',
    // Data Preview
    'preview': '预览',
    'preview-loading': '加载预览...',
    'preview-metadata': '元数据',
    'preview-content': '内容预览',
    'preview-locked': '购买以查看更多',
    'preview-truncated': '内容已截断',
    // Buyer Dispute/Refund
    'dispute-file': '提交争议',
    'dispute-reason-select': '选择原因',
    'dispute-evidence': '证据描述',
    'dispute-evidence-hint': '请详细描述问题...',
    'dispute-created': '创建时间', 'dispute-resolved-at': '解决时间', 'dispute-resolution': '解决方案',
    'dispute-reason-quality': '数据质量问题',
    'dispute-reason-mismatch': '内容与描述不符',
    'dispute-reason-copyright': '版权问题',
    'dispute-reason-fraud': '欺诈行为',
    'dispute-reason-other': '其他',
    'dispute-filed': '争议已提交',
    'my-disputes': '我的争议',
    'dispute-no-disputes': '暂无争议记录', 'dispute-no-disputes-hint': '对已购买的资产有疑虑时，可在这里提交争议',
    'dispute-open': '处理中',
    'report-issue': '报告问题',
    // Notifications
    'notifications': '通知',
    'notifications-empty': '暂无通知',
    'notifications-mark-read': '全部已读',
    // Sell shares
    'sell': '卖出', 'selling': '卖出中...',
    'sell-amount-hint': '输入要卖出的份额数',
    'sell-slippage': '最大滑点', 'sell-success': '卖出成功',
    // Transaction history
    'tx-history': '交易记录', 'tx-no-history': '暂无交易记录', 'tx-no-history-hint': '交易完成后，历史记录将自动出现',
    // Jury voting
    'jury-vote': '陪审投票', 'jury-voting': '投票中...',
    'jury-verdict': '裁决', 'jury-uphold': '支持消费者', 'jury-reject': '支持提供者',
    'jury-vote-success': '投票已提交',
    // Dispute resolution
    'resolve-dispute': '裁决争议', 'resolving': '裁决中...',
    'resolve-remedy': '处置方式', 'resolve-details': '详情',
    'resolve-success': '争议已裁决',
    // Evidence submission
    'submit-evidence': '提交证据', 'submitting-evidence': '提交中...',
    'evidence-hash': '证据哈希', 'evidence-type': '证据类型',
    'evidence-desc': '证据描述', 'evidence-success': '证据已提交',
    'evidence-type-document': '文档', 'evidence-type-screenshot': '截图',
    'evidence-type-log': '日志', 'evidence-type-other': '其他',
    // Metadata update
    'metadata-tags': '编辑标签',
    'metadata-updated': '元数据已更新',
    // Manual re-register
    're-register-manual': '更新版本',
    // Asset lifecycle
    'asset-lifecycle': '资产生命周期',
    'asset-lifecycle-hint': '退市 → 7天冷却 → 终止 → 认领清算',
    'asset-shutdown': '发起退市',
    'asset-shutdown-confirm': '确认发起退市？进入7天冷却期，保护现有持仓者，期间不可撤回。',
    'asset-shutdown-success': '退市已发起，7天后可终止',
    'asset-terminate': '终止资产', 'asset-terminate-success': '资产已终止',
    'asset-claim': '认领清算', 'asset-claim-success': '清算已认领',
    'asset-status-label': '状态',
    'asset-status-active': '活跃', 'asset-status-shutdown': '退市冷却中', 'asset-status-terminated': '已终止',
    // Version history
    'version-history': '版本历史', 'no-versions': '暂无版本记录',
    'version-number': '版本', 'version-time': '时间',
    // Governance
    'governance': '治理', 'governance-desc': '创建提案并参与投票',
    'gov-proposals': '提案列表', 'gov-no-proposals': '暂无提案', 'gov-no-proposals-hint': '提交第一个提案，开始参与协议治理',
    'gov-propose': '提交提案', 'gov-proposing': '提交中...',
    'gov-title': '标题', 'gov-description': '描述', 'gov-deposit': '押金 (OAS)',
    'gov-propose-success': '提案已提交',
    'gov-vote-yes': '赞成', 'gov-vote-no': '反对', 'gov-vote-abstain': '弃权',
    'gov-vote-success': '投票已提交',
    'gov-status': '状态', 'gov-chain-only': '治理功能已迁移到 L1 链',
    // Wallet export/import
    'wallet-export': '导出钱包', 'wallet-import': '导入钱包',
    'wallet-import-desc': '从备份文件恢复钱包',
    'wallet-exported': '钱包已导出', 'wallet-imported': '钱包已导入',
    'wallet-import-hint': '粘贴导出的钱包 JSON 内容',
    // Fingerprint list
    'fingerprint-list': '指纹记录', 'fingerprint-no-records': '暂无指纹记录', 'fingerprint-no-records-hint': '输入资产编号查询其指纹记录',
    'fingerprint-asset': '输入资产编号',
    // Reputation
    'node-reputation': '信誉分',
    // L0-L3 access operations
    'access-query': 'L0 查询', 'access-sample': 'L1 采样',
    'access-compute': 'L2 计算', 'access-deliver': 'L3 交付',
    'access-op-running': '执行中...',
    'access-result': '结果',
    // Task bounty (AHRP)
    'bounty': '悬赏任务',
    'bounty-post': '发布任务', 'bounty-posting': '发布中...',
    'bounty-list': '可用任务', 'bounty-no-tasks': '暂无可用任务', 'bounty-no-tasks-hint': '发布一个悬赏任务，或等待他人发布',
    'bounty-description': '任务描述', 'bounty-budget': '预算 (OAS)',
    'bounty-deadline': '截止时间 (小时)', 'bounty-capabilities': '所需能力',
    'bounty-capabilities-hint': '逗号分隔，例如 nlp,translation',
    'bounty-strategy': '选择策略', 'bounty-min-rep': '最低信誉',
    'bounty-strategy-weighted': '综合评分', 'bounty-strategy-price': '最低价',
    'bounty-strategy-reputation': '最高信誉', 'bounty-strategy-requester': '手动选择',
    'bounty-bid': '提交竞标', 'bounty-bidding': '竞标中...',
    'bounty-bid-price': '竞标价格', 'bounty-bid-seconds': '预计耗时 (秒)',
    'bounty-bid-rep': '信誉分', 'bounty-bid-success': '竞标已提交',
    'bounty-select': '选择执行者', 'bounty-selecting': '选择中...',
    'bounty-complete': '确认完成', 'bounty-completing': '确认中...',
    'bounty-cancel': '取消任务', 'bounty-cancelling': '取消中...',
    'bounty-bids': '竞标', 'bounty-bids-count': '竞标数',
    'bounty-requester': '发布者', 'bounty-assigned': '执行者',
    'bounty-post-success': '任务已发布', 'bounty-select-success': '已选择执行者',
    'bounty-complete-success': '任务已完成', 'bounty-cancel-success': '任务已取消',
    // Contribution proof
    'contribution': '贡献证明', 'contribution-desc': '证明数据由你创作，并验证他人的贡献证书',
    'contribution-prove': '生成证明', 'contribution-proving': '生成中...',
    'contribution-verify': '验证证明', 'contribution-verifying': '验证中...',
    'contribution-file': '文件路径', 'contribution-creator': '创作者密钥',
    'contribution-source': '来源类型', 'contribution-result': '证明结果',
    'contribution-valid': '验证通过', 'contribution-invalid': '验证失败',
    'contribution-prove-success': '贡献证明已生成', 'error-invalid-json': 'JSON 格式无效',
    'contribution-certificate': '证书 JSON', 'contribution-content-hash': '内容哈希',
    'contribution-semantic': '语义指纹', 'contribution-timestamp': '时间戳',
    // Leakage budget
    'leakage': '泄漏预算', 'leakage-desc': '查看代理对数据资产的剩余访问额度', 'yes': '是', 'no': '否',
    'leakage-check': '查询预算', 'leakage-checking': '查询中...',
    'leakage-reset': '重置预算', 'leakage-resetting': '重置中...',
    'leakage-agent': '代理 ID', 'leakage-asset': '资产编号',
    'leakage-remaining': '剩余预算', 'leakage-used': '已使用',
    'leakage-budget-total': '总预算', 'leakage-queries': '查询次数',
    'leakage-exhausted': '预算已耗尽', 'leakage-reset-success': '预算已重置',
    // Cache management
    'cache': '缓存管理', 'cache-stats': '缓存统计',
    'cache-total': '总计', 'cache-active': '有效', 'cache-expired': '过期',
    'cache-purge': '清理过期', 'cache-purging': '清理中...',
    'cache-purge-success': '已清理过期缓存', 'cache-db-path': '数据库路径',
    'error-boundary-title': '页面加载出错', 'error-boundary-retry': '重试',
    'preview-size': '大小',
    // Feedback
    'feedback': '反馈', 'feedback-desc': 'AI 代理可在此提交 Bug 报告或改进建议',
    'feedback-submit': '提交反馈', 'feedback-submitting': '提交中...',
    'feedback-message': '反馈内容', 'feedback-message-hint': '描述你发现的问题或建议...',
    'feedback-type': '类型', 'feedback-type-bug': 'Bug', 'feedback-type-suggestion': '建议', 'feedback-type-other': '其他',
    'feedback-agent': '代理 ID', 'feedback-agent-hint': '提交反馈的代理标识',
    'feedback-context': '上下文', 'feedback-context-hint': '相关上下文 (JSON)',
    'feedback-success': '反馈已提交', 'feedback-list': '反馈记录',
    'feedback-no-items': '暂无反馈', 'feedback-no-items-hint': '还没有收到 AI 代理的反馈',
    'feedback-status': '状态',
    'file-too-large': '文件过大（最大 100 MB）',
    'partial-failure': '部分操作失败',
    // Invocation lifecycle
    'invocation_completed': '已完成（挑战窗口）',
    'invocation_disputed': '已争议',
    'challenge_window': '挑战窗口',
    'claim_payment': '认领付款',
  },
  en: {
    home: 'Home', mydata: 'My Data', explore: 'Market', auto: 'Automation', network: 'Network', loading: 'Loading...',
    'hero-title-light': 'Your data and AI skills',
    'hero-title-bold': 'deserve a price',
    'hero-sub': 'Upload files, publish capabilities. The network prices and settles automatically.',
    protect: 'Register', protecting: 'Registering...', protected: 'Registered',
    'drop-browse': 'choose file',
    'describe': 'Description', 'describe-hint': 'e.g. medical imaging, research data, creative work',
    'value': 'Value', 'owner': 'Owner', 'id': 'ID',
    'search': 'Search your data...', 'no-data': 'No data yet', 'first-data': 'Upload your first file to start earning',
    'delete': 'Delete record', 'delete-confirm': 'Delete this local record? On-chain state is not affected. This cannot be undone.',
    'get-access': 'Buy', 'quote': 'Get quote', 'quoting': 'Calculating...',
    'pay': 'You pay',
    'confirm-buy': 'Confirm buy', 'buying': 'Processing...', 'back': 'Back',
    // Access level system
    'al-reputation': 'Your reputation', 'al-risk': 'Risk level', 'al-max': 'Max access level',
    'al-L0-name': 'Query', 'al-L0-desc': 'Aggregated stats only — raw data never leaves the server',
    'al-L1-name': 'Sample', 'al-L1-desc': 'Redacted and watermarked sample fragments',
    'al-L2-name': 'Compute', 'al-L2-desc': 'Your code runs server-side — only results are returned',
    'al-L3-name': 'Deliver', 'al-L3-desc': 'Full data delivery',
    'al-locked': 'Insufficient reputation', 'al-reputation_too_low': 'Insufficient reputation',
    'al-exceeds_max_level': 'Exceeds asset max access level',
    'al-liability': 'Share lock', 'al-days': 'days',
    'al-granted': 'Access level', 'al-bond-paid': 'Amount paid',
    'identity': 'Your identity',
    'no-key': 'Auto-generated on first registration', 'copy': 'Copy', 'copied': 'Copied',
    'again': 'Register another',
    'nav-mydata': 'My data', 'nav-mydata-desc': 'View your registered data assets',
    'nav-explore': 'Market', 'nav-explore-desc': 'Browse and trade data & AI capabilities',
    'nav-network': 'Network', 'nav-network-desc': 'Node status and network info',
    'cancel': 'Cancel', 'close': 'Close', 'confirm-remove': 'Yes, remove',
    'explore-title': 'Capability Market',
    'explore-desc': 'Browse and trade data assets and AI capabilities',
    'explore-search': 'Search by ID or description...',
    'discover-hint': 'Describe your intent to discover capabilities...',
    'discover': 'Discover',
    'discover-results': 'Ranked by relevance',
    'explore-empty': 'Enter an asset ID or keyword to search',
    'browse-all': 'Browse all',
    'all': 'All',
    'sort-time': 'Latest', 'sort-value': 'Value',
    'load-more': 'Load more', 'no-more': 'No more results',
    'view-mydata': 'View my data',
    'type-all': 'All', 'type-data': 'Data', 'type-capability': 'Services',
    'invoke': 'Invoke', 'invoking': 'Invoking...',
    'invoke-success': 'Invocation complete',
    'shares-minted': 'Shares minted',
    'spot-price': 'Current price', 'tags': 'Tags', 'type': 'Type', 'asset-type-data': 'Data',
    'buy-success': 'Purchase complete',
    // Earnings & invocation history
    'earnings-tab': 'Earnings', 'total-earnings': 'Total earnings', 'total-invocations': 'Invocations',
    'earnings-empty': 'Register a capability to start earning', 'earnings-empty-cta': 'Register capability',
    'invocation-history': 'Invocation history', 'my-invocations': 'My invocations', 'invocation-empty': 'Invoke a capability to see your history here',
    // Sell quote
    'sell-quote': 'Sell quote', 'sell-payout': 'Expected payout', 'sell-fee': 'Protocol fee', 'sell-burn': 'Burned',
    'sell-impact': 'Price impact', 'sell-impact-warning': 'High price impact, please confirm', 'sell-confirm': 'Confirm sell', 'sell-quoting': 'Calculating...',
    'inv-complete': 'Mark complete', 'inv-claim': 'Claim earnings', 'inv-completing': 'Processing...', 'inv-claiming': 'Claiming...',
    'inv-complete-success': 'Marked as complete', 'inv-claim-success': 'Earnings claimed',
    // Global disputes
    'disputes-tab': 'Disputes', 'all-disputes': 'All disputes', 'dispute-buyer': 'Buyer',
    'dispute-no-global': 'No disputes', 'dispute-no-global-hint': 'Network running smoothly, no disputes filed',
    'filter-all': 'All',
    'portfolio': 'Portfolio', 'no-holdings': 'No holdings yet', 'no-holdings-hint': 'Buy assets on the Market tab to see your holdings here', 'avg-price': 'Avg price', 'shares': 'Shares',
    'stake': 'Stake', 'staking': 'Staking...', 'stake-success': 'Stake confirmed',
    'validator': 'Validator', 'staked': 'Staked', 'reputation': 'Reputation',
    'validator-id': 'Validator ID', 'stake-amount': 'Stake amount',
    'no-validators': 'No validators yet', 'no-validators-hint': 'Validators will appear here once the L1 chain is running',
    'net-hero-light': 'Connected to the', 'net-hero-bold': 'intelligence market.',
    'net-hero-sub': 'Run a node, contribute compute, earn from the market.',
    'net-identity': 'Identity', 'net-node-id': 'Node ID', 'net-pubkey': 'Public Key', 'net-created': 'Created',
    'net-show': 'Show', 'net-hide': 'Hide',
    'net-chain-height': 'Chain height', 'net-peers': 'Connected peers',
    'net-no-identity': 'No identity yet', 'net-init-hint': 'Run oas bootstrap, then oas start',
    // AI compute config
    'net-ai': 'AI Compute', 'net-ai-desc': 'Configure your AI capability to provide intelligence to the network and earn OAS',
    'net-ai-what': 'Why do I need an API Key?',
    'net-ai-what-body': 'Your node uses an AI model to perform tasks for the network. Just provide an API Key (or local model address) and Oasyce handles the rest:',
    'net-ai-use-1': 'Validators: AI auto-verifies data quality, detects duplicates, audits metadata compliance',
    'net-ai-use-2': 'Arbitrators: AI auto-analyzes dispute evidence, compares copyright info, generates rulings',
    'net-ai-use-3': 'You provide compute, the network pays you OAS — your Key is your production tool',
    'net-ai-supported': 'Supported AI providers',
    'net-ai-supported-body': 'Claude (Anthropic), OpenAI, Ollama (local), or any OpenAI-compatible custom endpoint. Local models need no API Key — just enter the address.',
    'net-ai-provider': 'AI Provider',
    'net-ai-key': 'API Key',
    'net-ai-endpoint': 'Model Endpoint',
    'net-key-placeholder': 'Paste your API Key (sk-... or ant-...)',
    'net-key-placeholder-set': 'Configured · enter a new key to replace',
    'net-key-save': 'Save Key', 'net-key-update': 'Update Key',
    'net-key-saved': 'API Key saved securely',
    'net-key-active': 'AI Connected',
    'net-key-required': 'Please configure your API Key in the AI Compute card above first',
    'net-endpoint-placeholder': 'e.g. http://localhost:8080/v1',
    // Node role
    'net-role': 'Node Role', 'net-role-desc': 'Once AI is configured, choose your role to start earning',
    'net-role-validator': 'Validator', 'net-role-arbitrator': 'Arbitrator',
    'net-role-none': 'Standard peer node. Configure AI compute above, then apply as validator or arbitrator to earn OAS.',
    'net-become-validator': 'Become Validator', 'net-become-validator-desc': 'Stake OAS + provide AI compute → produce blocks, earn tokens',
    'net-become-arbitrator': 'Become Arbitrator', 'net-become-arbitrator-desc': 'Provide AI compute → resolve disputes, earn fees',
    'net-validator-min': 'Minimum stake',
    'net-staked': 'Staked',
    'net-role-validator-ok': 'Registered as validator', 'net-role-arbitrator-ok': 'Registered as arbitrator',
    'net-val-what': 'What does your node do?',
    'net-val-what-body': 'Your AI automatically: bundles transactions into blocks, verifies data quality (detects forgery/duplicates), audits metadata compliance. Runs continuously, no manual work needed.',
    'net-val-earn': 'How much can you earn?',
    'net-val-earn-1': '4.0 OAS per block produced (halves ~every 2 years — earlier is more valuable)',
    'net-val-earn-2': '20% of all transaction fees go to validators',
    'net-val-earn-3': 'More stake → higher weight → more blocks → more earnings',
    'net-val-need': 'What do you need?',
    'net-val-need-1': 'Stake at least 10,000 OAS (locked while staking)',
    'net-val-need-2': 'An AI API Key (for data quality verification)',
    'net-val-need-3': 'Keep your node online — offline: 5% slash, malicious: 100% slash, unstaking: 28-day cooldown',
    'net-arb-what': 'What does your node do?',
    'net-arb-what-body': 'When a dispute is filed (copyright, fraud, etc.), your AI automatically: analyzes both sides\' evidence, compares data fingerprints, evaluates ownership claims, and generates a ruling recommendation (delist, transfer, correct rights, etc.).',
    'net-arb-earn': 'How much can you earn?',
    'net-arb-earn-1': 'Arbitration fee per ruling (paid by disputing party, typically 50-500 OAS)',
    'net-arb-earn-2': 'More accurate rulings → higher reputation → more cases → more earnings',
    'net-arb-need': 'What do you need?',
    'net-arb-need-1': 'An AI API Key (for evidence analysis and reasoning)',
    'net-arb-need-2': 'No staking required, but keep your node online to receive cases',
    'net-arb-tags-hint': 'Expertise areas (comma-separated), e.g. copyright,medical,finance',
    'net-work': 'Work Earnings', 'net-work-desc': 'Protocol-assigned tasks and your earnings summary',
    'net-work-total': 'Total tasks', 'net-work-settled': 'Settled',
    'net-work-earned': 'Total earned', 'net-work-quality': 'Avg quality',
    'net-work-failed': 'Failed', 'net-work-no-tasks': 'No task history yet', 'net-work-no-tasks-hint': 'Configure AI compute and the protocol will assign tasks automatically',
    'net-work-recent': 'Recent tasks',
    'net-work-type-validation': 'Validation', 'net-work-type-arbitration': 'Arbitration',
    'net-work-type-verification': 'Verification', 'net-work-type-moderation': 'Moderation',
    'net-consensus': 'Consensus', 'net-consensus-desc': 'Epoch progress and active validators',
    'net-consensus-epoch': 'Current Epoch', 'net-consensus-slot': 'Current Slot',
    'net-consensus-validators': 'Active Validators', 'net-consensus-staked': 'Total Staked',
    'net-consensus-next-epoch': 'Next Epoch', 'net-consensus-delegate': 'Delegate',
    'net-consensus-delegate-desc': 'Stake OAS to a validator',
    'net-consensus-undelegate': 'Undelegate', 'net-consensus-undelegate-desc': 'Withdraw staked OAS',
    'net-consensus-amount': 'Amount (OAS)', 'net-consensus-validator-id': 'Validator ID',
    'net-consensus-submit': 'Submit', 'net-consensus-submitting': 'Submitting...',
    'net-cosmos': 'Cosmos Chain', 'net-cosmos-connected': 'Connected — Block #{height}', 'net-cosmos-checking': 'Checking chain...',
    'net-cosmos-connecting': 'Connecting to Cosmos chain REST API...',
    'net-cosmos-unreachable': 'Cannot reach Cosmos chain at localhost:1317 — showing local data instead',
    'net-cosmos-error': 'Error',
    'net-cosmos-retry': 'Retry', 'net-cosmos-refresh': 'Refresh',
    'net-cosmos-chain-id': 'Chain ID', 'net-cosmos-node-id': 'Node ID', 'net-cosmos-moniker': 'Moniker',
    'net-cosmos-sdk': 'Cosmos SDK', 'net-cosmos-app-ver': 'App Version',
    'net-cosmos-block-height': 'Block Height', 'net-cosmos-block-time': 'Block Time', 'net-cosmos-block-hash': 'Block Hash',
    'net-cosmos-validators': 'Cosmos Validators', 'net-cosmos-val-loading': 'Loading validators...',
    'net-cosmos-no-validators': 'No bonded validators found.',
    'net-cosmos-jailed': 'jailed',
    'net-watermark': 'Watermark Tools', 'net-watermark-desc': 'Track data distribution across the network',
    'net-embed': 'Embed watermark', 'net-embed-desc': 'Sign your identity into a file',
    'net-extract': 'Extract watermark', 'net-extract-desc': 'Read signature info from a file',
    'net-trace': 'Trace distribution', 'net-trace-desc': 'View file distribution history',
    'created-at': 'Created',
    'wm-file-path': 'File path',
    'wm-caller-id': 'Caller ID',
    'wm-embed-btn': 'Embed watermark',
    'wm-embedding': 'Embedding...',
    'wm-extract-btn': 'Extract watermark',
    'wm-extracting': 'Extracting...',
    'wm-asset-id': 'Asset ID',
    'wm-list-btn': 'List distributions',
    'wm-listing': 'Loading...',
    'wm-fingerprint': 'Fingerprint',
    'wm-caller': 'Caller',
    'wm-timestamp': 'Time',
    'wm-watermarked-path': 'Watermarked file',
    'wm-no-records': 'No distribution records', 'wm-no-records-hint': 'Embed a watermark first, then distribution records will appear here',
    'val-staked': 'Staked',
    'val-reputation': 'Reputation',
    'automation': 'Automation', 'automation-desc': 'Manage auto-registration and trading rules, review pending tasks',
    'auto-queue': 'Queue', 'auto-rules': 'Rules', 'coming-soon': 'Coming Soon',
    'pending-tasks': 'Pending', 'completed-tasks': 'Completed',
    'approve-all': 'Approve all', 'all-approved': 'All approved',
    'reject-all': 'Reject all', 'all-rejected': 'All rejected',
    'queue-empty': 'No pending tasks', 'queue-empty-hint': 'Scan a directory, or wait for agents to submit tasks',
    'trust-level-desc': 'Control how much autonomy agents have for registration and trading',
    'trust-0-desc': 'All actions require manual approval',
    'trust-1-desc': 'High-confidence actions auto-execute, rest need approval',
    'trust-2-desc': 'All actions auto-execute, only anomalies flagged',
    'auto-threshold-desc': 'Tasks above the threshold are auto-approved',
    'threshold-strict': 'Strict', 'threshold-strict-desc': 'Only very high confidence auto-approved, most need review',
    'threshold-balanced': 'Balanced', 'threshold-balanced-desc': 'Most trusted tasks auto-approved, suspicious ones flagged',
    'threshold-permissive': 'Permissive', 'threshold-permissive-desc': 'Most tasks auto-approved, only low confidence flagged',
    'scan-directory': 'Scan Directory', 'scan-directory-desc': 'Scan local folders to discover registerable data assets',
    'agent-executor': 'Agent Executor', 'agent-executor-desc': 'Choose which agent handles registration and trading tasks',
    'custom-agent-config': 'Configure Custom Agent',
    'custom-agent-name': 'Agent name',
    'custom-agent-endpoint': 'API endpoint (e.g. https://api.example.com/v1)',
    'custom-agent-test': 'Test connection',
    'agent-setup-hint': 'Install and configure this agent locally before using it for automation.',
    'scan-path-hint': 'Enter directory path, e.g. ~/Documents',
    'scan-btn': 'Scan', 'scanning': 'Scanning...',
    'scan-done': 'Scan complete', 'scan-found': 'Files scanned', 'scan-added': 'Added to inbox',
    'trust-settings': 'Trust Settings', 'trust-level': 'Trust Level',
    'trust-0': 'Manual', 'trust-1': 'Semi-auto', 'trust-2': 'Full-auto',
    'auto-threshold': 'Auto-approve threshold',
    'inbox-no-match': 'No matching items',
    'status-pending': 'Pending', 'status-approved': 'Approved', 'status-rejected': 'Rejected',
    'approve': 'Approve', 'reject': 'Reject', 'edit': 'Edit', 'save': 'Save',
    'approved': 'Approved', 'rejected': 'Rejected', 'saved': 'Saved',
    'edit-name': 'Asset name', 'edit-tags': 'Tags (comma separated)', 'edit-desc': 'Description',
    'rights-type': 'Rights type',
    'rights-original': 'Original', 'rights-co_creation': 'Co-creation', 'rights-licensed': 'Licensed resale', 'rights-collection': 'Personal collection',
    'co-creators': 'Co-creators', 'co-creator-address': 'Address',
    'add-co-creator': 'Add co-creator', 'remove-co-creator': 'Remove',
    'co-creators-hint': 'Co-creation requires at least 2 people, shares must total 100%',
    'disputed': 'Disputed', 'dispute': 'Dispute', 'dispute-reason': 'Dispute reason',
    'dispute-confirm': 'Submit', 'dispute-submitting': 'Submitting...', 'dispute-success': 'Dispute submitted',
    'dispute-reason-hint': 'Describe the reason for dispute',
    'arbitrators': 'Arbitrators', 'arbitrator-score': 'Match',
    'no-arbitrators': 'No arbitrators available', 'arbitrator-auto': 'System auto-matches arbitrators',
    'dispute-status': 'Dispute status', 'dispute-pending': 'Pending arbitration',
    'drop-folder-hint': 'Supports folder drag-and-drop',
    'price-model': 'Pricing Model',
    'price-model-auto': 'Market Pricing', 'price-model-fixed': 'Fixed Price', 'price-model-floor': 'Floor Price',
    'price-model-auto-desc': 'More buyers means higher price — supply and demand',
    'price-model-fixed-desc': 'You set the price, buyers pay this amount',
    'price-model-floor-desc': 'Market pricing, but never below your floor',
    'price-input-hint': 'Enter your desired price', 'price-floor-hint': 'Enter minimum price',
    'register-data': 'Register data', 'publish-cap': 'List capability',
    'cap-name': 'Name', 'cap-name-hint': 'e.g. Image style transfer',
    'cap-desc-hint': 'Input image, output restyled image',
    'cap-desc-guide': 'Describe inputs and outputs so others know how to use it',
    'cap-guide': 'List your AI capability for others to discover and invoke',
    'cap-published': 'Capability listed',
    'cap-endpoint': 'Endpoint URL', 'cap-endpoint-hint': 'e.g. https://api.example.com/translate',
    'cap-api-key': 'API Key', 'cap-api-key-hint': 'Encrypted at rest, never exposed to consumers',
    'cap-price': 'Price per call (OAS)', 'cap-tags': 'Tags', 'cap-tags-hint': 'Comma-separated, e.g. nlp,translation',
    'cap-rate-limit': 'Rate limit', 'cap-rate-limit-hint': 'Max calls per minute',
    'cap-advanced': 'Advanced',
    'my-caps': 'My Capabilities', 'my-data-tab': 'Data Assets',
    'cap-total-calls': 'Total calls', 'cap-success-rate': 'Success rate', 'cap-avg-latency': 'Avg latency',
    'cap-earnings': 'Earnings', 'cap-total-earned': 'Total earned',
    'cap-endpoint-url': 'Endpoint', 'cap-no-caps': 'No capabilities listed yet',
    'cap-no-caps-hint': 'List your first AI capability from the Home page', 'cap-register-cta': 'Go to Home',
    'cap-invoke-input': 'Input (JSON)', 'cap-invoke-input-hint': 'e.g. {"text": "hello"}',
    'dispute-resolved': 'Resolved', 'dispute-dismissed': 'Dismissed',
    'remedy-delist': 'Delist', 'remedy-transfer': 'Transfer ownership', 'remedy-rights_correction': 'Correct rights type', 'remedy-share_adjustment': 'Adjust shares',
    'delisted': 'Delisted',
    'net-retry': 'Retry',
    'files': 'files',
    'explore-browse': 'Browse and trade data & AI capabilities',
    'explore-quickstart': 'Quick Start',
    'explore-quickstart-hint': 'Run these commands in your terminal to get started',
    'explore-qs-demo': 'Run the protocol demo',
    'explore-qs-register': 'Register your first asset',
    'explore-qs-capability': 'Register an AI capability',
    'portfolio-hint': 'Trade on the Market tab to see your holdings here', 'portfolio-browse-cta': 'Browse Market',
    'stake-hint': 'Stake OAS to validator nodes to participate in governance and earn rewards',
    'co-creators-sum': 'Total shares',
    'removed': 'Removed',
    'hash-changed': 'Changed',
    're-register': 'Re-register',
    'file-missing': 'File missing',
    'error-generic': 'That didn\'t work — please try again',
    'error-unauthorized': 'Authentication failed — is your node running?',
    'error-rate-limit': 'Too many requests — wait a few seconds and retry',
    'error-not-found': 'This content no longer exists or was removed',
    'error-server': 'Server error — please try again in a moment',
    'error-timeout': 'Request timed out — check your connection and retry',
    'error-network': 'Can\'t reach the node — make sure oas start is running',
    'invoke-result': 'Result',
    'net-cat-config': 'Configuration', 'net-cat-chain': 'Network & Consensus', 'net-cat-tools': 'Tools', 'net-cat-community': 'Community',
    'net-consensus-loading': 'Loading consensus data...',
    // About panel
    'about-version': 'v2.3.1',
    'about-desc': 'AI-first network for data rights and capability contracts. Bootstrap once, then let agents scan, register, quote, and settle.',
    'about-tab-overview': 'Overview',
    'about-tab-start': 'Quick Start',
    'about-tab-arch': 'Architecture',
    'about-tab-econ': 'Economics',
    'about-tab-update': 'Maintain',
    'about-tab-links': 'Links',
    'about-how': 'Oasyce lets agents register data assets, discover capabilities, and settle through escrow while DataVault acts as the local safety filter. Files are scanned, risk-scored, and only then flow into quote, buy, delivery, and feedback loops.',
    'about-quickstart': '1. pip install oasyce\n2. oas bootstrap         # self-update + wallet + DataVault readiness\n3. oas demo              # run register -> quote -> buy once\n4. oas start             # launch node + dashboard\n5. Optional: oas doctor  # diagnostics',
    'about-arch': 'Core Layers:\n\u2022 Schema Registry \u2014 unified validation for data/capability/oracle/identity\n\u2022 Engine Pipeline \u2014 Scan \u2192 Classify \u2192 Metadata \u2192 PoPc Certificate \u2192 Register\n\u2022 Discovery \u2014 Recall (broad retrieval) \u2192 Rank (trust + economics) + feedback loop\n\u2022 Settlement \u2014 bonding curve pricing, escrow, share distribution\n\u2022 Access Control \u2014 L0 metadata / L1 sample / L2 compute / L3 full\n\u2022 P2P Network \u2014 Ed25519 identity, gossip sync, PoS consensus\n\u2022 Risk Engine \u2014 auto-classification (public / internal / sensitive)',
    'about-econ': 'Token: OAS\n\nPricing: Bonding curve (reserve ratio 0.35) \u2014 more buyers = higher price\nShares: Early buyers earn more (diminishing: 100% \u2192 80% \u2192 60% \u2192 40%)\nRights multiplier: original 1.0x / co_creation 0.9x / licensed 0.7x / collection 0.3x\nStaking: Validators stake OAS to produce blocks and earn rewards\nBlock reward: 4.0 OAS (mainnet), halving every ~1M blocks\nEscrow: Funds locked before execution, released after quality verification',
    'about-update': 'Update:\n  oas update\n  # or: python -m pip install --upgrade --upgrade-strategy eager oasyce odv\n\nFirst-run prep:\n  oas bootstrap\n\nBuild from source:\n  git clone https://github.com/Shangri-la-0428/oasyce-net\n  cd oasyce-net && pip install -e .\n\nRun tests:\n  python -m pytest tests/ -v\n\nContribute: Fork \u2192 Branch \u2192 PR (see CONTRIBUTING.md)',
    'about-link-intro': 'Introduction',
    'about-link-intro-d': 'What is Oasyce and why it matters',
    'about-link-whitepaper': 'Whitepaper',
    'about-link-whitepaper-d': 'Full protocol design and economics paper',
    'about-link-docs': 'Protocol Overview',
    'about-link-docs-d': 'Technical reference, API, and architecture',
    'about-link-github-project': 'GitHub (Project)',
    'about-link-github-project-d': 'Specs, docs, and roadmap',
    'about-link-github-engine': 'GitHub (Engine)',
    'about-link-github-engine-d': 'Protocol implementation, CLI, dashboard, and tests',
    'about-link-discord': 'Discord Community',
    'about-link-discord-d': 'Chat, support, and governance',
    'about-link-contact': 'Contact',
    // Agent Scheduler
    'agent-schedule': 'Scheduled Tasks', 'agent-schedule-desc': 'Let the plugin run autonomously — scan, register, and trade on schedule',
    'agent-enabled': 'Enable Scheduler', 'agent-disabled': 'Disabled',
    'agent-running': 'Running', 'agent-interval': 'Interval', 'agent-interval-hours': 'hours',
    'agent-scan-paths': 'Scan Directories', 'agent-scan-paths-hint': 'One directory path per line',
    'agent-auto-register': 'Auto Register', 'agent-auto-trade': 'Auto Trade',
    'agent-auto-trade-desc': 'Auto-buy capabilities matching tags',
    'agent-trade-tags': 'Trade Tags', 'agent-trade-tags-hint': 'Comma-separated, e.g. nlp,translation',
    'agent-trade-max': 'Max Spend Per Cycle',
    'agent-last-run': 'Last Run', 'agent-next-run': 'Next Run',
    'agent-total-runs': 'Total Runs', 'agent-total-registered': 'Total Registered', 'agent-total-errors': 'Total Errors',
    'agent-run-now': 'Run Now', 'agent-history': 'Run History',
    'agent-save-config': 'Save Config', 'agent-no-history': 'No runs yet', 'agent-no-history-hint': 'Enable the scheduler and run once to see history here',
    'balance-label': 'Balance',
    'earnings': 'Earnings',
    'theme-system': 'Follow system theme',
    'lang-system': 'Follow system language',
    'recent-trades': 'Recent trades',
    'wallet-needed': 'Prepare or join an account before registering or trading',
    'wallet': 'Local wallet',
    'account': 'Account',
    'mode': 'Mode',
    'create-wallet': 'Create account',
    'skip-to-content': 'Skip to content',
    'wallet-created': 'Account created',
    'onboard-step1': 'Prepare device',
    'onboard-step1-hint': 'Decide whether this device should create a new account or join an existing one.',
    'onboard-step2': 'Claim starter bonus',
    'onboard-step2-hint': 'Complete a quick task to get free credits',
    'onboard-step2-btn': 'Claim credits',
    'onboard-step2-mining': 'Computing...',
    'register-success': 'Received {amount} OAS',
    'onboard-step3': 'Upload your first file',
    'onboard-step3-hint': 'Just drop a file — advanced options come later',
    'onboard-welcome': 'Get started',
    'onboard-welcome-hint': 'Prepare this device first, then continue into market and registration flows.',
    'gate-create-body': 'Connect this device to the right economic account first. For a new setup, create a local account here. If you already have a primary device, import the connection file it exported.',
    'gate-funds-body': 'Solve a quick computation task to earn your first credits.',
    'account-entry-title': 'Connect this device',
    'account-entry-question': 'Should this device create a new account?',
    'account-entry-hint': 'Create a new account on this device, or join an account that already exists on another device.',
    'account-entry-create': 'Create new account',
    'account-entry-create-hint': 'Use this device as a primary, signing device for a new account.',
    'account-entry-existing': 'Use existing account',
    'account-entry-existing-hint': 'Import a connection file from your primary device, or join manually if you know the details.',
    'account-entry-back': 'Back',
    'account-entry-cancel': 'Cancel for now',
    'account-entry-advanced': 'Join manually',
    'prepare-device': 'Create on this device',
    'prepare-device-hint': 'Create a write-capable public beta identity on this device and connect the default environment.',
    'join-existing': 'Join existing account',
    'join-existing-bundle': 'Import connection file',
    'join-existing-advanced': 'Advanced manual join',
    'join-existing-readonly': 'Join read-only',
    'join-existing-signing': 'Join with signer',
    'join-bundle-file': 'Connection file',
    'join-bundle-file-hint': 'Choose the oasyce-device.json exported from the primary device',
    'join-bundle-hint': 'Recommended. Import the connection file exported by your primary device and this device will attach to the same account automatically.',
    'join-bundle-warning': 'Connection files may include signing credentials. Transfer them only over channels you trust, then delete the file after import.',
    'join-bundle-invalid': 'This connection file is not valid JSON',
    'join-bundle-submit': 'Import connection file',
    'join-bundle-selected': 'Selected',
    'join-advanced-hint': 'Use advanced manual join only when you already know the account address or this machine already has the same signer.',
    'join-account-address': 'Account address',
    'join-account-address-hint': 'Enter an existing account address, e.g. oasyce1...',
    'join-signer-name': 'Signer name',
    'join-signer-name-hint': 'Enter a signer name that already exists on this device',
    'join-readonly-hint': 'Best for browsing, holdings, quoting, and AI collaboration. No direct on-chain writes.',
    'join-signing-hint': 'Use this only if the same signer already exists on this device.',
    'device-prepare-success': 'This device account is ready',
    'device-join-success': 'Device joined to this account',
    'device-export-title': 'Connect another device',
    'device-export-hint': 'Primary devices can export a connection file. Import it on another device to attach that device to the same account.',
    'device-export-signing': 'Export signing connection file',
    'device-export-readonly': 'Export read-only connection file',
    'device-export-success': 'Connection file exported',
    'device-export-readonly-success': 'Read-only connection file exported',
    'device-export-signer-warning': 'Signing connection files include signer credentials. Transfer them only over channels you trust, then delete the file after import.',
    'device-manage-title': 'Manage this device',
    'device-manage-hint': 'You can switch this device to another account, or revoke its current access.',
    'device-switch-account': 'Use another account',
    'device-revoke': 'Disconnect this device',
    'device-revoke-body': 'If the wrong account was connected, disconnect this device first and then join the correct one.',
    'device-revoke-confirm': 'Confirm disconnect',
    'device-revoke-success': 'This device has been disconnected from the current account',
    'readonly-device-title': 'Existing account connected',
    'readonly-device-body': 'This device is attached to the same economic account, but currently in read-only mode.',
    'readonly-device-upgrade': 'To register, buy, sell, or stake manually on this device, re-import a signing connection file exported from the primary device.',
    'readonly-device-cta-market': 'Browse market',
    'readonly-device-cta-network': 'Open network',
    'account-mode-readonly': 'Read-only',
    'account-mode-signing': 'Signing',
    'success-outcome': 'Live',
    'success-outcome-body': 'Your file is now discoverable and purchasable. Earnings arrive in your account automatically.',
    'success-cta-market': 'Visit market',
    'success-cta-more': 'Upload another',
    'advanced-options-hint': 'Advanced options can be changed on the "My Data" page',
    'vet-register-cta': 'Upload more',
    'total-earned': 'Total Earned',
    'recent-transactions': 'Recent Transactions',
    'no-transactions': 'No transactions yet', 'no-transactions-hint': 'Buy or sell assets to see transaction history here',
    // Data Preview
    'preview': 'Preview',
    'preview-loading': 'Loading preview...',
    'preview-metadata': 'Metadata',
    'preview-content': 'Content Preview',
    'preview-locked': 'Purchase to view more',
    'preview-truncated': 'Content truncated',
    // Buyer Dispute/Refund
    'dispute-file': 'File Dispute',
    'dispute-reason-select': 'Select reason',
    'dispute-evidence': 'Evidence',
    'dispute-evidence-hint': 'Describe the issue in detail...',
    'dispute-created': 'Created', 'dispute-resolved-at': 'Resolved At', 'dispute-resolution': 'Resolution',
    'dispute-reason-quality': 'Data quality issue',
    'dispute-reason-mismatch': 'Content mismatch',
    'dispute-reason-copyright': 'Copyright issue',
    'dispute-reason-fraud': 'Fraudulent content',
    'dispute-reason-other': 'Other',
    'dispute-filed': 'Dispute filed',
    'my-disputes': 'My Disputes',
    'dispute-no-disputes': 'No disputes yet', 'dispute-no-disputes-hint': 'If you have concerns about a purchased asset, file a dispute here',
    'dispute-open': 'Open',
    'report-issue': 'Report Issue',
    // Notifications
    'notifications': 'Notifications',
    'notifications-empty': 'No notifications',
    'notifications-mark-read': 'Mark all read',
    // Sell shares
    'sell': 'Sell', 'selling': 'Selling...',
    'sell-amount-hint': 'Enter number of shares',
    'sell-slippage': 'Max slippage', 'sell-success': 'Sale complete',
    // Transaction history
    'tx-history': 'Transaction History', 'tx-no-history': 'No transactions yet', 'tx-no-history-hint': 'Transaction history will appear here after your first trade',
    // Jury voting
    'jury-vote': 'Jury Vote', 'jury-voting': 'Voting...',
    'jury-verdict': 'Verdict', 'jury-uphold': 'Side with consumer', 'jury-reject': 'Side with provider',
    'jury-vote-success': 'Vote submitted',
    // Dispute resolution
    'resolve-dispute': 'Resolve Dispute', 'resolving': 'Resolving...',
    'resolve-remedy': 'Remedy', 'resolve-details': 'Details',
    'resolve-success': 'Dispute resolved',
    // Evidence submission
    'submit-evidence': 'Submit Evidence', 'submitting-evidence': 'Submitting...',
    'evidence-hash': 'Evidence hash', 'evidence-type': 'Evidence type',
    'evidence-desc': 'Description', 'evidence-success': 'Evidence submitted',
    'evidence-type-document': 'Document', 'evidence-type-screenshot': 'Screenshot',
    'evidence-type-log': 'Log', 'evidence-type-other': 'Other',
    // Metadata update
    'metadata-tags': 'Edit Tags',
    'metadata-updated': 'Metadata updated',
    // Manual re-register
    're-register-manual': 'Update Version',
    // Asset lifecycle
    'asset-lifecycle': 'Asset Lifecycle',
    'asset-lifecycle-hint': 'Delist → 7-day cooldown → Terminate → Claim payout',
    'asset-shutdown': 'Delist from market',
    'asset-shutdown-confirm': 'Delist this asset? Enters a 7-day cooldown to protect existing holders. Cannot be undone.',
    'asset-shutdown-success': 'Delisting initiated — terminable after 7 days',
    'asset-terminate': 'Terminate', 'asset-terminate-success': 'Asset terminated',
    'asset-claim': 'Claim Payout', 'asset-claim-success': 'Payout claimed',
    'asset-status-label': 'Status',
    'asset-status-active': 'Active', 'asset-status-shutdown': 'Cooling down', 'asset-status-terminated': 'Terminated',
    // Version history
    'version-history': 'Version History', 'no-versions': 'No version history',
    'version-number': 'Version', 'version-time': 'Time',
    // Governance
    'governance': 'Governance', 'governance-desc': 'Create proposals and participate in voting',
    'gov-proposals': 'Proposals', 'gov-no-proposals': 'No proposals yet', 'gov-no-proposals-hint': 'Submit your first proposal to participate in protocol governance',
    'gov-propose': 'Submit Proposal', 'gov-proposing': 'Submitting...',
    'gov-title': 'Title', 'gov-description': 'Description', 'gov-deposit': 'Deposit (OAS)',
    'gov-propose-success': 'Proposal submitted',
    'gov-vote-yes': 'Yes', 'gov-vote-no': 'No', 'gov-vote-abstain': 'Abstain',
    'gov-vote-success': 'Vote submitted',
    'gov-status': 'Status', 'gov-chain-only': 'Governance has moved to L1 chain',
    // Wallet export/import
    'wallet-export': 'Export Wallet', 'wallet-import': 'Import Wallet',
    'wallet-import-desc': 'Restore wallet from backup',
    'wallet-exported': 'Wallet exported', 'wallet-imported': 'Wallet imported',
    'wallet-import-hint': 'Paste exported wallet JSON',
    // Fingerprint list
    'fingerprint-list': 'Fingerprint Records', 'fingerprint-no-records': 'No fingerprint records', 'fingerprint-no-records-hint': 'Enter an asset ID to look up its fingerprint history',
    'fingerprint-asset': 'Asset ID',
    // Reputation
    'node-reputation': 'Reputation',
    // L0-L3 access operations
    'access-query': 'L0 Query', 'access-sample': 'L1 Sample',
    'access-compute': 'L2 Compute', 'access-deliver': 'L3 Deliver',
    'access-op-running': 'Running...',
    'access-result': 'Result',
    // Task bounty (AHRP)
    'bounty': 'Bounty Tasks',
    'bounty-post': 'Post Task', 'bounty-posting': 'Posting...',
    'bounty-list': 'Open Tasks', 'bounty-no-tasks': 'No open tasks', 'bounty-no-tasks-hint': 'Post a bounty task or wait for others to post',
    'bounty-description': 'Task Description', 'bounty-budget': 'Budget (OAS)',
    'bounty-deadline': 'Deadline (hours)', 'bounty-capabilities': 'Required Capabilities',
    'bounty-capabilities-hint': 'Comma-separated, e.g. nlp,translation',
    'bounty-strategy': 'Selection Strategy', 'bounty-min-rep': 'Min Reputation',
    'bounty-strategy-weighted': 'Weighted Score', 'bounty-strategy-price': 'Lowest Price',
    'bounty-strategy-reputation': 'Best Reputation', 'bounty-strategy-requester': 'Manual',
    'bounty-bid': 'Submit Bid', 'bounty-bidding': 'Bidding...',
    'bounty-bid-price': 'Bid Price', 'bounty-bid-seconds': 'Estimated Time (s)',
    'bounty-bid-rep': 'Reputation', 'bounty-bid-success': 'Bid submitted',
    'bounty-select': 'Select Winner', 'bounty-selecting': 'Selecting...',
    'bounty-complete': 'Mark Complete', 'bounty-completing': 'Completing...',
    'bounty-cancel': 'Cancel Task', 'bounty-cancelling': 'Cancelling...',
    'bounty-bids': 'Bids', 'bounty-bids-count': 'Bids',
    'bounty-requester': 'Requester', 'bounty-assigned': 'Assigned',
    'bounty-post-success': 'Task posted', 'bounty-select-success': 'Winner selected',
    'bounty-complete-success': 'Task completed', 'bounty-cancel-success': 'Task cancelled',
    // Contribution proof
    'contribution': 'Contribution Proof', 'contribution-desc': 'Prove data authorship and verify contribution certificates',
    'contribution-prove': 'Generate Proof', 'contribution-proving': 'Generating...',
    'contribution-verify': 'Verify Proof', 'contribution-verifying': 'Verifying...',
    'contribution-file': 'File Path', 'contribution-creator': 'Creator Key',
    'contribution-source': 'Source Type', 'contribution-result': 'Proof Result',
    'contribution-valid': 'Valid', 'contribution-invalid': 'Invalid',
    'contribution-prove-success': 'Contribution proof generated', 'error-invalid-json': 'Invalid JSON format',
    'contribution-certificate': 'Certificate JSON', 'contribution-content-hash': 'Content Hash',
    'contribution-semantic': 'Semantic Fingerprint', 'contribution-timestamp': 'Timestamp',
    // Leakage budget
    'leakage': 'Leakage Budget', 'leakage-desc': 'Remaining access allowance for agents on your data assets', 'yes': 'Yes', 'no': 'No',
    'leakage-check': 'Check Budget', 'leakage-checking': 'Checking...',
    'leakage-reset': 'Reset Budget', 'leakage-resetting': 'Resetting...',
    'leakage-agent': 'Agent ID', 'leakage-asset': 'Asset ID',
    'leakage-remaining': 'Remaining', 'leakage-used': 'Used',
    'leakage-budget-total': 'Total Budget', 'leakage-queries': 'Queries',
    'leakage-exhausted': 'Budget exhausted', 'leakage-reset-success': 'Budget reset',
    // Cache management
    'cache': 'Cache', 'cache-stats': 'Cache Stats',
    'cache-total': 'Total', 'cache-active': 'Active', 'cache-expired': 'Expired',
    'cache-purge': 'Purge Expired', 'cache-purging': 'Purging...',
    'cache-purge-success': 'Expired entries purged', 'cache-db-path': 'DB Path',
    'error-boundary-title': 'This section failed to load', 'error-boundary-retry': 'Try again',
    'preview-size': 'Size',
    // Feedback
    'feedback': 'Feedback', 'feedback-desc': 'AI agents can submit bug reports and suggestions here',
    'feedback-submit': 'Submit', 'feedback-submitting': 'Submitting...',
    'feedback-message': 'Message', 'feedback-message-hint': 'Describe the issue or suggestion...',
    'feedback-type': 'Type', 'feedback-type-bug': 'Bug', 'feedback-type-suggestion': 'Suggestion', 'feedback-type-other': 'Other',
    'feedback-agent': 'Agent ID', 'feedback-agent-hint': 'Identifier of the reporting agent',
    'feedback-context': 'Context', 'feedback-context-hint': 'Related context (JSON)',
    'feedback-success': 'Feedback submitted', 'feedback-list': 'Feedback log',
    'feedback-no-items': 'No feedback yet', 'feedback-no-items-hint': 'No reports from AI agents yet',
    'feedback-status': 'Status',
    'file-too-large': 'File too large (max 100 MB)',
    'partial-failure': 'Some items failed',
    // Invocation lifecycle
    'invocation_completed': 'Completed (Challenge Window)',
    'invocation_disputed': 'Disputed',
    'challenge_window': 'Challenge Window',
    'claim_payment': 'Claim Payment',
  },
};

/**
 * i18n computed — 返回一个 Proxy 包裹的 dict
 * 组件里用 i18n.value['key'] 来读取，确保 signal tracking
 * 如果 key 不存在，返回 fallback 链：当前语言 → en → key 本身
 * 这样即使翻译缺失也不会渲染 undefined
 */
export const i18n = computed(() => {
  const current = dict[resolvedLang.value] || dict['en'];
  const fallback = dict['en'];
  return new Proxy(current, {
    get(target, prop: string) {
      return target[prop] ?? fallback[prop] ?? prop;
    },
  });
});
