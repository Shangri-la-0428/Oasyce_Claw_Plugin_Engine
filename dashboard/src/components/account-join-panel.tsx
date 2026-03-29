import type { ComponentChildren } from 'preact';
import { useMemo, useState } from 'preact/hooks';
import {
  i18n,
  joinDeviceBundle,
  joinExistingAccount,
  prepareLocalAccount,
  showToast,
} from '../store/ui';

type Stage = 'question' | 'prepare' | 'existing' | 'advanced';
type AdvancedMode = 'readonly' | 'signing';

export default function AccountJoinPanel(
  { onReady, onCancel }: { onReady?: () => void; onCancel?: () => void },
) {
  const _ = i18n.value;
  const [stage, setStage] = useState<Stage>('question');
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

  function resetFeedback() {
    setIssues([]);
    setWarnings([]);
  }

  function goTo(nextStage: Stage) {
    if (loading) return;
    resetFeedback();
    setStage(nextStage);
  }

  async function handlePrepare() {
    if (loading) return;
    setLoading(true);
    resetFeedback();
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
    resetFeedback();
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
    resetFeedback();
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

  function renderActions(content: ComponentChildren) {
    return <div class="row gap-8 wrap">{content}</div>;
  }

  return (
    <div class="home-account-panel">
      {stage === 'question' && (
        <div class="home-account-card">
          <div class="home-account-copy">
            <strong>{_['account-entry-question']}</strong>
            <p class="caption fg-muted">{_['account-entry-hint']}</p>
          </div>
          <div class="home-account-choice-grid">
            <button
              type="button"
              class="home-account-choice"
              onClick={() => goTo('prepare')}
              disabled={loading}
            >
              <strong>{_['account-entry-create']}</strong>
              <span class="caption fg-muted">{_['account-entry-create-hint']}</span>
            </button>
            <button
              type="button"
              class="home-account-choice"
              onClick={() => goTo('existing')}
              disabled={loading}
            >
              <strong>{_['account-entry-existing']}</strong>
              <span class="caption fg-muted">{_['account-entry-existing-hint']}</span>
            </button>
          </div>
          {onCancel && (
            renderActions(
              <button type="button" class="btn btn-ghost" onClick={onCancel} disabled={loading}>
                {_['account-entry-cancel']}
              </button>,
            )
          )}
        </div>
      )}

      {stage === 'prepare' && (
        <div class="home-account-card">
          <div class="home-account-copy">
            <strong>{_['prepare-device']}</strong>
            <p class="caption fg-muted">{_['prepare-device-hint']}</p>
          </div>
          {renderActions(
            <>
              <button type="button" class="btn btn-primary" onClick={handlePrepare} disabled={loading}>
                {loading ? '…' : _['prepare-device']}
              </button>
              <button type="button" class="btn btn-ghost" onClick={() => goTo('question')} disabled={loading}>
                {_['account-entry-back']}
              </button>
            </>,
          )}
        </div>
      )}

      {stage === 'existing' && (
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
          {renderActions(
            <>
              <button
                type="button"
                class="btn btn-primary"
                onClick={handleBundleJoin}
                disabled={loading || !bundleFile}
              >
                {loading ? '…' : _['join-bundle-submit']}
              </button>
              <button type="button" class="btn btn-ghost" onClick={() => goTo('question')} disabled={loading}>
                {_['account-entry-back']}
              </button>
              <button type="button" class="btn btn-ghost" onClick={() => goTo('advanced')} disabled={loading}>
                {_['account-entry-advanced']}
              </button>
            </>,
          )}
        </div>
      )}

      {stage === 'advanced' && (
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
          {renderActions(
            <>
              <button
                type="button"
                class="btn btn-primary"
                onClick={handleJoin}
                disabled={loading || !canSubmitManualJoin}
              >
                {loading ? '…' : _['join-existing']}
              </button>
              <button type="button" class="btn btn-ghost" onClick={() => goTo('existing')} disabled={loading}>
                {_['account-entry-back']}
              </button>
            </>,
          )}
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
