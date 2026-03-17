/**
 * Home — 首页
 * 注册流程直接嵌入，渐进式披露
 */
import { useState, useRef, useEffect } from 'preact/hooks';
import { post, postFile, postBundle } from '../api/client';
import { showToast, i18n } from '../store/ui';
import { loadAssets } from '../store/assets';
import NetworkGrid from '../components/network-grid';
import type { Page } from '../app';
import { readEntryFiles } from '../utils';
import './home.css';

interface Props { go: (p: Page) => void; }

function maskId(id: string) {
  if (!id || id.length <= 8) return id;
  return id.slice(0, 8) + '••••';
}

function baseName(name: string) {
  const dot = name.lastIndexOf('.');
  return dot > 0 ? name.slice(0, dot) : name;
}

type Mode = 'data' | 'capability';

export default function Home({ go }: Props) {
  const [mode, setMode] = useState<Mode>('data');
  const [file, setFile] = useState<File | null>(null);
  const [desc, setDesc] = useState('');
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState<any>(null);
  const [dragging, setDragging] = useState(false);
  const [rightsType, setRightsType] = useState('original');
  const [coCreators, setCoCreators] = useState<{address: string; share: number}[]>([{address: '', share: 50}, {address: '', share: 50}]);

  // Folder state
  const [folderName, setFolderName] = useState<string | null>(null);
  const [folderFiles, setFolderFiles] = useState<File[]>([]);

  // Capability state — 只需要名称和描述，其余有默认值
  const [capName, setCapName] = useState('');
  const [capDesc, setCapDesc] = useState('');

  const ref = useRef<HTMLInputElement>(null);

  const _ = i18n.value;

  // 选中状态：有文件或文件夹
  const hasSelection = !!(file || folderName);

  const clearSelection = () => {
    setFile(null); setDesc('');
    setFolderName(null); setFolderFiles([]);
    setRightsType('original');
    setCoCreators([{address: '', share: 50}, {address: '', share: 50}]);
  };

  const onFile = (f: File) => {
    setFile(f); setDone(null);
    setFolderName(null); setFolderFiles([]);
    if (!desc) setDesc(baseName(f.name));
  };

  const onFolderDetected = (name: string, files: File[]) => {
    setFolderName(name); setFolderFiles(files);
    setFile(null); setDone(null);
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
    setLoading(true);
    const tags = desc.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean).join(',');
    const fields: Record<string, string> = { tags, rights_type: rightsType };
    if (rightsType === 'co_creation') {
      fields.co_creators = JSON.stringify(coCreators.filter(c => c.address.trim()));
    }
    const res = await postFile('/register', file, fields);
    if (res.success) {
      setDone(res.data);
      showToast(_['protected'] + ' ✓', 'success');
      loadAssets(); clearSelection();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  const submitBundle = async () => {
    if (folderFiles.length === 0) return;
    setLoading(true);
    const tags = desc.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean).join(',');
    const res = await postBundle(folderFiles, { name: folderName || 'bundle', tags });
    if (res.success) {
      setDone(res.data);
      showToast(_['protected'] + ' ✓', 'success');
      loadAssets(); clearSelection();
    } else {
      showToast(res.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  const submitCap = async () => {
    if (!capName.trim()) return;
    setLoading(true);
    const res = await post<{ ok?: boolean; capability_id?: string; error?: string }>('/capability/register', {
      name: capName.trim(),
      provider: 'self',
      description: capDesc.trim(),
      tags: capName.split(/[,，\s]+/).map(s => s.trim()).filter(Boolean),
      base_price: 1.0,
    });
    if (res.success && res.data?.ok) {
      setDone({ asset_id: res.data.capability_id, capability: true });
      showToast(_['cap-published'] || '已发布', 'success');
      loadAssets();
      setCapName(''); setCapDesc('');
    } else {
      showToast(res.error || res.data?.error || _['error-generic'], 'error');
    }
    setLoading(false);
  };

  const copyId = () => {
    if (done?.asset_id) {
      navigator.clipboard.writeText(done.asset_id);
      showToast(_['copied'], 'success');
    }
  };

  return (
    <div class="page">
      <div class="spacer-64" />

      {/* Hero */}
      <div class="home-hero">
        <h1 class="display">
          <span class="home-title-light">{_['hero-title-light']}</span>
          <br />
          <strong>{_['hero-title-bold']}</strong>
        </h1>
        <p class="body-text mt-16">{_['hero-sub']}</p>
      </div>

      <div class="spacer-48" />

      <div class="home-grid-wrap">
        <NetworkGrid />
      </div>

      {/* 注册区 */}
      <div class="home-register">
        {!done ? (
          <>
            {/* 模式切换 — 用下划线文字，不用按钮 */}
            <div class="home-mode-switch" role="tablist">
              <button
                role="tab"
                aria-selected={mode === 'data'}
                class={`home-mode-tab ${mode === 'data' ? 'active' : ''}`}
                onClick={() => setMode('data')}
              >
                {_['register-data'] || '注册数据'}
              </button>
              <span class="home-mode-sep" aria-hidden="true">/</span>
              <button
                role="tab"
                aria-selected={mode === 'capability'}
                class={`home-mode-tab ${mode === 'capability' ? 'active' : ''}`}
                onClick={() => setMode('capability')}
              >
                {_['publish-cap'] || '发布能力'}
              </button>
            </div>

            {mode === 'data' ? (
              <>
                {/* Dropzone — 点击选文件，拖入支持文件夹 */}
                <div
                  class={`dropzone ${dragging ? 'dropzone-active' : ''} ${hasSelection ? 'dropzone-done' : ''}`}
                  onDrop={onDrop}
                  onDragOver={e => { e.preventDefault(); setDragging(true); }}
                  onDragLeave={() => setDragging(false)}
                  onClick={() => { if (!hasSelection) ref.current?.click(); }}
                >
                  {hasSelection ? (
                    <div class="dropzone-selected">
                      <span class="dropzone-selected-name">
                        {folderName ? `${folderName}/` : file!.name}
                      </span>
                      {folderName && (
                        <span class="caption">{folderFiles.length} {_['files'] || '个文件'}</span>
                      )}
                      <button
                        class="dropzone-clear"
                        onClick={e => { e.stopPropagation(); clearSelection(); }}
                        aria-label="clear"
                      >×</button>
                    </div>
                  ) : (
                    <>
                      <div class="dropzone-icon">↑</div>
                      <div class="dropzone-text">
                        <strong>{_['drop-browse'] || '选择文件'}</strong>
                      </div>
                      <div class="caption" style="margin-top:6px">
                        {_['drop-folder-hint'] || '支持拖入文件夹'}
                      </div>
                    </>
                  )}
                  <input ref={ref} type="file" style="display:none" onChange={e => {
                    const f = (e.target as HTMLInputElement).files?.[0];
                    if (f) onFile(f);
                  }} />
                </div>

                {/* 注册表单 — 文件夹 */}
                {folderName && (
                  <div class="home-fields">
                    <div>
                      <label class="label">{_['describe']}</label>
                      <input class="input" value={desc}
                        onInput={e => setDesc((e.target as HTMLInputElement).value)}
                        placeholder={folderName} />
                    </div>
                    <button class="btn btn-primary btn-full" onClick={submitBundle} disabled={loading}>
                      {loading ? _['protecting'] : _['protect']}
                    </button>
                  </div>
                )}

                {/* 注册表单 — 单文件 */}
                {file && (
                  <div class="home-fields">
                    <div>
                      <label class="label">{_['describe']}</label>
                      <input class="input" value={desc}
                        onInput={e => setDesc((e.target as HTMLInputElement).value)}
                        placeholder={_['describe-hint']} />
                    </div>
                    <div>
                      <label class="label">{_['rights-type']}</label>
                      <select class="input" value={rightsType} onChange={e => setRightsType((e.target as HTMLSelectElement).value)}>
                        <option value="original">{_['rights-original']}</option>
                        <option value="co_creation">{_['rights-co_creation']}</option>
                        <option value="licensed">{_['rights-licensed']}</option>
                        <option value="collection">{_['rights-collection']}</option>
                      </select>
                    </div>
                    {rightsType === 'co_creation' && (
                      <div>
                        <label class="label">{_['co-creators']}</label>
                        <div class="caption" style="margin-bottom:8px">{_['co-creators-hint']}</div>
                        {coCreators.map((c, i) => (
                          <div key={i} class="row gap-8" style="margin-bottom:6px">
                            <input class="input" style="flex:2" placeholder={_['co-creator-address']} value={c.address}
                              onInput={e => { const v = [...coCreators]; v[i] = {...v[i], address: (e.target as HTMLInputElement).value}; setCoCreators(v); }} />
                            <input class="input" style="flex:1;max-width:80px" type="number" placeholder="%" value={c.share}
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
                          <span class={`caption mono ${coCreators.reduce((s, c) => s + c.share, 0) === 100 ? '' : 'style-warn'}`}>
                            {_['co-creators-sum']}: {coCreators.reduce((s, c) => s + c.share, 0)}%
                          </span>
                        </div>
                      </div>
                    )}
                    <button class="btn btn-primary btn-full" onClick={submitFile} disabled={loading}>
                      {loading ? _['protecting'] : _['protect']}
                    </button>
                  </div>
                )}
              </>
            ) : (
              /* ── 发布能力 — 极简表单 ── */
              <div class="home-fields">
                <div class="caption" style="margin-bottom:4px">
                  {_['cap-guide'] || '将你的 AI 能力发布到网络，其他人可以发现和调用。'}
                </div>
                <div>
                  <label class="label">{_['cap-name'] || '名称'}</label>
                  <input class="input" value={capName}
                    onInput={e => setCapName((e.target as HTMLInputElement).value)}
                    placeholder={_['cap-name-hint'] || '例如：图像风格迁移'} />
                </div>
                <div>
                  <label class="label">{_['describe']}</label>
                  <input class="input" value={capDesc}
                    onInput={e => setCapDesc((e.target as HTMLInputElement).value)}
                    placeholder={_['cap-desc-hint'] || '输入图片，输出指定风格的新图片'} />
                  <div class="caption" style="margin-top:4px">
                    {_['cap-desc-guide'] || '描述输入输出，帮助别人理解如何使用'}
                  </div>
                </div>
                <button class="btn btn-primary btn-full" onClick={submitCap} disabled={loading || !capName.trim()}>
                  {loading ? _['protecting'] : (_['publish-cap'] || '发布能力')}
                </button>
              </div>
            )}
          </>
        ) : (
          <div class="home-success">
            <div class="home-success-icon">✓</div>
            <div class="home-success-title">
              {done.capability ? (_['cap-published'] || '能力已发布') : _['protected']}
            </div>
            {done.file_count && (
              <div class="caption mb-8">
                {done.file_count} {_['files-bundled'] || '个文件已打包注册'}
              </div>
            )}
            <div class="home-success-detail">
              <div class="kv">
                <span class="kv-key">{_['id']}</span>
                <span class="kv-val">
                  <span class="masked">
                    <span>{maskId(done.asset_id)}</span>
                    <button class="btn-copy" onClick={copyId}>{_['copy']}</button>
                  </span>
                </span>
              </div>
              {done.spot_price != null && (
                <div class="kv">
                  <span class="kv-key">{_['spot-price'] || '起始价'}</span>
                  <span class="kv-val">{done.spot_price >= 1 ? done.spot_price.toFixed(2) : done.spot_price.toFixed(4)} OAS</span>
                </div>
              )}
              {done.rights_type && (
                <div class="kv">
                  <span class="kv-key">{_['rights-type']}</span>
                  <span class="kv-val">{_[`rights-${done.rights_type}`] || done.rights_type}</span>
                </div>
              )}
              {done.fingerprint && (
                <div class="kv">
                  <span class="kv-key">{_['wm-fingerprint'] || '指纹'}</span>
                  <span class="kv-val mono" style="font-size:11px">{done.fingerprint.slice(0, 12)}…</span>
                </div>
              )}
            </div>
            <div class="row gap-8 mt-16" style="justify-content:center">
              <button class="btn btn-ghost btn-sm" onClick={() => go('mydata')}>{_['view-mydata']} →</button>
              <button class="btn btn-ghost btn-sm" onClick={() => setDone(null)}>{_['again']}</button>
            </div>
          </div>
        )}
      </div>

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
