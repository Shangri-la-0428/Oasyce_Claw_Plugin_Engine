/**
 * UI Store
 * i18n 用 computed signal 确保语言切换触发重渲染
 */
import { signal, computed } from '@preact/signals';

export const theme = signal<'dark' | 'light'>('dark');
export const lang = signal<'zh' | 'en'>('zh');
export const toasts = signal<{ id: string; message: string; type: string }[]>([]);

export function initUI() {
  theme.value = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  lang.value = navigator.language?.startsWith('zh') ? 'zh' : 'en';
  document.documentElement.setAttribute('data-theme', theme.value);
}

export function toggleTheme() {
  theme.value = theme.value === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', theme.value);
}

export function toggleLang() {
  lang.value = lang.value === 'zh' ? 'en' : 'zh';
}

export function showToast(message: string, type = 'info') {
  const id = Date.now().toString();
  toasts.value = [...toasts.value, { id, message, type }];
  setTimeout(() => toasts.value = toasts.value.filter(t => t.id !== id), 3000);
}

const dict: Record<string, Record<string, string>> = {
  zh: {
    home: '首页', mydata: '我的数据', explore: '探索', network: '网络',
    'hero-title-light': '数据的权利',
    'hero-title-bold': '由你掌控',
    'hero-sub': '注册、追踪、清算。你的数据在 Oasyce 网络上拥有不可篡改的身份。',
    protect: '注册数据', protecting: '注册中...', protected: '已注册',
    'drop-hint': '拖入文件', 'drop-browse': '选择文件',
    'describe': '描述', 'describe-hint': '例如：医疗影像、研究数据、创意作品',
    'value': '当前价值', 'owner': '所有者', 'id': '编号',
    'search': '搜索你的数据...', 'no-data': '还没有数据', 'first-data': '注册你的第一份数据',
    'delete': '移除', 'delete-confirm': '确定移除这份数据？移除后无法恢复。',
    'get-access': '获取访问权', 'quote': '查看报价', 'quoting': '计算中...',
    'pay': '需要支付', 'receive': '获得份额', 'impact': '价格影响',
    'confirm-buy': '确认获取', 'buying': '处理中...', 'back': '返回',
    'paste-id': '粘贴数据编号', 'amount': '金额',
    'identity': '你的身份', 'identity-hint': '这是你在网络上的唯一标识',
    'no-key': '首次注册数据时自动生成', 'copy': '复制', 'copied': '已复制',
    'advanced': '详细信息',
    'again': '继续注册',
    'nav-mydata': '我的数据', 'nav-mydata-desc': '查看已注册的数据资产',
    'nav-explore': '探索', 'nav-explore-desc': '搜索网络上的数据资产',
    'nav-network': '网络', 'nav-network-desc': '节点状态与网络信息',
    'cancel': '取消', 'confirm-remove': '确认移除',
    'get-desc': '输入数据编号，查看报价并获取访问权',
    'explore-title': '探索数据',
    'explore-desc': '发现网络上的数据资产，获取访问权',
    'explore-search': '搜索数据编号或描述...',
    'explore-empty': '输入编号或关键词开始搜索',
    'categories': '分类',
    'browse-all': '浏览全部',
    'all': '全部',
    'sort-time': '最新', 'sort-value': '价值',
    'load-more': '加载更多', 'no-more': '没有更多了',
    'view-mydata': '查看我的数据',
  },
  en: {
    home: 'Home', mydata: 'My Data', explore: 'Explore', network: 'Network',
    'hero-title-light': 'Data rights,',
    'hero-title-bold': 'settled.',
    'hero-sub': 'Register. Track. Clear. Your data gets an immutable identity on the Oasyce network.',
    protect: 'Register', protecting: 'Registering...', protected: 'Registered',
    'drop-hint': 'Drop file', 'drop-browse': 'choose file',
    'describe': 'Description', 'describe-hint': 'e.g. medical imaging, research data, creative work',
    'value': 'Value', 'owner': 'Owner', 'id': 'ID',
    'search': 'Search your data...', 'no-data': 'No data yet', 'first-data': 'Register your first file',
    'delete': 'Remove', 'delete-confirm': 'Remove this data? This cannot be undone.',
    'get-access': 'Get access', 'quote': 'Get quote', 'quoting': 'Calculating...',
    'pay': 'You pay', 'receive': 'You receive', 'impact': 'Price impact',
    'confirm-buy': 'Confirm', 'buying': 'Processing...', 'back': 'Back',
    'paste-id': 'Paste data ID', 'amount': 'Amount',
    'identity': 'Your identity', 'identity-hint': 'Your unique ID on the network',
    'no-key': 'Auto-generated on first registration', 'copy': 'Copy', 'copied': 'Copied',
    'advanced': 'Details',
    'again': 'Register another',
    'nav-mydata': 'My data', 'nav-mydata-desc': 'View your registered data assets',
    'nav-explore': 'Explore', 'nav-explore-desc': 'Search data assets on the network',
    'nav-network': 'Network', 'nav-network-desc': 'Node status and network info',
    'cancel': 'Cancel', 'confirm-remove': 'Confirm remove',
    'get-desc': 'Enter a data ID to get a quote and gain access',
    'explore-title': 'Explore data',
    'explore-desc': 'Discover data assets on the network and get access',
    'explore-search': 'Search by ID or description...',
    'explore-empty': 'Enter an ID or keyword to start',
    'categories': 'Categories',
    'browse-all': 'Browse all',
    'all': 'All',
    'sort-time': 'Latest', 'sort-value': 'Value',
    'load-more': 'Load more', 'no-more': "That's all",
    'view-mydata': 'View my data',
  },
};

/**
 * i18n computed — 返回一个 computed signal
 * 组件里用 i18n.value['key'] 来读取，确保 signal tracking
 */
export const i18n = computed(() => dict[lang.value] || dict['en']);
