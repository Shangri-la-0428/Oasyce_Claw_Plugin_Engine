/**
 * RegisterForm — shared data/capability registration component
 * Extracted from home.tsx and mydata.tsx to eliminate duplication.
 */
import { useState, useRef } from 'preact/hooks';
import { post, postFile, postBundle } from '../api/client';
import { showToast, i18n, walletAddress } from '../store/ui';
import { loadAssets } from '../store/assets';
import { readEntryFiles } from '../utils';
import './register-form.css';

interface Props {
  mode: 'data' | 'capability';
  onSuccess?: (result: any) => void;
  compact?: boolean;
}

function baseName(name: string) {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(0, dot) : name;
}

export default function RegisterForm({ mode, onSuccess, compact }: Props) {
  // ── Data registration state ──
  const [file, setFile] = useState<File | null>(null);
  const [desc, setDesc] = useState('');
  const [loading, setLoading] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [rightsType, setRightsType] = useState('original');
  const [priceModel, setPriceModel] = useState('auto');
  const [manualPrice, setManualPrice] = useState('');
  const [coCreators, setCoCreators] = useState<{address: string; share: number}[]>([{address: '', share: 50}, {address: '', share: 50}]);

  // Folder state
  const [folderName, setFolderName] = useState<string | null>(null);
  const [folderFiles, setFolderFiles] = useState<File[]>([]);

  // ── Capability state ──
  const [capName, setCapName] = useState('');
  const [capDesc, setCapDesc] = useState('');
  const [capEndpoint, setCapEndpoint] = useState('');
  const [capApiKey, setCapApiKey] = useState('');
  const [capPrice, setCapPrice] = useState('0');
  const [capTags, setCapTags] = useState('');
  const [capRateLimit, setCapRateLimit] = useState('60');
  const [capAdvanced, setCapAdvanced] = useState(false);

  const ref = useRef<HTMLInputElement>(null);

  const _ = i18n.value;

  const hasSelection = !!(file || folderName);
  const owner = walletAddress();
  const filledCoCreators = coCreators
    .map(c => ({ address: c.address.trim(), share: Number(c.share) || 0 }))
    .filter(c => c.address);
  const totalCoCreatorShare = filledCoCreators.reduce((sum, c) => sum + c.share, 0);
  const coCreationError = rightsType !== 'co_creation'
    ? ''
    : filledCoCreators.length < 2
      ? (_['co-creators-hint'] || 'Co-creation requires at least 2 people, shares must total 100%')
      : Math.abs(totalCoCreatorShare - 100) > 0.01
        ? `${_['co-creators-sum'] || 'Total shares'}: ${totalCoCreatorShare}%`
        : '';

  const clearSelection = () => {
    setFile(null); setDesc('');
    setFolderName(null); setFolderFiles([]);
    setRightsType('original');
    setPriceModel('auto'); setManualPrice('');
    setCoCreators([{address: '', share: 50}, {address: '', share: 50}]);
  };

  const onFile = (f: File) => {
    setFile(f);
    setFolderName(null); setFolderFiles([]);
    if (!desc) setDesc(baseName(f.name));
  };

  const onFolderDetected = (name: string, files: File[]) => {
    setFolderName(name); setFolderFiles(files);
    setFile(null);
    if (!desc) setDesc(name);
  };

  const onDrop = async (e: DragEvent) => {
    e.preventDefault(); setDragging(false);
    if (mode === 'capability') return;
    const items = e.dataTransfer?.items;
    if (items && items.length > 0) {
      const entry = (items[0] as any).webkitGetAsEntry?.();
      if (entry?.isDirectory) {
        const name = entry.name || 'folder';
        const files = await readEntryFiles(entry);
        onFolderDetected(name, files);
        return;
      }
    }
    const f = e.dataTransfer?.files[0];
    if (f) onFile(f);
  };

  const submitFile = async () => {
    if (!file) return;
    if (owner === 'anonymous') {
      showToast(_['wallet-needed'] || 'Create your wallet to get started', 'error');
      return;
    }
    if (rightsType === 'co_creation' && coCreationError) {
      showToast(coCreationError, 'error');
      return;
    }
    if ((priceModel === 'fixed' || priceModel === 'floor') && !(parseFloat(manualPrice) > 0)) {
      showToast(_['error-generic'], 'error');
      return;
    }
    setLoading(true);
    const tags = desc.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean).join(',');
    const fields: Record<string, string> = {
      owner,
      tags,
      rights_type: rightsType,
      price_model: priceModel,
    };
    if (rightsType === 'co_creation') {
      fields.co_creators = JSON.stringify(filledCoCreators);
    }
    if ((priceModel === 'fixed' || priceModel === 'floor') && manualPrice) {
      fields.price = manualPrice;
    }
    const res = await postFile('/register', file, fields);
    if (res.success) {
      showToast(_['protected'], 'success');
      loadAssets(); clearSelection();
      onSuccess?.(res.data);
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  const submitBundle = async () => {
    if (folderFiles.length === 0) return;
    if (owner === 'anonymous') {
      showToast(_['wallet-needed'] || 'Create your wallet to get started', 'error');
      return;
    }
    setLoading(true);
    const tags = desc.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean).join(',');
    const res = await postBundle(folderFiles, {
      name: folderName || 'bundle',
      owner,
      tags,
    });
    if (res.success) {
      showToast(_['protected'], 'success');
      loadAssets(); clearSelection();
      onSuccess?.(res.data);
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  const submitCap = async () => {
    if (!capName.trim() || !capEndpoint.trim()) return;
    if (owner === 'anonymous') {
      showToast(_['wallet-needed'] || 'Create your wallet to get started', 'error');
      return;
    }
    setLoading(true);
    const tags = capTags.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean);
    const res = await post<{ ok?: boolean; capability_id?: string; error?: string }>('/delivery/register', {
      name: capName.trim(),
      provider: owner,
      description: capDesc.trim(),
      endpoint: capEndpoint.trim(),
      api_key: capApiKey.trim() || undefined,
      price: parseFloat(capPrice) || 0,
      tags,
      rate_limit: parseInt(capRateLimit) || 60,
    });
    if (res.success && res.data?.ok) {
      showToast(_['cap-published'] || '\u5df2\u53d1\u5e03', 'success');
      loadAssets();
      const result = { asset_id: res.data.capability_id, capability: true };
      setCapName(''); setCapDesc(''); setCapEndpoint(''); setCapApiKey('');
      setCapPrice('0'); setCapTags(''); setCapRateLimit('60'); setCapAdvanced(false);
      onSuccess?.(result);
    } else {
      showToast(res.error || res.data?.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  const fieldsClass = compact ? 'register-fields compact' : 'register-fields';

  if (mode === 'capability') {
    return (
      <div class={fieldsClass}>
        <div class="caption mb-4">
          {_['cap-guide'] || '\u5c06\u4f60\u7684 AI \u80fd\u529b\u53d1\u5e03\u5230\u7f51\u7edc\uff0c\u5176\u4ed6\u4eba\u53ef\u4ee5\u53d1\u73b0\u548c\u8c03\u7528\u3002'}
        </div>
        <div>
          <label class="label" htmlFor="cap-name">{_['cap-name'] || '\u540d\u79f0'}</label>
          <input id="cap-name" class="input" value={capName}
            onInput={e => setCapName((e.target as HTMLInputElement).value)}
            placeholder={_['cap-name-hint'] || '\u4f8b\u5982\uff1a\u56fe\u50cf\u98ce\u683c\u8fc1\u79fb'}
            required aria-required="true" />
        </div>
        <div>
          <label class="label" htmlFor="cap-endpoint">{_['cap-endpoint']}</label>
          <input id="cap-endpoint" class="input" value={capEndpoint}
            onInput={e => setCapEndpoint((e.target as HTMLInputElement).value)}
            placeholder={_['cap-endpoint-hint']}
            required aria-required="true" />
        </div>

        {/* Advanced section — progressive disclosure */}
        <button class="btn btn-ghost btn-sm self-start" onClick={() => setCapAdvanced(!capAdvanced)}>
          {capAdvanced ? '\u25be' : '\u25b8'} {_['cap-advanced']}
        </button>
        {capAdvanced && (
          <>
            <div>
              <label class="label" htmlFor="cap-api-key">{_['cap-api-key']}</label>
              <input id="cap-api-key" class="input" type="password" value={capApiKey}
                onInput={e => setCapApiKey((e.target as HTMLInputElement).value)}
                placeholder={_['cap-api-key-hint']} />
            </div>
            <div>
              <label class="label" htmlFor="cap-desc">{_['describe']}</label>
              <input id="cap-desc" class="input" value={capDesc}
                onInput={e => setCapDesc((e.target as HTMLInputElement).value)}
                placeholder={_['cap-desc-hint'] || '\u8f93\u5165\u56fe\u7247\uff0c\u8f93\u51fa\u6307\u5b9a\u98ce\u683c\u7684\u65b0\u56fe\u7247'} />
              <div class="caption mt-4">
                {_['cap-desc-guide'] || '\u63cf\u8ff0\u8f93\u5165\u8f93\u51fa\uff0c\u5e2e\u52a9\u522b\u4eba\u7406\u89e3\u5982\u4f55\u4f7f\u7528'}
              </div>
            </div>
            <div>
              <label class="label" htmlFor="cap-price">{_['cap-price']}</label>
              <input id="cap-price" class="input" type="number" value={capPrice} min="0" step="0.01"
                onInput={e => setCapPrice((e.target as HTMLInputElement).value)} />
            </div>
            <div>
              <label class="label" htmlFor="cap-tags">{_['cap-tags']}</label>
              <input id="cap-tags" class="input" value={capTags}
                onInput={e => setCapTags((e.target as HTMLInputElement).value)}
                placeholder={_['cap-tags-hint']} />
            </div>
            <div>
              <label class="label" htmlFor="cap-rate-limit">{_['cap-rate-limit']}</label>
              <input id="cap-rate-limit" class="input" type="number" value={capRateLimit} min="1"
                onInput={e => setCapRateLimit((e.target as HTMLInputElement).value)} />
              <div class="caption mt-4">{_['cap-rate-limit-hint']}</div>
            </div>
          </>
        )}

        <button
          class="btn btn-primary btn-full"
          onClick={submitCap}
          disabled={loading || owner === 'anonymous' || !capName.trim() || !capEndpoint.trim()}
        >
          {loading ? _['protecting'] : (_['publish-cap'] || '\u53d1\u5e03\u80fd\u529b')}
        </button>
      </div>
    );
  }

  // ── Data mode ──
  return (
    <>
      {/* Dropzone */}
      <div
        class={`dropzone ${dragging ? 'dropzone-active' : ''} ${hasSelection ? 'dropzone-done' : ''} ${compact ? 'mb-24' : ''}`}
        role="button"
        tabIndex={0}
        aria-label={hasSelection ? (folderName || file?.name || '') : (_['drop-browse'] || 'Select file')}
        onDrop={onDrop}
        onDragOver={e => { e.preventDefault(); setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onClick={() => { if (!hasSelection) ref.current?.click(); }}
        onKeyDown={e => { if (!hasSelection && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); ref.current?.click(); } }}
      >
        {hasSelection ? (
          <div class="dropzone-selected">
            <span class="dropzone-selected-name">
              {folderName ? `${folderName}/` : file!.name}
            </span>
            {folderName && (
              <span class="caption">{folderFiles.length} {_['files'] || '\u4e2a\u6587\u4ef6'}</span>
            )}
            <button
              class="dropzone-clear"
              onClick={e => { e.stopPropagation(); clearSelection(); }}
              aria-label="clear"
            >&times;</button>
          </div>
        ) : (
          <>
            <div class="dropzone-icon" aria-hidden="true">&uarr;</div>
            <div class="dropzone-text">
              <strong>{_['drop-browse'] || '\u9009\u62e9\u6587\u4ef6'}</strong>
            </div>
            <div class="caption mt-6">
              {_['drop-folder-hint'] || '\u652f\u6301\u62d6\u5165\u6587\u4ef6\u5939'}
            </div>
          </>
        )}
        <input ref={ref} type="file" class="hidden" aria-label="Upload file" onChange={e => {
          const f = (e.target as HTMLInputElement).files?.[0];
          if (f) onFile(f);
        }} />
      </div>

      {/* Folder registration form */}
      {folderName && (
        <div class={`${fieldsClass} ${compact ? 'mb-24' : ''}`}>
          <div>
            <label class="label" htmlFor="folder-desc">{_['describe']}</label>
            <input id="folder-desc" class="input" value={desc}
              onInput={e => setDesc((e.target as HTMLInputElement).value)}
              placeholder={folderName}
              required aria-required="true" />
          </div>
          <button class="btn btn-primary btn-full" onClick={submitBundle} disabled={loading}>
            {loading ? _['protecting'] : _['protect']}
          </button>
        </div>
      )}

      {/* Single file registration form */}
      {file && (
        <div class={`${fieldsClass} ${compact ? 'mb-24' : ''}`}>
          <div>
            <label class="label" htmlFor="file-desc">{_['describe']}</label>
            <input id="file-desc" class="input" value={desc}
              onInput={e => setDesc((e.target as HTMLInputElement).value)}
              placeholder={_['describe-hint']}
              required aria-required="true" />
          </div>
          {!compact && (
            <>
              <div>
                <label class="label" htmlFor="rights-type">{_['rights-type']}</label>
                <select id="rights-type" class="input" value={rightsType} onChange={e => setRightsType((e.target as HTMLSelectElement).value)}>
                  <option value="original">{_['rights-original']}</option>
                  <option value="co_creation">{_['rights-co_creation']}</option>
                  <option value="licensed">{_['rights-licensed']}</option>
                  <option value="collection">{_['rights-collection']}</option>
                </select>
              </div>
              {rightsType === 'co_creation' && (
                <div>
                  <label class="label" htmlFor="co-creators">{_['co-creators']}</label>
                  <div class="caption mb-8">{_['co-creators-hint']}</div>
                  {coCreators.map((c, i) => (
                    <div key={i} class="row gap-8 mb-6">
                      <input class="input input-flex-2" placeholder={_['co-creator-address']} value={c.address}
                        onInput={e => { const v = [...coCreators]; v[i] = {...v[i], address: (e.target as HTMLInputElement).value}; setCoCreators(v); }} />
                      <input class="input input-share" type="number" placeholder="%" value={c.share}
                        onInput={e => { const v = [...coCreators]; v[i] = {...v[i], share: Number((e.target as HTMLInputElement).value)}; setCoCreators(v); }} />
                      {coCreators.length > 2 && (
                        <button class="btn btn-ghost btn-sm" onClick={() => setCoCreators(coCreators.filter((_, j) => j !== i))}>{_['remove-co-creator']}</button>
                      )}
                    </div>
                  ))}
                  <div class="row between mt-8">
                    <button class="btn btn-ghost btn-sm" onClick={() => setCoCreators([...coCreators, {address: '', share: 0}])}>
                      + {_['add-co-creator']}
                    </button>
                    <span class={`caption mono ${Math.abs(totalCoCreatorShare - 100) <= 0.01 ? '' : 'style-warn'}`}>
                      {_['co-creators-sum']}: {totalCoCreatorShare}%
                    </span>
                  </div>
                  {coCreationError && (
                    <div class="caption style-warn mt-8">{coCreationError}</div>
                  )}
                </div>
              )}
              <div>
                <label class="label" id="price-model-label">{_['price-model']}</label>
                <div class="row gap-8 mb-8">
                  {(['auto', 'fixed', 'floor'] as const).map(pm => (
                    <button
                      key={pm}
                      class={`btn btn-sm ${priceModel === pm ? 'btn-active' : 'btn-ghost'}`}
                      onClick={() => { setPriceModel(pm); if (pm === 'auto') setManualPrice(''); }}
                    >
                      {_[`price-model-${pm}`]}
                    </button>
                  ))}
                </div>
                <div class="caption mb-8">{_[`price-model-${priceModel}-desc`]}</div>
                {(priceModel === 'fixed' || priceModel === 'floor') && (
                  <input
                    class="input mono"
                    type="number"
                    min="0"
                    step="0.01"
                    value={manualPrice}
                    onInput={e => setManualPrice((e.target as HTMLInputElement).value)}
                    placeholder={priceModel === 'floor' ? _['price-floor-hint'] : _['price-input-hint']}
                  />
                )}
              </div>
            </>
          )}
          <button
            class="btn btn-primary btn-full"
            onClick={submitFile}
            disabled={
              loading
              || owner === 'anonymous'
              || !!coCreationError
              || ((priceModel === 'fixed' || priceModel === 'floor') && !(parseFloat(manualPrice) > 0))
            }
          >
            {loading ? _['protecting'] : _['protect']}
          </button>
        </div>
      )}
    </>
  );
}
