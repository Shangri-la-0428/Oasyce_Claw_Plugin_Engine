/**
 * DataPreview — shows asset preview based on access level (L0-L3)
 */
import { useState, useEffect, useRef } from 'preact/hooks';
import { useEscapeKey } from '../hooks/useEscapeKey';
import { get } from '../api/client';
import { i18n, showToast } from '../store/ui';
import { fmtPrice, fmtDate } from '../utils';

interface PreviewData {
  asset_id: string;
  level: string;
  asset_type: string;
  metadata: {
    name?: string;
    tags?: string[];
    size?: number;
    rights_type?: string;
    created_at?: number;
    owner?: string;
    provider?: string;
    description?: string;
  };
  content_type?: string;
  content?: string | string[];
  truncated?: boolean;
  full_access?: boolean;
  detail?: any;
}

interface Props {
  assetId: string;
  onClose: () => void;
}

export default function DataPreview({ assetId, onClose }: Props) {
  const [preview, setPreview] = useState<PreviewData | null>(null);
  const [loading, setLoading] = useState(false);
  const [level, setLevel] = useState('L0');
  const genRef = useRef(0);
  const _ = i18n.value;

  useEscapeKey(onClose);

  const loadPreview = async (lvl: string) => {
    const gen = ++genRef.current;
    setLoading(true);
    setLevel(lvl);
    const res = await get<PreviewData>(`/asset/${assetId}/preview?level=${lvl}`);
    if (gen !== genRef.current) return; // stale response
    if (res.success && res.data) {
      setPreview(res.data);
    } else if (!res.success) {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  // Auto-load L0 on mount
  useEffect(() => {
    loadPreview('L0');
    return () => { genRef.current++; };
  }, [assetId]);

  const formatSize = (bytes?: number) => {
    if (!bytes) return '-';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const renderContent = () => {
    if (!preview || level === 'L0') return null;
    if (preview.content_type === 'csv' && Array.isArray(preview.content)) {
      const rows = preview.content.map(line => line.split(','));
      return (
        <div class="preview-table-wrap">
          <table class="preview-table">
            {rows.length > 0 && (
              <thead>
                <tr>{rows[0].map((cell, i) => <th key={i}>{cell}</th>)}</tr>
              </thead>
            )}
            <tbody>
              {rows.slice(1).map((row, ri) => (
                <tr key={ri}>{row.map((cell, ci) => <td key={ci}>{cell}</td>)}</tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    }
    if (preview.content_type === 'text' && typeof preview.content === 'string') {
      return (
        <div class="preview-code-wrap">
          <pre class="preview-code">{preview.content}</pre>
          {preview.truncated && <div class="preview-truncated">{_['preview-truncated']}</div>}
        </div>
      );
    }
    if (typeof preview.content === 'string') {
      return <div class="preview-info">{preview.content}</div>;
    }
    return null;
  };

  return (
    <div class="preview-panel">
      <div class="preview-header">
        <span class="preview-title">{_['preview']}</span>
        <button class="btn btn-sm btn-ghost" onClick={onClose} aria-label={_['close']}>&times;</button>
      </div>

      {loading ? (
        <div class="preview-loading">{_['preview-loading']}</div>
      ) : preview ? (
        <div class="preview-body">
          {/* Metadata (always shown) */}
          <div class="preview-section">
            <div class="preview-section-title">{_['preview-metadata']}</div>
            <div class="kv"><span class="kv-key">{_['id']}</span><span class="kv-val mono">{preview.asset_id.slice(0, 16)}...</span></div>
            {preview.metadata.name && <div class="kv"><span class="kv-key">{_['edit-name']}</span><span class="kv-val">{preview.metadata.name}</span></div>}
            {preview.metadata.tags && preview.metadata.tags.length > 0 && (
              <div class="kv"><span class="kv-key">{_['tags']}</span><span class="kv-val">{preview.metadata.tags.join(', ')}</span></div>
            )}
            <div class="kv"><span class="kv-key">{_['rights-type']}</span><span class="kv-val">{preview.metadata.rights_type || 'original'}</span></div>
            <div class="kv"><span class="kv-key">{_['preview-size']}</span><span class="kv-val">{formatSize(preview.metadata.size)}</span></div>
            <div class="kv"><span class="kv-key">{_['created-at']}</span><span class="kv-val">{fmtDate(preview.metadata.created_at, 'date')}</span></div>
          </div>

          {/* Level selector */}
          <div class="preview-levels">
            {['L0', 'L1', 'L2', 'L3'].map(l => (
              <button
                key={l}
                class={`btn btn-sm ${level === l ? 'btn-active' : 'btn-ghost'}`}
                onClick={() => loadPreview(l)}
              >
                {l}
              </button>
            ))}
          </div>

          {/* Content preview */}
          {level !== 'L0' && (
            <div class="preview-section">
              <div class="preview-section-title">{_['preview-content']}</div>
              {renderContent()}
            </div>
          )}

          {/* Lock indicator for higher levels */}
          {level === 'L0' && (
            <div class="preview-locked">
              <span class="preview-lock-icon">&#x1F512;</span>
              <span>{_['preview-locked']}</span>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}
