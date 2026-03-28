import { useMemo, useState } from 'preact/hooks';
import {
  i18n,
  joinExistingAccount,
  prepareLocalAccount,
  showToast,
} from '../store/ui';

type Mode = 'prepare' | 'readonly' | 'signing';

export default function AccountJoinPanel({ onReady }: { onReady?: () => void }) {
  const _ = i18n.value;
  const [mode, setMode] = useState<Mode>('prepare');
  const [accountAddress, setAccountAddress] = useState('');
  const [signerName, setSignerName] = useState('');
  const [loading, setLoading] = useState(false);
  const [issues, setIssues] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);

  const canSubmitJoin = useMemo(() => {
    if (!accountAddress.trim()) return false;
    if (mode === 'signing' && !signerName.trim()) return false;
    return true;
  }, [accountAddress, mode, signerName]);

  async function handlePrepare() {
    if (loading) return;
    setLoading(true);
    setIssues([]);
    setWarnings([]);
    const result = await prepareLocalAccount();
    setLoading(false);
    if (result.ok) {
      showToast(_['device-prepare-success'], 'success');
      onReady?.();
      return;
    }
    setIssues(result.issues || []);
    setWarnings(result.warnings || []);
    showToast(result.error || _['error-generic'], 'error');
  }

  async function handleJoin() {
    if (loading || !canSubmitJoin) return;
    setLoading(true);
    setIssues([]);
    setWarnings([]);
    const result = await joinExistingAccount({
      accountAddress: accountAddress.trim(),
      signerName: mode === 'signing' ? signerName.trim() : undefined,
      readonly: mode === 'readonly',
    });
    setLoading(false);
    if (result.ok) {
      showToast(_['device-join-success'], 'success');
      onReady?.();
      return;
    }
    setIssues(result.issues || []);
    setWarnings(result.warnings || []);
    showToast(result.error || _['error-generic'], 'error');
  }

  return (
    <div class="home-account-panel">
      <div class="home-account-modes" role="tablist" aria-label={_['account-entry-title']}>
        <button
          type="button"
          class={`btn ${mode === 'prepare' ? 'btn-primary' : 'btn-ghost'}`}
          role="tab"
          aria-selected={mode === 'prepare'}
          onClick={() => setMode('prepare')}
        >
          {_['prepare-device']}
        </button>
        <button
          type="button"
          class={`btn ${mode === 'readonly' ? 'btn-primary' : 'btn-ghost'}`}
          role="tab"
          aria-selected={mode === 'readonly'}
          onClick={() => setMode('readonly')}
        >
          {_['join-existing-readonly']}
        </button>
        <button
          type="button"
          class={`btn ${mode === 'signing' ? 'btn-primary' : 'btn-ghost'}`}
          role="tab"
          aria-selected={mode === 'signing'}
          onClick={() => setMode('signing')}
        >
          {_['join-existing-signing']}
        </button>
      </div>

      {mode === 'prepare' && (
        <div class="home-account-card">
          <div class="home-account-copy">
            <strong>{_['prepare-device']}</strong>
            <p class="caption fg-muted">{_['prepare-device-hint']}</p>
          </div>
          <button type="button" class="btn btn-primary" onClick={handlePrepare} disabled={loading}>
            {loading ? '…' : _['prepare-device']}
          </button>
        </div>
      )}

      {mode !== 'prepare' && (
        <div class="home-account-card">
          <label class="label" htmlFor="join-account-address">{_['join-account-address']}</label>
          <input
            id="join-account-address"
            class="input"
            value={accountAddress}
            onInput={e => setAccountAddress((e.target as HTMLInputElement).value)}
            placeholder={_['join-account-address-hint']}
            autoComplete="off"
            spellcheck={false}
          />
          {mode === 'signing' && (
            <>
              <label class="label" htmlFor="join-signer-name">{_['join-signer-name']}</label>
              <input
                id="join-signer-name"
                class="input"
                value={signerName}
                onInput={e => setSignerName((e.target as HTMLInputElement).value)}
                placeholder={_['join-signer-name-hint']}
                autoComplete="off"
                spellcheck={false}
              />
            </>
          )}
          <p class="caption fg-muted">
            {mode === 'readonly' ? _['join-readonly-hint'] : _['join-signing-hint']}
          </p>
          <button
            type="button"
            class="btn btn-primary"
            onClick={handleJoin}
            disabled={loading || !canSubmitJoin}
          >
            {loading ? '…' : _['join-existing']}
          </button>
        </div>
      )}

      {(issues.length > 0 || warnings.length > 0) && (
        <div class="home-account-feedback" role="status" aria-live="polite">
          {issues.length > 0 && (
            <div class="home-account-feedback-block is-error">
              <div class="label">{_['issues']}</div>
              <ul class="home-account-list">
                {issues.map(issue => <li key={issue}>{issue}</li>)}
              </ul>
            </div>
          )}
          {warnings.length > 0 && (
            <div class="home-account-feedback-block is-warning">
              <div class="label">{_['warnings']}</div>
              <ul class="home-account-list">
                {warnings.map(warning => <li key={warning}>{warning}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
