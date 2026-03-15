/**
 * Network — 网络状态
 * 小白看到数字和身份，极客折叠看详情
 */
import { useEffect, useState } from 'preact/hooks';
import { get } from '../api/client';
import { showToast, i18n } from '../store/ui';
import './network.css';

/** 公钥：•••• + 后4位 */
function maskKey(key: string) {
  if (!key || key.length <= 4) return key;
  return '••••' + key.slice(-4);
}

/** Node ID：遮罩显示前8位 + •••• */
function maskNodeId(id: string) {
  if (!id || id.length <= 8) return id;
  return id.slice(0, 8) + '••••';
}

export default function Network() {
  const [status, setStatus] = useState<any>(null);
  const [config, setConfig] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [showDetail, setShowDetail] = useState(false);

  const _ = i18n.value;

  useEffect(() => {
    Promise.all([
      get('/status').then(r => { if (r.success) setStatus(r.data); }),
      get('/config').then(r => { if (r.success) setConfig(r.data); }),
    ]).finally(() => setLoading(false));
  }, []);

  const copyText = (text: string) => {
    navigator.clipboard.writeText(text);
    showToast(_['copied'], 'success');
  };

  if (loading) {
    return (
      <div class="page">
        <h1 class="heading">{_['network']}</h1>
        <div class="col gap-16">
          <div class="skeleton" style="height:80px"></div>
          <div class="skeleton" style="height:80px"></div>
        </div>
      </div>
    );
  }

  return (
    <div class="page">
      {/* Label 标题 */}
      <h1 class="heading">{_['network']}</h1>

      {/* 统计数字（水平排列，竖线分隔） */}
      {status && (
        <div class="net-stats mb-48">
          <div class="stat">
            <div class="stat-value">{status.total_assets}</div>
            <div class="stat-label">assets</div>
          </div>
          <div class="net-line" />
          <div class="stat">
            <div class="stat-value">{status.total_blocks}</div>
            <div class="stat-label">blocks</div>
          </div>
          <div class="net-line" />
          <div class="stat">
            <div class="stat-value">{status.total_distributions}</div>
            <div class="stat-label">watermarks</div>
          </div>
        </div>
      )}

      {/* 身份区：遮罩公钥 + 复制按钮 + caption 说明 */}
      <div class="label">{_['identity']}</div>
      {config?.public_key ? (
        <div class="mb-48">
          <div class="row gap-8 mb-8">
            <span class="masked">{maskKey(config.public_key)}</span>
            <button class="btn-copy" onClick={() => copyText(config.public_key)}>{_['copy']}</button>
          </div>
          <div class="caption">{_['identity-hint']}</div>
        </div>
      ) : (
        <div class="mb-48 caption">{_['no-key']}</div>
      )}

      {/* 48px section-rule */}
      <hr class="section-rule" />

      {/* 详细信息（折叠）: Node ID（遮罩）、Address */}
      {status && (
        <>
          <button class="nav-row" onClick={() => setShowDetail(!showDetail)} style="border-bottom:none">
            <span class="nav-row-title">{_['advanced']} {showDetail ? '↑' : '→'}</span>
          </button>
          {showDetail && (
            <div style="animation:field-in 0.2s var(--ease)">
              <div class="kv">
                <span class="kv-key">Node ID</span>
                <span class="kv-val">
                  <span class="masked">
                    <span>{maskNodeId(status.node_id)}</span>
                    <button class="btn-copy" onClick={() => copyText(status.node_id)}>{_['copy']}</button>
                  </span>
                </span>
              </div>
              <div class="kv"><span class="kv-key">Address</span><span class="kv-val">{status.host}:{status.port}</span></div>
              {status.chain_height != null && <div class="kv"><span class="kv-key">Chain Height</span><span class="kv-val">{status.chain_height}</span></div>}
            </div>
          )}
        </>
      )}
    </div>
  );
}
