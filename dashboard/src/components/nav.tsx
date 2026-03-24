/**
 * Nav — single-line instrument bar
 * Features: sliding active indicator that morphs between tabs
 */
import { useState, useRef, useEffect, useCallback } from 'preact/hooks';
import { theme, lang, toggleTheme, toggleLang, i18n } from '../store/ui';
import type { Page } from '../hooks/use-route';
import AboutPanel from './about-panel';
import './nav.css';

const tabs: Page[] = ['home', 'mydata', 'explore', 'auto', 'network'];

interface Props {
  current: Page;
  go: (p: Page, sub?: string) => void;
}

export default function Nav({ current, go }: Props) {
  const _ = i18n.value;
  const [showAbout, setShowAbout] = useState(false);
  const tabsRef = useRef<HTMLDivElement>(null);
  const indicatorRef = useRef<HTMLDivElement>(null);

  const updateIndicator = useCallback(() => {
    const container = tabsRef.current;
    const indicator = indicatorRef.current;
    if (!container || !indicator) return;
    const activeTab = container.querySelector('.nav-tab.active') as HTMLElement | null;
    if (!activeTab) { indicator.style.opacity = '0'; return; }
    const containerRect = container.getBoundingClientRect();
    const tabRect = activeTab.getBoundingClientRect();
    indicator.style.opacity = '1';
    indicator.style.left = `${tabRect.left - containerRect.left}px`;
    indicator.style.width = `${tabRect.width}px`;
  }, []);

  useEffect(() => {
    updateIndicator();
  }, [current, updateIndicator]);

  // Recalculate on resize
  useEffect(() => {
    const onResize = () => updateIndicator();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [updateIndicator]);

  return (
    <>
      <nav class="nav">
        <button class="nav-brand" onClick={() => go('home')}>OASYCE</button>
        <div class="nav-tabs" role="tablist" ref={tabsRef}>
          {tabs.map(k => (
            <button
              key={k}
              role="tab"
              aria-selected={current === k}
              class={`nav-tab ${current === k ? 'active' : ''}`}
              onClick={() => go(k)}
            >
              {_[k]}
            </button>
          ))}
          <div class="nav-indicator" ref={indicatorRef} aria-hidden="true" />
        </div>
        <div class="nav-end">
          <button class="nav-tool" onClick={() => setShowAbout(!showAbout)} aria-label="About" title="About">?</button>
          <button class="nav-tool" onClick={toggleLang} aria-label={lang.value === 'zh' ? 'Switch to English' : '切换到中文'}>{lang.value === 'zh' ? 'En' : '中'}</button>
          <button class="nav-tool" onClick={toggleTheme} aria-label={theme.value === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>{theme.value === 'dark' ? '☀' : '☾'}</button>
        </div>
      </nav>
      {showAbout && <AboutPanel onClose={() => setShowAbout(false)} />}
    </>
  );
}
