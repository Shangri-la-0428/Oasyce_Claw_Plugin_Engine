/**
 * Nav
 */
import { theme, lang, toggleTheme, toggleLang, i18n } from '../store/ui';
import type { Page } from '../app';
import './nav.css';

const tabs: Page[] = ['home', 'mydata', 'explore', 'auto', 'network'];

interface Props { current: Page; go: (p: Page) => void; }

export default function Nav({ current, go }: Props) {
  const _ = i18n.value; /* signal tracking */
  return (
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
        <button class="nav-tool" onClick={toggleLang}>{lang.value === 'zh' ? 'En' : '中'}</button>
        <button class="nav-tool" onClick={toggleTheme}>{theme.value === 'dark' ? '☀' : '☾'}</button>
      </div>
    </nav>
  );
}
