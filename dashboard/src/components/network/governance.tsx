import { useState, useEffect, useRef } from 'preact/hooks';
import { get, post } from '../../api/client';
import { showToast, i18n, walletAddress } from '../../store/ui';
import { Section } from '../section';

export function GovernanceSection({ forceOpen }: { forceOpen: boolean }) {
  const [proposals, setProposals] = useState<any[]>([]);
  const [proposalsLoading, setProposalsLoading] = useState(false);
  const [govAction, setGovAction] = useState<'propose' | 'vote' | null>(null);
  const [propTitle, setPropTitle] = useState('');
  const [propDesc, setPropDesc] = useState('');
  const [propDeposit, setPropDeposit] = useState('');
  const [govSubmitting, setGovSubmitting] = useState(false);
  const [govChainOnly, setGovChainOnly] = useState(false);
  const votingRef = useRef(false);
  const mountedRef = useRef(true);
  useEffect(() => () => { mountedRef.current = false; }, []);

  const _ = i18n.value;

  useEffect(() => {
    let cancelled = false;
    setProposalsLoading(true);
    get<any>('/governance/proposals').then(res => {
      if (cancelled) return;
      if (!mountedRef.current) return;
      if (res.success && res.data) {
        setProposals(Array.isArray(res.data) ? res.data : (res.data.proposals || []));
      } else if (res.error && res.error.toLowerCase().includes('go chain')) {
        setGovChainOnly(true);
      }
      setProposalsLoading(false);
    }).catch(() => { if (!cancelled && mountedRef.current) setProposalsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  return (
    <Section id="governance" title={_['governance']} desc={_['governance-desc']} forceOpen={forceOpen}>
      {govChainOnly && (
        <div class="caption fg-muted mb-12">{_['gov-chain-only']}</div>
      )}

      {proposalsLoading && <div class="caption fg-muted">{_['gov-proposals']}...</div>}

      {!proposalsLoading && !govChainOnly && proposals.length === 0 && (
        <div class="caption fg-muted mb-12">
          <div class="mb-4">{_['gov-no-proposals']}</div>
          <div>{_['gov-no-proposals-hint']}</div>
        </div>
      )}

      {proposals.length > 0 && (
        <div class="mb-16">
          <div class="label-inline mb-8">{_['gov-proposals']}</div>
          {proposals.map((p: any) => (
            <div key={p.proposal_id} class="card mb-8" style="padding: 12px;">
              <div class="kv">
                <span class="kv-key">#{p.proposal_id}</span>
                <span class="kv-val">{p.title}</span>
              </div>
              <div class="kv">
                <span class="kv-key">{_['gov-status']}</span>
                <span class="kv-val mono">{p.status}</span>
              </div>
              {p.description && (
                <p class="caption mt-4">{p.description}</p>
              )}
              <div class="row gap-8 mt-8">
                {(['yes', 'no', 'abstain'] as const).map(option => (
                  <button key={option} class="btn btn-sm btn-ghost" disabled={govSubmitting}
                    onClick={async () => {
                      if (votingRef.current) return;
                      votingRef.current = true;
                      setGovSubmitting(true);
                      const res = await post<any>('/governance/vote', { proposal_id: p.proposal_id, voter: walletAddress(), option });
                      if (!mountedRef.current) return;
                      if (res.success && res.data?.ok) {
                        showToast(_['gov-vote-success'], 'success');
                        // Refresh proposals to show updated vote counts
                        const pRes = await get<any>('/governance/proposals');
                        if (pRes.success && pRes.data) setProposals(Array.isArray(pRes.data) ? pRes.data : (pRes.data.proposals || []));
                      } else {
                        showToast(res.error || res.data?.error || _['error-generic'], 'error');
                      }
                      setGovSubmitting(false);
                      votingRef.current = false;
                    }}>
                    {_[`gov-vote-${option}`]}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Submit Proposal toggle */}
      <div class="net-tools">
        <button class={`nav-item ${govAction === 'propose' ? 'nav-item-active' : ''}`}
          onClick={() => setGovAction(govAction === 'propose' ? null : 'propose')}>
          <span class="nav-item-title">{_['gov-propose']} {govAction === 'propose' ? '\u2193' : '\u2192'}</span>
        </button>
        {govAction === 'propose' && (
          <div class="net-tool-form">
            <input class="input" value={propTitle}
              onInput={e => setPropTitle((e.target as HTMLInputElement).value)}
              placeholder={_['gov-title']} />
            <textarea class="input" rows={3} value={propDesc}
              onInput={e => setPropDesc((e.target as HTMLTextAreaElement).value)}
              placeholder={_['gov-description']} />
            <input class="input" type="number" value={propDeposit}
              onInput={e => setPropDeposit((e.target as HTMLInputElement).value)}
              placeholder={_['gov-deposit']} />
            <button class="btn btn-primary btn-full" disabled={govSubmitting || !propTitle.trim()}
              onClick={async () => {
                if (votingRef.current) return;
                votingRef.current = true;
                setGovSubmitting(true);
                const res = await post<any>('/governance/propose', {
                  title: propTitle.trim(),
                  description: propDesc.trim(),
                  deposit: parseFloat(propDeposit) || 0,
                  proposer: walletAddress(),
                });
                if (!mountedRef.current) return;
                if (res.success && res.data?.ok) {
                  showToast(_['gov-propose-success'], 'success');
                  setPropTitle(''); setPropDesc(''); setPropDeposit('');
                  setGovAction(null);
                  setProposalsLoading(true);
                  const pRes = await get<any>('/governance/proposals');
                  if (pRes.success && pRes.data) setProposals(Array.isArray(pRes.data) ? pRes.data : (pRes.data.proposals || []));
                  setProposalsLoading(false);
                } else {
                  showToast(res.error || res.data?.error || _['error-generic'], 'error');
                }
                setGovSubmitting(false);
                votingRef.current = false;
              }}>
              {govSubmitting ? _['gov-proposing'] : _['gov-propose']}
            </button>
          </div>
        )}
      </div>
    </Section>
  );
}
