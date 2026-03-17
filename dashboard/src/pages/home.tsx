/**
 * Home — 首页
 * 注册流程直接嵌入，渐进式披露
 */
import { useState, useRef } from 'preact/hooks';
import { postFile } from '../api/client';
import { showToast, i18n } from '../store/ui';
import { loadAssets } from '../store/assets';
import NetworkGrid from '../components/network-grid';
import type { Page } from '../app';
import './home.css';

interface Props { go: (p: Page) => void; }

/** 遮罩 asset_id：前8位 + •••• */
function maskId(id: string) {
  if (!id || id.length <= 8) return id;
  return id.slice(0, 8) + '••••';
}

export default function Home({ go }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [desc, setDesc] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState<any>(null);
  const [dragging, setDragging] = useState(false);
  const ref = useRef<HTMLInputElement>(null);

  const _ = i18n.value;

  const onFile = (f: File) => {
    setFile(f); setDone(null);
    const ext = f.name.split('.').pop()?.toLowerCase() || '';
    const hint: Record<string, string> = {
      csv: 'dataset', json: 'structured data', jpg: 'image', png: 'image',
      pdf: 'document', mp4: 'video', mp3: 'audio', txt: 'text',
    };
    if (hint[ext] && !desc) setDesc(hint[ext]);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault(); setDragging(false);
    const f = e.dataTransfer?.files[0];
    if (f) onFile(f);
  };

  const copyId = () => {
    if (done?.asset_id) {
      navigator.clipboard.writeText(done.asset_id);
      showToast(_['copied'], 'success');
    }
  };

  const submit = async () => {
    if (!file) return;
    setLoading(true);
    const tags = desc.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean).join(',');
    const res = await postFile('/register', file, { tags });
    if (res.success) {
      setDone(res.data);
      showToast(_['protected'] + ' ✓', 'success');
      loadAssets();
      setFile(null); setDesc('');
    } else {
      showToast(res.error || 'Failed', 'error');
    }
    setLoading(false);
  };

  return (
    <div class="page">
      {/* 64px 顶部留白 */}
      <div class="spacer-64" />

      {/* Hero: 两行分开渲染 */}
      <div class="home-hero">
        <h1 class="display">
          <span class="home-title-light">{_['hero-title-light']}</span>
          <br />
          <strong>{_['hero-title-bold']}</strong>
        </h1>
        <p class="body-text mt-16">{_['hero-sub']}</p>
      </div>

      {/* 48px 间距 */}
      <div class="spacer-48" />

      {/* 网络可视化 */}
      <div class="home-grid-wrap">
        <NetworkGrid />
      </div>

      {/* 注册区 */}
      <div class="home-register">
        {!done ? (
          <>
            <div
              class={`dropzone ${dragging ? 'dropzone-active' : ''} ${file ? 'dropzone-done' : ''}`}
              onDrop={onDrop}
              onDragOver={e => { e.preventDefault(); setDragging(true); }}
              onDragLeave={() => setDragging(false)}
              onClick={() => ref.current?.click()}
            >
              {file ? (
                <div class="dropzone-text"><strong>{file.name}</strong></div>
              ) : (
                <>
                  <div class="dropzone-icon">↑</div>
                  <div class="dropzone-text">
                    {_['drop-hint']}
                    {' '}
                    <strong>{_['drop-browse']}</strong>
                  </div>
                </>
              )}
              <input ref={ref} type="file" style="display:none" onChange={e => {
                const f = (e.target as HTMLInputElement).files?.[0];
                if (f) onFile(f);
              }} />
            </div>

            {/* 选文件后 16px 间距出现描述字段 → 16px 间距出现按钮 */}
            {file && (
              <div class="home-fields">
                <div>
                  <label class="label">{_['describe']}</label>
                  <input class="input" value={desc} onInput={e => setDesc((e.target as HTMLInputElement).value)} placeholder={_['describe-hint']} />
                </div>
                <button class="btn btn-primary btn-full" onClick={submit} disabled={loading}>
                  {loading ? _['protecting'] : _['protect']}
                </button>
              </div>
            )}
          </>
        ) : (
          <div class="home-success">
            <div class="home-success-icon">✓</div>
            <div class="home-success-title">{_['protected']}</div>
            <div class="masked">
              <span>{maskId(done.asset_id)}</span>
              <button class="btn-copy" onClick={copyId}>{_['copy']}</button>
            </div>
            <div class="row gap-8" style="margin-top:16px;justify-content:center">
              <button class="btn btn-ghost btn-sm" onClick={() => go('mydata')}>{_['view-mydata']} →</button>
              <button class="btn btn-ghost btn-sm" onClick={() => setDone(null)}>{_['again']}</button>
            </div>
          </div>
        )}
      </div>

      {/* 间距 */}
      <div class="spacer-48" />

      {/* 底部导航 */}
      <div class="home-nav">
        <button class="nav-row" onClick={() => go('mydata')}>
          <span class="nav-row-title">{_['nav-mydata']} →</span>
          <span class="nav-row-desc">{_['nav-mydata-desc']}</span>
        </button>
        <button class="nav-row" onClick={() => go('explore')}>
          <span class="nav-row-title">{_['nav-explore']} →</span>
          <span class="nav-row-desc">{_['nav-explore-desc']}</span>
        </button>
        <button class="nav-row" onClick={() => go('network')}>
          <span class="nav-row-title">{_['nav-network']} →</span>
          <span class="nav-row-desc">{_['nav-network-desc']}</span>
        </button>
      </div>
    </div>
  );
}
