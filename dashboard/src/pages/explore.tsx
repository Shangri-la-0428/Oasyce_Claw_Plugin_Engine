/**
 * Explore — 搜索网络上的资产（数据 + 服务），查看报价，获取访问权/调用
 * + Portfolio (持仓) + Stake (质押)
 */
import { useState } from 'preact/hooks';
import { i18n } from '../store/ui';
import ExploreBrowse from './explore-browse';
import ExplorePortfolio from './explore-portfolio';
import ExploreStake from './explore-stake';
import ExploreBounty from './explore-bounty';
import ExploreEarnings from './explore-earnings';
import ExploreDisputes from './explore-disputes';
import './explore.css';

type ExploreTab = 'browse' | 'portfolio' | 'stake' | 'bounty' | 'earnings' | 'disputes';

interface ExploreProps { subpath?: string; }

export default function Explore({ subpath }: ExploreProps) {
  const [exploreTab, setExploreTab] = useState<ExploreTab>('browse');
  const _ = i18n.value;

  return (
    <div class="page">
      <h1 class="label m-0 mb-4">{_['explore-title']}</h1>
      <p class="caption m-0 mb-24">{_['explore-desc']}</p>

      {/* Section tabs */}
      <div class="tabs mb-24" role="tablist" aria-label={_['explore-title']}>
        <button role="tab" aria-selected={exploreTab === 'browse'} class={`tab ${exploreTab === 'browse' ? 'active' : ''}`} onClick={() => setExploreTab('browse')}>
          {_['browse-all']}
        </button>
        <button role="tab" aria-selected={exploreTab === 'portfolio'} class={`tab ${exploreTab === 'portfolio' ? 'active' : ''}`} onClick={() => setExploreTab('portfolio')}>
          {_['portfolio']}
        </button>
        <button role="tab" aria-selected={exploreTab === 'stake'} class={`tab ${exploreTab === 'stake' ? 'active' : ''}`} onClick={() => setExploreTab('stake')}>
          {_['stake']}
        </button>
        <button role="tab" aria-selected={exploreTab === 'bounty'} class={`tab ${exploreTab === 'bounty' ? 'active' : ''}`} onClick={() => setExploreTab('bounty')}>
          {_['bounty']}
        </button>
        <button role="tab" aria-selected={exploreTab === 'earnings'} class={`tab ${exploreTab === 'earnings' ? 'active' : ''}`} onClick={() => setExploreTab('earnings')}>
          {_['earnings-tab']}
        </button>
        <button role="tab" aria-selected={exploreTab === 'disputes'} class={`tab ${exploreTab === 'disputes' ? 'active' : ''}`} onClick={() => setExploreTab('disputes')}>
          {_['disputes-tab']}
        </button>
      </div>

      {exploreTab === 'browse' && <ExploreBrowse subpath={subpath} />}
      {exploreTab === 'portfolio' && <ExplorePortfolio onBrowse={() => setExploreTab('browse')} />}
      {exploreTab === 'stake' && <ExploreStake />}
      {exploreTab === 'bounty' && <ExploreBounty />}
      {exploreTab === 'earnings' && <ExploreEarnings onRegister={() => setExploreTab('browse')} />}
      {exploreTab === 'disputes' && <ExploreDisputes />}
    </div>
  );
}
