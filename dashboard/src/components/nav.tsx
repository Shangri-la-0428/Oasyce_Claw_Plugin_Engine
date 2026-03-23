/**
 * Nav — single-line instrument bar
 */
import { useState } from 'preact/hooks';
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

  return (
    <>
      <nav class="nav">
        <button class="nav-brand" onClick={() => go('home')}>OASYCE</button>
        <div class="nav-tabs" role="tablist">
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
