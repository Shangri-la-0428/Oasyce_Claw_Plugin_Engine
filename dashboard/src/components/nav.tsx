/**
 * Nav — with about panel trigger
 */
import { useState } from 'preact/hooks';
import { theme, lang, toggleTheme, toggleLang, i18n } from '../store/ui';
import type { Page } from '../app';
import AboutPanel from './about-panel';
import './nav.css';

const tabs: Page[] = ['home', 'mydata', 'explore', 'auto', 'network'];

interface Props { current: Page; go: (p: Page) => void; }

export default function Nav({ current, go }: Props) {
  const _ = i18n.value; /* signal tracking */
  const [showAbout, setShowAbout] = useState(false);

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
          <button class="nav-tool" onClick={() => setShowAbout(!showAbout)} aria-label="About Oasyce" title="About Oasyce">i</button>
          <button class="nav-tool" onClick={toggleLang} aria-label={lang.value === 'zh' ? 'Switch to English' : '切换到中文'}>{lang.value === 'zh' ? 'En' : '中'}</button>
          <button class="nav-tool" onClick={toggleTheme} aria-label={theme.value === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>{theme.value === 'dark' ? '☀' : '☾'}</button>
        </div>
      </nav>
      {showAbout && <AboutPanel onClose={() => setShowAbout(false)} />}
    </>
  );
}
