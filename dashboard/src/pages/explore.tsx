/**
 * Explore — 搜索网络上的资产（数据 + 服务），查看报价，获取访问权/调用
 * + Portfolio (持仓) + Stake (质押)
 */
import { useState } from 'preact/hooks';
import { i18n } from '../store/ui';
import ExploreBrowse from './explore-browse';
import ExplorePortfolio from './explore-portfolio';
import ExploreStake from './explore-stake';
import './explore.css';

type ExploreTab = 'browse' | 'portfolio' | 'stake';

interface ExploreProps { subpath?: string; }

export default function Explore({ subpath }: ExploreProps) {
  const [exploreTab, setExploreTab] = useState<ExploreTab>('browse');
  const _ = i18n.value;

  return (
    <div class="page">
      <h1 class="label m-0 mb-4">{_['explore-title']}</h1>
      <p class="caption m-0 mb-48">{_['explore-desc']}</p>

      {/* Section tabs */}
      <div class="tabs mb-24">
        <button class={`tab ${exploreTab === 'browse' ? 'active' : ''}`} onClick={() => setExploreTab('browse')}>
          {_['browse-all']}
        </button>
        <button class={`tab ${exploreTab === 'portfolio' ? 'active' : ''}`} onClick={() => setExploreTab('portfolio')}>
          {_['portfolio']}
        </button>
        <button class={`tab ${exploreTab === 'stake' ? 'active' : ''}`} onClick={() => setExploreTab('stake')}>
          {_['stake']}
        </button>
      </div>

      {exploreTab === 'browse' && <ExploreBrowse subpath={subpath} />}
      {exploreTab === 'portfolio' && <ExplorePortfolio />}
      {exploreTab === 'stake' && <ExploreStake />}
    </div>
  );
}
