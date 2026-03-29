import { exportDeviceBundle, i18n, showToast } from '../store/ui';
import { useState } from 'preact/hooks';

function triggerBundleDownload(filename: string, bundle: unknown) {
  const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export default function DeviceSharePanel({ canSign }: { canSign: boolean }) {
  const _ = i18n.value;
  const [loadingMode, setLoadingMode] = useState<'signing' | 'readonly' | null>(null);

  async function handleExport(readonly: boolean) {
    if (loadingMode) return;
    setLoadingMode(readonly ? 'readonly' : 'signing');
    const result = await exportDeviceBundle({ readonly });
    setLoadingMode(null);
    if (!result.ok) {
      showToast(result.error || _['error-generic'], 'error');
      return;
    }
    const filename = result.data?.filename || `oasyce-device-${readonly ? 'readonly' : 'signing'}.json`;
    triggerBundleDownload(filename, result.data?.bundle || {});
    showToast(
      readonly ? _['device-export-readonly-success'] : _['device-export-success'],
      'success',
    );
  }

  return (
    <section class="home-device-share" aria-label={_['device-export-title']}>
      <div class="home-device-share-copy">
        <div class="label">{_['device-export-title']}</div>
        <p class="caption fg-muted">{_['device-export-hint']}</p>
        {canSign && <p class="caption fg-muted">{_['device-export-signer-warning']}</p>}
      </div>
      <div class="row gap-8 wrap">
        {canSign && (
          <button
            type="button"
            class="btn btn-primary"
            onClick={() => handleExport(false)}
            disabled={loadingMode !== null}
          >
            {loadingMode === 'signing' ? '…' : _['device-export-signing']}
          </button>
        )}
        <button
          type="button"
          class="btn btn-ghost"
          onClick={() => handleExport(true)}
          disabled={loadingMode !== null}
        >
          {loadingMode === 'readonly' ? '…' : _['device-export-readonly']}
        </button>
      </div>
    </section>
  );
}
