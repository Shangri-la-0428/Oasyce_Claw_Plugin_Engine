import { useMemo, useState } from 'preact/hooks';
import {
  i18n,
  joinDeviceBundle,
  joinExistingAccount,
  prepareLocalAccount,
  showToast,
} from '../store/ui';

type Mode = 'prepare' | 'bundle' | 'advanced';
type AdvancedMode = 'readonly' | 'signing';

export default function AccountJoinPanel({ onReady }: { onReady?: () => void }) {
  const _ = i18n.value;
  const [mode, setMode] = useState<Mode>('prepare');
  const [advancedMode, setAdvancedMode] = useState<AdvancedMode>('readonly');
  const [accountAddress, setAccountAddress] = useState('');
  const [signerName, setSignerName] = useState('');
  const [bundleFile, setBundleFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [issues, setIssues] = useState<string[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);

  const canSubmitManualJoin = useMemo(() => {
    if (!accountAddress.trim()) return false;
    if (advancedMode === 'signing' && !signerName.trim()) return false;
    return true;
  }, [accountAddress, advancedMode, signerName]);

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

  async function handleBundleJoin() {
    if (loading || !bundleFile) return;
    setLoading(true);
    setIssues([]);
    setWarnings([]);
    try {
      const raw = await bundleFile.text();
      const parsed = JSON.parse(raw) as Record<string, unknown>;
      const result = await joinDeviceBundle(parsed);
      setLoading(false);
      if (result.ok) {
        showToast(_['device-join-success'], 'success');
        onReady?.();
        return;
      }
      setIssues(result.issues || []);
      setWarnings(result.warnings || []);
      showToast(result.error || _['error-generic'], 'error');
    } catch {
      setLoading(false);
      setIssues([_['join-bundle-invalid']]);
      showToast(_['join-bundle-invalid'], 'error');
    }
  }

  async function handleJoin() {
    if (loading || !canSubmitManualJoin) return;
    setLoading(true);
    setIssues([]);
    setWarnings([]);
    const result = await joinExistingAccount({
      accountAddress: accountAddress.trim(),
      signerName: advancedMode === 'signing' ? signerName.trim() : undefined,
      readonly: advancedMode === 'readonly',
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
          class={`btn ${mode === 'bundle' ? 'btn-primary' : 'btn-ghost'}`}
          role="tab"
          aria-selected={mode === 'bundle'}
          onClick={() => setMode('bundle')}
        >
          {_['join-existing-bundle']}
        </button>
        <button
          type="button"
          class={`btn ${mode === 'advanced' ? 'btn-primary' : 'btn-ghost'}`}
          role="tab"
          aria-selected={mode === 'advanced'}
          onClick={() => setMode('advanced')}
        >
          {_['join-existing-advanced']}
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

      {mode === 'bundle' && (
        <div class="home-account-card">
          <div class="home-account-copy">
            <strong>{_['join-existing-bundle']}</strong>
            <p class="caption fg-muted">{_['join-bundle-hint']}</p>
          </div>
          <label class="home-account-file" htmlFor="join-bundle-file">
            <span class="label">{_['join-bundle-file']}</span>
            <span class={`home-account-file-name ${bundleFile ? '' : 'is-placeholder'}`}>
              {bundleFile ? `${_['join-bundle-selected']}: ${bundleFile.name}` : _['join-bundle-file-hint']}
            </span>
            <input
              id="join-bundle-file"
              class="sr-only"
              type="file"
              accept=".json,application/json"
              onChange={event => {
                const file = (event.currentTarget as HTMLInputElement).files?.[0] || null;
                setBundleFile(file);
              }}
            />
          </label>
          <p class="caption fg-muted">{_['join-bundle-warning']}</p>
          <button
            type="button"
            class="btn btn-primary"
            onClick={handleBundleJoin}
            disabled={loading || !bundleFile}
          >
            {loading ? '…' : _['join-bundle-submit']}
          </button>
        </div>
      )}

      {mode === 'advanced' && (
        <div class="home-account-card">
          <div class="home-account-copy">
            <strong>{_['join-existing-advanced']}</strong>
            <p class="caption fg-muted">{_['join-advanced-hint']}</p>
          </div>
          <div class="home-account-modes" role="tablist" aria-label={_['join-existing-advanced']}>
            <button
              type="button"
              class={`btn ${advancedMode === 'readonly' ? 'btn-primary' : 'btn-ghost'}`}
              role="tab"
              aria-selected={advancedMode === 'readonly'}
              onClick={() => setAdvancedMode('readonly')}
            >
              {_['join-existing-readonly']}
            </button>
            <button
              type="button"
              class={`btn ${advancedMode === 'signing' ? 'btn-primary' : 'btn-ghost'}`}
              role="tab"
              aria-selected={advancedMode === 'signing'}
              onClick={() => setAdvancedMode('signing')}
            >
              {_['join-existing-signing']}
            </button>
          </div>
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
          {advancedMode === 'signing' && (
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
            {advancedMode === 'readonly' ? _['join-readonly-hint'] : _['join-signing-hint']}
          </p>
          <button
            type="button"
            class="btn btn-primary"
            onClick={handleJoin}
            disabled={loading || !canSubmitManualJoin}
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
