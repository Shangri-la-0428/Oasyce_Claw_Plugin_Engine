/**
 * AboutPanel — tabbed info panel for all audiences
 * Slides in from the right when the "i" button is clicked.
 */
import { useState, useEffect, useRef } from 'preact/hooks';
import { i18n } from '../store/ui';
import './about-panel.css';

interface Props {
  onClose: () => void;
}

type Tab = 'overview' | 'start' | 'arch' | 'econ' | 'update' | 'links';

export default function AboutPanel({ onClose }: Props) {
  const _ = i18n.value;
  const [tab, setTab] = useState<Tab>('overview');
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
    panelRef.current?.focus();
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = '';
    };
  }, [onClose]);

  const tabs: { key: Tab; label: string }[] = [
    { key: 'overview', label: _['about-tab-overview'] },
    { key: 'start', label: _['about-tab-start'] },
    { key: 'arch', label: _['about-tab-arch'] },
    { key: 'econ', label: _['about-tab-econ'] },
    { key: 'update', label: _['about-tab-update'] },
    { key: 'links', label: _['about-tab-links'] },
  ];

  return (
    <div>
      <div class="about-overlay" onClick={onClose} />
      <div class="about-panel" role="dialog" aria-modal="true" ref={panelRef} tabIndex={-1}>
        <button class="about-close" onClick={onClose}>&times;</button>

        <div class="about-header">
          <h3>Oasyce</h3>
          <span class="about-badge">{_['about-version']}</span>
        </div>
        <p class="about-desc">{_['about-desc']}</p>

        <div class="about-tabs">
          {tabs.map(t => (
            <button
              key={t.key}
              class={`about-tab ${tab === t.key ? 'active' : ''}`}
              onClick={() => setTab(t.key)}
            >{t.label}</button>
          ))}
        </div>

        {/* Overview */}
        <div class={`about-section ${tab === 'overview' ? 'active' : ''}`}>
          <p>{_['about-how']}</p>
        </div>

        {/* Quick Start */}
        <div class={`about-section ${tab === 'start' ? 'active' : ''}`}>
          <pre>{_['about-quickstart']}</pre>
        </div>

        {/* Architecture */}
        <div class={`about-section ${tab === 'arch' ? 'active' : ''}`}>
          <pre>{_['about-arch']}</pre>
        </div>

        {/* Economics */}
        <div class={`about-section ${tab === 'econ' ? 'active' : ''}`}>
          <pre>{_['about-econ']}</pre>
        </div>

        {/* Update */}
        <div class={`about-section ${tab === 'update' ? 'active' : ''}`}>
          <pre>{_['about-update']}</pre>
        </div>

        {/* Links */}
        <div class={`about-section ${tab === 'links' ? 'active' : ''}`}>
          <ul class="about-links">
            <li><a href="https://oasyce.com" target="_blank" rel="noopener noreferrer">
              <div class="about-link-label">{_['about-link-intro']}</div>
              <div class="about-link-desc">{_['about-link-intro-d']}</div>
            </a></li>
            <li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/WHITEPAPER.md" target="_blank" rel="noopener noreferrer">
              <div class="about-link-label">{_['about-link-whitepaper']}</div>
              <div class="about-link-desc">{_['about-link-whitepaper-d']}</div>
            </a></li>
            <li><a href="https://github.com/Shangri-la-0428/Oasyce_Project/blob/main/docs/PROTOCOL_OVERVIEW.md" target="_blank" rel="noopener noreferrer">
              <div class="about-link-label">{_['about-link-docs']}</div>
              <div class="about-link-desc">{_['about-link-docs-d']}</div>
            </a></li>
            <li><a href="https://github.com/Shangri-la-0428/Oasyce_Project" target="_blank" rel="noopener noreferrer">
              <div class="about-link-label">{_['about-link-github-project']}</div>
              <div class="about-link-desc">{_['about-link-github-project-d']}</div>
            </a></li>
            <li><a href="https://github.com/Shangri-la-0428/Oasyce_Claw_Plugin_Engine" target="_blank" rel="noopener noreferrer">
              <div class="about-link-label">{_['about-link-github-engine']}</div>
              <div class="about-link-desc">{_['about-link-github-engine-d']}</div>
            </a></li>
            <li><a href="https://discord.gg/oasyce" target="_blank" rel="noopener noreferrer">
              <div class="about-link-label">{_['about-link-discord']}</div>
              <div class="about-link-desc">{_['about-link-discord-d']}</div>
            </a></li>
          </ul>
          <div class="about-contact">
            {_['about-link-contact']}<br />
            <a href="mailto:wutc@oasyce.com">wutc@oasyce.com</a>
          </div>
        </div>
      </div>
    </div>
  );
}
