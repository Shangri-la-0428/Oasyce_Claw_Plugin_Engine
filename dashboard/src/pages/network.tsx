/**
 * Network — 身份 + 水印工具
 * 风格对齐首页：构成主义极简，留白、线条、块面
 */
import { useEffect, useState } from 'preact/hooks';
import { get } from '../api/client';
import { showToast, i18n } from '../store/ui';
import './network.css';

export default function Network() {
  const [identity, setIdentity] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  const _ = i18n.value;

  useEffect(() => {
    get('/identity').then(r => {
      if (r.success && r.data) setIdentity(r.data);
    }).finally(() => setLoading(false));
  }, []);

  const copyText = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    showToast(label + ' ' + (_['copied'] || '已复制'), 'success');
  };

  if (loading) {
    return (
      <div class="page">
        <h1 class="heading">{_['network']}</h1>
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
          <span style="color:var(--fg-1)">{_['net-hero-light'] || '你的'}</span>
          <br />
          <strong>{_['net-hero-bold'] || '网络身份'}</strong>
        </h1>
        <p class="body-text mt-16">{_['net-hero-sub'] || '所有注册与交易都用此身份签名'}</p>
      </div>

      <div class="spacer-48" />

      {/* 身份卡片 */}
      {identity?.public_key ? (
        <div class="card mb-24">
          <div class="label">{_['net-identity'] || 'IDENTITY'}</div>

          <div class="kv">
            <span class="kv-key">{_['net-node-id'] || '节点 ID'}</span>
            <span class="kv-val mono row gap-8">
              <span>{identity.node_id || identity.public_key.slice(0, 16)}</span>
              <button class="btn-copy" onClick={() => copyText(identity.node_id || identity.public_key.slice(0, 16), 'Node ID')}>{_['copy'] || '复制'}</button>
            </span>
          </div>

          <div class="kv">
            <span class="kv-key">{_['net-pubkey'] || '公钥'}</span>
            <span class="kv-val mono row gap-8">
              <span>{'••••' + identity.public_key.slice(-8)}</span>
              <button class="btn-copy" onClick={() => copyText(identity.public_key, _['net-pubkey'] || '公钥')}>{_['copy'] || '复制'}</button>
            </span>
          </div>

          {identity.created_at && (
            <div class="kv">
              <span class="kv-key">{_['net-created'] || '创建时间'}</span>
              <span class="kv-val">{new Date(identity.created_at * 1000).toLocaleDateString()}</span>
            </div>
          )}
        </div>
      ) : (
        <div class="card mb-24">
          <div class="label">{_['net-identity'] || 'IDENTITY'}</div>
          <p class="body-text" style="color:var(--yellow)">
            {_['net-no-identity'] || '尚未生成身份'}
            <br />
            <span class="caption">{_['net-init-hint'] || '运行 oasyce start 来初始化节点'}</span>
          </p>
        </div>
      )}

      {/* 水印工具 */}
      <div class="card mb-24">
        <div class="label">{_['net-watermark'] || 'WATERMARK TOOLS'}</div>
        <p class="caption mb-16">{_['net-watermark-desc'] || '追踪数据在网络中的流转'}</p>

        <div class="net-tools">
          <button class="nav-item">
            <span class="nav-item-title">{_['net-embed'] || '嵌入水印'} →</span>
            <span class="nav-item-desc">{_['net-embed-desc'] || '把身份信息刻进文件'}</span>
          </button>
          <button class="nav-item">
            <span class="nav-item-title">{_['net-extract'] || '提取水印'} →</span>
            <span class="nav-item-desc">{_['net-extract-desc'] || '读出文件的签名信息'}</span>
          </button>
          <button class="nav-item">
            <span class="nav-item-title">{_['net-trace'] || '追踪分发'} →</span>
            <span class="nav-item-desc">{_['net-trace-desc'] || '查看文件的流转记录'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
