import { useState } from 'preact/hooks';
import { post } from '../../api/client';
import { showToast, i18n } from '../../store/ui';
import { fmtDate } from '../../utils';
import { Section } from '../section';

export function ContributionSection({ forceOpen }: { forceOpen: boolean }) {
  const [cpFilePath, setCpFilePath] = useState('');
  const [cpCreatorKey, setCpCreatorKey] = useState('');
  const [cpSourceType, setCpSourceType] = useState('manual');
  const [cpProving, setCpProving] = useState(false);
  const [cpResult, setCpResult] = useState<any>(null);
  const [cpCertJson, setCpCertJson] = useState('');
  const [cpVerifyFile, setCpVerifyFile] = useState('');
  const [cpVerifying, setCpVerifying] = useState(false);
  const [cpVerifyResult, setCpVerifyResult] = useState<any>(null);

  const _ = i18n.value;

  return (
    <Section id="contribution" title={_['contribution']} desc={_['contribution-desc']} forceOpen={forceOpen}>
      {/* Generate proof form */}
      <div class="net-tool-form net-tool-form-flush">
        <label class="label" htmlFor="cp-file-path">{_['contribution-file']}</label>
        <input id="cp-file-path" class="input" value={cpFilePath}
          onInput={e => setCpFilePath((e.target as HTMLInputElement).value)}
          placeholder={_['contribution-file']} />
        <label class="label" htmlFor="cp-creator-key">{_['contribution-creator']}</label>
        <input id="cp-creator-key" class="input" value={cpCreatorKey}
          onInput={e => setCpCreatorKey((e.target as HTMLInputElement).value)}
          placeholder={_['contribution-creator']} />
        <label class="label" htmlFor="cp-source-type">{_['contribution-source']}</label>
        <select id="cp-source-type" class="input" value={cpSourceType}
          onChange={e => setCpSourceType((e.target as HTMLSelectElement).value)}>
          <option value="manual">manual</option>
          <option value="tee_capture">tee_capture</option>
          <option value="api_log">api_log</option>
          <option value="sensor_sig">sensor_sig</option>
          <option value="git_commit">git_commit</option>
        </select>
        <button class="btn btn-primary btn-full" disabled={cpProving || !cpFilePath.trim()}
          onClick={async () => {
            setCpProving(true); setCpResult(null);
            const res = await post<any>('/contribution/prove', {
              file_path: cpFilePath.trim(),
              creator_key: cpCreatorKey.trim() || undefined,
              source_type: cpSourceType,
            });
            if (res.success && res.data) {
              setCpResult(res.data);
              showToast(_['contribution-prove-success'], 'success');
            } else {
              showToast(res.error || _['error-generic'], 'error');
            }
            setCpProving(false);
          }}>
          {cpProving ? _['contribution-proving'] : _['contribution-prove']}
        </button>
      </div>

      {cpResult && (
        <div class="net-tool-result mt-12">
          <div class="label-inline mb-8">{_['contribution-result']}</div>
          {cpResult.content_hash && (
            <div class="kv"><span class="kv-key">{_['contribution-content-hash']}</span><span class="kv-val mono kv-val-xs-nowrap">{cpResult.content_hash}</span></div>
          )}
          {cpResult.semantic_fingerprint && (
            <div class="kv"><span class="kv-key">{_['contribution-semantic']}</span><span class="kv-val mono kv-val-xs-nowrap">{cpResult.semantic_fingerprint}</span></div>
          )}
          {cpResult.timestamp && (
            <div class="kv"><span class="kv-key">{_['contribution-timestamp']}</span><span class="kv-val">{fmtDate(cpResult.timestamp)}</span></div>
          )}
        </div>
      )}

      {/* Verify proof form */}
      <div class="net-tool-form net-tool-form-flush mt-16">
        <div class="label-inline mb-8">{_['contribution-verify']}</div>
        <label class="label" htmlFor="cp-cert-json">{_['contribution-certificate']}</label>
        <textarea id="cp-cert-json" class="input" rows={4} value={cpCertJson}
          onInput={e => setCpCertJson((e.target as HTMLTextAreaElement).value)}
          placeholder={_['contribution-certificate']} />
        <label class="label" htmlFor="cp-verify-file">{_['contribution-file']}</label>
        <input id="cp-verify-file" class="input" value={cpVerifyFile}
          onInput={e => setCpVerifyFile((e.target as HTMLInputElement).value)}
          placeholder={_['contribution-file']} />
        <button class="btn btn-primary btn-full" disabled={cpVerifying || !cpCertJson.trim()}
          onClick={async () => {
            setCpVerifying(true); setCpVerifyResult(null);
            let certData: any;
            try { certData = JSON.parse(cpCertJson.trim()); } catch {
              showToast(_['error-invalid-json'], 'error');
              setCpVerifying(false);
              return;
            }
            const res = await post<any>('/contribution/verify', {
              certificate: certData,
              file_path: cpVerifyFile.trim() || undefined,
            });
            if (res.success && res.data) {
              setCpVerifyResult(res.data);
            } else {
              showToast(res.error || _['error-generic'], 'error');
            }
            setCpVerifying(false);
          }}>
          {cpVerifying ? _['contribution-verifying'] : _['contribution-verify']}
        </button>
      </div>

      {cpVerifyResult && (
        <div class="net-tool-result mt-12">
          <div class="kv">
            <span class="kv-key">{_['contribution-result']}</span>
            <span class={`kv-val mono ${cpVerifyResult.valid ? 'color-green' : 'color-red'}`}>
              {cpVerifyResult.valid ? _['contribution-valid'] : _['contribution-invalid']}
            </span>
          </div>
        </div>
      )}
    </Section>
  );
}
