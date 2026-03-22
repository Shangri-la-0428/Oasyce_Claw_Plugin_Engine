/**
 * Nav — dashboard instrument header
 */
import { useState, useEffect, useRef } from 'preact/hooks';
import {
  theme,
  lang,
  toggleTheme,
  toggleLang,
  i18n,
  balance,
  unreadCount,
  notifications,
  loadNotifications,
  markNotificationsRead,
  identity,
} from '../store/ui';
import type { Notification } from '../store/ui';
import type { Page } from '../hooks/use-route';
import AboutPanel from './about-panel';
import './nav.css';

const tabs: Array<{ page: Page; code: string }> = [
  { page: 'home', code: '01' },
  { page: 'mydata', code: '02' },
  { page: 'explore', code: '03' },
  { page: 'auto', code: '04' },
  { page: 'network', code: '05' },
];

interface Props {
  current: Page;
  go: (p: Page, sub?: string) => void;
}

function maskWallet(address: string) {
  if (!address || address.length <= 12) return address;
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

function NotificationPanel({ onClose }: { onClose: () => void }) {
  const _ = i18n.value;
  const items = notifications.value;
  const panelRef = useRef<HTMLDivElement>(null);
  const copy = lang.value === 'zh'
    ? { close: '关闭', unread: '未读' }
    : { close: 'Close', unread: 'Unread' };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    panelRef.current?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose]);

  const formatTime = (ts: number) => {
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const unread = items.filter(item => !item.read).length;

  return (
    <div class="notif-panel" ref={panelRef} tabIndex={-1} role="dialog" aria-label={_['notifications']}>
      <div class="notif-header">
        <div>
          <span class="notif-title">{_['notifications']}</span>
          <span class="notif-summary">
            {unread > 0 ? `${unread} ${copy.unread}` : _['notifications-empty']}
          </span>
        </div>
        <div class="notif-actions">
          {items.some(item => !item.read) && (
            <button class="btn btn-sm btn-ghost" onClick={() => markNotificationsRead()}>
              {_['notifications-mark-read']}
            </button>
          )}
          <button class="nav-tool nav-tool-sm" onClick={onClose} aria-label={copy.close} title={copy.close}>
            ×
          </button>
        </div>
      </div>
      <div class="notif-list">
        {items.length === 0 ? (
          <div class="notif-empty">{_['notifications-empty']}</div>
        ) : items.map((item: Notification) => (
          <button
            key={item.id}
            class={`notif-item ${item.read ? '' : 'notif-unread'}`}
            onClick={() => {
              if (!item.read) markNotificationsRead(item.id);
            }}
          >
            <div class="notif-msg">{item.message}</div>
            <div class="notif-time">{formatTime(item.created_at)}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

export default function Nav({ current, go }: Props) {
  const _ = i18n.value;
  const [showAbout, setShowAbout] = useState(false);
  const [showNotif, setShowNotif] = useState(false);
  const count = unreadCount.value;
  const walletExists = !!identity.value?.exists;
  const walletLabel = walletExists
    ? maskWallet(identity.value?.address || '')
    : (lang.value === 'zh' ? '尚未创建' : 'Not ready');
  const copy = lang.value === 'zh'
    ? {
        brandSub: '权利清算仪表盘',
        about: '关于 Oasyce',
        notif: '通知',
      }
    : {
        brandSub: 'Rights clearing dashboard',
        about: 'About Oasyce',
        notif: 'Notifications',
      };

  return (
    <>
      <nav class="nav">
        <div class="nav-topline">
          <button class="nav-brand" onClick={() => go('home')}>
            <span class="nav-brand-mark" aria-hidden="true" />
            <span class="nav-brand-copy">
              <strong>OASYCE</strong>
              <small>{copy.brandSub}</small>
            </span>
          </button>

          <div class="nav-utility-rail">
            <div class="nav-stat">
              <span class="nav-stat-label">{_['identity']}</span>
              <span class="nav-stat-value mono">{walletLabel}</span>
            </div>
            <div class="nav-stat">
              <span class="nav-stat-label">{_['balance-label']}</span>
              <span class="nav-stat-value mono">{(balance.value ?? 0).toFixed(1)} OAS</span>
            </div>
            <div class="nav-toolset">
              <button
                class="nav-tool notif-bell"
                onClick={() => {
                  setShowNotif(!showNotif);
                  setShowAbout(false);
                  if (!showNotif) loadNotifications();
                }}
                aria-label={copy.notif}
                title={copy.notif}
              >
                <span>◌</span>
                {count > 0 && <span class="notif-badge">{count > 99 ? '99+' : count}</span>}
              </button>
              <button
                class="nav-tool"
                onClick={() => {
                  setShowAbout(!showAbout);
                  setShowNotif(false);
                }}
                aria-label={copy.about}
                title={copy.about}
              >
                i
              </button>
              <button
                class="nav-tool"
                onClick={toggleLang}
                aria-label={lang.value === 'zh' ? 'Switch to English' : '切换到中文'}
              >
                {lang.value === 'zh' ? 'En' : '中'}
              </button>
              <button
                class="nav-tool"
                onClick={toggleTheme}
                aria-label={theme.value === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              >
                {theme.value === 'dark' ? '☀' : '☾'}
              </button>
            </div>
          </div>
        </div>

        <div class="nav-tabs" role="tablist" aria-label="Primary navigation">
          {tabs.map(tab => (
            <button
              key={tab.page}
              role="tab"
              aria-selected={current === tab.page}
              class={`nav-tab ${current === tab.page ? 'active' : ''}`}
              onClick={() => go(tab.page)}
            >
              <span class="nav-tab-index">{tab.code}</span>
              <span class="nav-tab-label">{_[tab.page]}</span>
            </button>
          ))}
        </div>
      </nav>

      {showNotif && <NotificationPanel onClose={() => setShowNotif(false)} />}
      {showAbout && <AboutPanel onClose={() => setShowAbout(false)} />}
    </>
  );
}
