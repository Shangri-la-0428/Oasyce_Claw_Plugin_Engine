/**
 * Stake tab — validator list, delegation
 */
import { useEffect, useState } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n } from '../store/ui';
import { maskIdShort, fmtPrice } from '../utils';
import { EmptyState } from '../components/empty-state';
import './explore.css';

interface ValidatorInfo {
  id: string;
  staked: number;
  reputation: number;
}

export default function ExploreStake() {
  const [validators, setValidators] = useState<ValidatorInfo[]>([]);
  const [stakeAmts, setStakeAmts] = useState<Record<string, string>>({});
  const [stakingId, setStakingId] = useState<string | null>(null);

  const _ = i18n.value;

  useEffect(() => {
    loadValidators();
  }, []);

  const loadValidators = async () => {
    const res = await get<{ validators: ValidatorInfo[] }>('/staking');
    if (res.success && Array.isArray(res.data?.validators)) setValidators(res.data.validators);
  };

  /* 质押 */
  const onStake = async (validatorId: string) => {
    const amt = parseFloat(stakeAmts[validatorId] || '10000');
    if (!amt || amt <= 0) return;
    setStakingId(validatorId);
    const res = await post<{ success: boolean; staked: number }>('/stake', { validator_id: validatorId, amount: amt });
    if (res.success && res.data?.success) {
      showToast(_['stake-success'], 'success');
      loadValidators();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setStakingId(null);
  };

  return (
    <>
      <h2 class="label-inline mb-16">{_['stake']}</h2>
      {validators.length === 0 ? (
        <EmptyState icon="⬡" title={_['no-validators']} hint={_['stake-hint']} />
      ) : (
        <div class="col gap-16">
          {validators.map(v => (
            <div key={v.id} class="card stake-card">
              <div class="kv"><span class="kv-key">{_['validator']}</span><span class="kv-val">{maskIdShort(v.id)}</span></div>
              <div class="kv"><span class="kv-key">{_['staked']}</span><span class="kv-val">{fmtPrice(v.staked)} OAS</span></div>
              <div class="kv"><span class="kv-key">{_['reputation']}</span><span class="kv-val">{v.reputation}</span></div>
              <div class="row gap-8 mt-12">
                <input
                  class="input grow"
                  type="number"
                  placeholder={_['stake-amount']}
                  value={stakeAmts[v.id] || ''}
                  onInput={e => setStakeAmts(prev => ({ ...prev, [v.id]: (e.target as HTMLInputElement).value }))}
                  min="1"
                />
                <button class="btn btn-primary" onClick={() => onStake(v.id)} disabled={stakingId === v.id}>
                  {stakingId === v.id ? _['staking'] : _['stake']}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}
