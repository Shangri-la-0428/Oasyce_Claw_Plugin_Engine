/**
 * Nav — with about panel trigger
 */
import { useState } from 'preact/hooks';
import { theme, lang, toggleTheme, toggleLang, i18n, balance, unreadCount, notifications, loadNotifications, markNotificationsRead } from '../store/ui';
import type { Notification } from '../store/ui';
import type { Page } from '../hooks/use-route';
import AboutPanel from './about-panel';
import './nav.css';

const tabs: Page[] = ['home', 'mydata', 'explore', 'auto', 'network'];

interface Props { current: Page; go: (p: Page, sub?: string) => void; }

function NotificationPanel({ onClose: _onClose }: { onClose: () => void }) {
  const _ = i18n.value;
  const items = notifications.value;
  const formatTime = (ts: number) => {
    const d = new Date(ts * 1000);
    return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };
  return (
    <div class="notif-panel">
      <div class="notif-header">
        <span class="notif-title">{_['notifications']}</span>
        {items.some(n => !n.read) && (
          <button class="btn btn-sm btn-ghost" onClick={() => markNotificationsRead()}>
            {_['notifications-mark-read']}
          </button>
        )}
      </div>
      <div class="notif-list">
        {items.length === 0 ? (
          <div class="notif-empty">{_['notifications-empty']}</div>
        ) : items.map((n: Notification) => (
          <div
            key={n.id}
            class={`notif-item ${n.read ? '' : 'notif-unread'}`}
            onClick={() => { if (!n.read) markNotificationsRead(n.id); }}
          >
            <div class="notif-msg">{n.message}</div>
            <div class="notif-time">{formatTime(n.created_at)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function Nav({ current, go }: Props) {
  const _ = i18n.value; /* signal tracking */
  const [showAbout, setShowAbout] = useState(false);
  const [showNotif, setShowNotif] = useState(false);
  const count = unreadCount.value;

  return (
    <>
      <nav class="nav">
        <button class="nav-brand" onClick={() => go('home')}>Oasyce</button>
        <div class="nav-tabs">
          {tabs.map(k => (
            <button key={k} class={`nav-tab ${current === k ? 'active' : ''}`} onClick={() => go(k)}>
              {_[k]}
            </button>
          ))}
        </div>
        <div class="nav-end">
          <span class="nav-balance" title={_['balance-label']}>{(balance.value ?? 0).toFixed(1)} OAS</span>
          <button
            class="nav-tool notif-bell"
            onClick={() => { setShowNotif(!showNotif); setShowAbout(false); if (!showNotif) loadNotifications(); }}
            aria-label={_['notifications']}
            title={_['notifications']}
          >
            <span>&#x1F514;</span>
            {count > 0 && <span class="notif-badge">{count > 99 ? '99+' : count}</span>}
          </button>
          <button class="nav-tool" onClick={() => { setShowAbout(!showAbout); setShowNotif(false); }} aria-label="About Oasyce" title="About Oasyce">i</button>
          <button class="nav-tool" onClick={toggleLang} aria-label={lang.value === 'zh' ? 'Switch to English' : '切换到中文'}>{lang.value === 'zh' ? 'En' : '中'}</button>
          <button class="nav-tool" onClick={toggleTheme} aria-label={theme.value === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>{theme.value === 'dark' ? '☀' : '☾'}</button>
        </div>
      </nav>
      {showNotif && <NotificationPanel onClose={() => setShowNotif(false)} />}
      {showAbout && <AboutPanel onClose={() => setShowAbout(false)} />}
    </>
  );
}
