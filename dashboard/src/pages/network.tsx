/**
 * Network — 身份 + 水印工具
 * 风格对齐首页：构成主义极简，留白、线条、块面
 */
import { useEffect, useState } from 'preact/hooks';
import { get, post } from '../api/client';
import { showToast, i18n } from '../store/ui';
import './network.css';

type WmTool = null | 'embed' | 'extract' | 'trace';

export default function Network() {
  const [identity, setIdentity] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  // Watermark tool state
  const [activeTool, setActiveTool] = useState<WmTool>(null);
  const [wmFilePath, setWmFilePath] = useState('');
  const [wmCallerId, setWmCallerId] = useState('');
  const [wmAssetId, setWmAssetId] = useState('');
  const [wmLoading, setWmLoading] = useState(false);
  const [wmResult, setWmResult] = useState<any>(null);

  const _ = i18n.value;

  useEffect(() => {
    get('/identity').then(r => {
      if (r.success && r.data) setIdentity(r.data);
    }).finally(() => setLoading(false));
  }, []);

  const copyText = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    showToast(label + ' ' + _['copied'], 'success');
  };

  const onEmbed = async () => {
    if (!wmFilePath.trim()) return;
    setWmLoading(true);
    setWmResult(null);
    const res = await post<any>('/fingerprint/embed', {
      file_path: wmFilePath.trim(),
      caller_id: wmCallerId.trim() || undefined,
    });
    if (res.success && res.data) {
      setWmResult(res.data);
      showToast(_['wm-embed-btn'] + ' ✓', 'success');
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setWmLoading(false);
  };

  const onExtract = async () => {
    if (!wmFilePath.trim()) return;
    setWmLoading(true);
    setWmResult(null);
    const res = await post<any>('/fingerprint/extract', {
      file_path: wmFilePath.trim(),
    });
    if (res.success && res.data) {
      setWmResult(res.data);
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setWmLoading(false);
  };

  const onTrace = async () => {
    if (!wmAssetId.trim()) return;
    setWmLoading(true);
    setWmResult(null);
    const res = await get<any>(`/fingerprint/distributions?asset_id=${encodeURIComponent(wmAssetId.trim())}`);
    if (res.success && res.data) {
      setWmResult(res.data);
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setWmLoading(false);
  };

  const selectTool = (tool: WmTool) => {
    setActiveTool(activeTool === tool ? null : tool);
    setWmResult(null);
    setWmFilePath('');
    setWmCallerId('');
    setWmAssetId('');
  };

  if (loading) {
    return (
      <div class="page">
        <h1 class="label">{_['network']}</h1>
        <div class="skeleton" style="height:200px" />
      </div>
    );
  }

  return (
    <div class="page">
      <div class="spacer-48" />

      {/* Hero */}
      <div class="net-hero">
        <h1 class="display">
          <span style="color:var(--fg-1)">{_['net-hero-light']}</span>
          <br />
          <strong>{_['net-hero-bold']}</strong>
        </h1>
        <p class="body-text mt-16">{_['net-hero-sub']}</p>
      </div>

      <div class="spacer-48" />

      {/* 身份卡片 */}
      {identity?.public_key ? (
        <div class="card mb-24">
          <div class="label">{_['net-identity']}</div>

          <div class="kv">
            <span class="kv-key">{_['net-node-id']}</span>
            <span class="kv-val mono row gap-8">
              <span>{identity.node_id || identity.public_key.slice(0, 16)}</span>
              <button class="btn-copy" onClick={() => copyText(identity.node_id || identity.public_key.slice(0, 16), 'Node ID')}>{_['copy']}</button>
            </span>
          </div>

          <div class="kv">
            <span class="kv-key">{_['net-pubkey']}</span>
            <span class="kv-val mono row gap-8">
              <span>{'••••' + identity.public_key.slice(-8)}</span>
              <button class="btn-copy" onClick={() => copyText(identity.public_key, _['net-pubkey'])}>{_['copy']}</button>
            </span>
          </div>

          {identity.created_at && (
            <div class="kv">
              <span class="kv-key">{_['net-created']}</span>
              <span class="kv-val">{new Date(identity.created_at * 1000).toLocaleDateString()}</span>
            </div>
          )}
        </div>
      ) : (
        <div class="card mb-24">
          <div class="label">{_['net-identity']}</div>
          <p class="body-text" style="color:var(--fg-2)">
            {_['net-no-identity']}
          </p>
          <p class="caption mt-8">{_['net-init-hint']}</p>
          <button class="btn btn-ghost btn-sm mt-12" onClick={() => {
            setLoading(true);
            get('/identity').then(r => {
              if (r.success && r.data) setIdentity(r.data);
            }).finally(() => setLoading(false));
          }}>
            {_['net-retry']}
          </button>
        </div>
      )}

      {/* 水印工具 */}
      <div class="card mb-24">
        <div class="label">{_['net-watermark']}</div>
        <p class="caption mb-16">{_['net-watermark-desc']}</p>

        <div class="net-tools">
          <button class={`nav-item ${activeTool === 'embed' ? 'nav-item-active' : ''}`} onClick={() => selectTool('embed')}>
            <span class="nav-item-title">{_['net-embed']} {activeTool === 'embed' ? '↓' : '→'}</span>
            <span class="nav-item-desc">{_['net-embed-desc']}</span>
          </button>
          {activeTool === 'embed' && (
            <div class="net-tool-form">
              <input class="input" value={wmFilePath} onInput={e => setWmFilePath((e.target as HTMLInputElement).value)} placeholder={_['wm-file-path']} />
              <input class="input" value={wmCallerId} onInput={e => setWmCallerId((e.target as HTMLInputElement).value)} placeholder={_['wm-caller-id']} />
              <button class="btn btn-primary btn-full" onClick={onEmbed} disabled={wmLoading || !wmFilePath.trim()}>
                {wmLoading ? _['wm-embedding'] : _['wm-embed-btn']}
              </button>
              {wmResult && (
                <div class="net-tool-result">
                  {wmResult.watermarked_path && <div class="kv"><span class="kv-key">{_['wm-watermarked-path']}</span><span class="kv-val mono" style="font-size:11px;word-break:break-all">{wmResult.watermarked_path}</span></div>}
                  {wmResult.fingerprint && <div class="kv"><span class="kv-key">{_['wm-fingerprint']}</span><span class="kv-val mono" style="font-size:11px">{wmResult.fingerprint.slice(0, 16)}…</span></div>}
                </div>
              )}
            </div>
          )}

          <button class={`nav-item ${activeTool === 'extract' ? 'nav-item-active' : ''}`} onClick={() => selectTool('extract')}>
            <span class="nav-item-title">{_['net-extract']} {activeTool === 'extract' ? '↓' : '→'}</span>
            <span class="nav-item-desc">{_['net-extract-desc']}</span>
          </button>
          {activeTool === 'extract' && (
            <div class="net-tool-form">
              <input class="input" value={wmFilePath} onInput={e => setWmFilePath((e.target as HTMLInputElement).value)} placeholder={_['wm-file-path']} />
              <button class="btn btn-primary btn-full" onClick={onExtract} disabled={wmLoading || !wmFilePath.trim()}>
                {wmLoading ? _['wm-extracting'] : _['wm-extract-btn']}
              </button>
              {wmResult && (
                <div class="net-tool-result">
                  {wmResult.fingerprint && <div class="kv"><span class="kv-key">{_['wm-fingerprint']}</span><span class="kv-val mono" style="font-size:11px">{wmResult.fingerprint}</span></div>}
                  {wmResult.caller_id && <div class="kv"><span class="kv-key">{_['wm-caller']}</span><span class="kv-val mono">{wmResult.caller_id}</span></div>}
                  {wmResult.timestamp && <div class="kv"><span class="kv-key">{_['wm-timestamp']}</span><span class="kv-val">{new Date(wmResult.timestamp * 1000).toLocaleString()}</span></div>}
                  {!wmResult.fingerprint && !wmResult.caller_id && <div class="caption" style="color:var(--fg-2)">{_['wm-no-records']}</div>}
                </div>
              )}
            </div>
          )}

          <button class={`nav-item ${activeTool === 'trace' ? 'nav-item-active' : ''}`} onClick={() => selectTool('trace')}>
            <span class="nav-item-title">{_['net-trace']} {activeTool === 'trace' ? '↓' : '→'}</span>
            <span class="nav-item-desc">{_['net-trace-desc']}</span>
          </button>
          {activeTool === 'trace' && (
            <div class="net-tool-form">
              <input class="input" value={wmAssetId} onInput={e => setWmAssetId((e.target as HTMLInputElement).value)} placeholder={_['wm-asset-id']} />
              <button class="btn btn-primary btn-full" onClick={onTrace} disabled={wmLoading || !wmAssetId.trim()}>
                {wmLoading ? _['wm-listing'] : _['wm-list-btn']}
              </button>
              {wmResult && (
                <div class="net-tool-result">
                  {Array.isArray(wmResult.distributions) && wmResult.distributions.length > 0 ? (
                    wmResult.distributions.map((d: any, i: number) => (
                      <div key={i} class="kv">
                        <span class="kv-key mono" style="font-size:11px">{d.caller_id?.slice(0, 12) || '—'}</span>
                        <span class="kv-val">{d.timestamp ? new Date(d.timestamp * 1000).toLocaleString() : '—'}</span>
                      </div>
                    ))
                  ) : (
                    <div class="caption" style="color:var(--fg-2)">{_['wm-no-records']}</div>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
