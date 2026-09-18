import {useState} from 'react';

type Value = Record<string, any>;
type Request = (path: string, init?: RequestInit) => Promise<any>;
const KIND: Record<string, string> = {text: '文本', image: '图片', video: '视频', audio: '语音'};

function ProviderCard({preset, request, onSaved}: {preset: Value; request: Request; onSaved: () => Promise<void>}) {
  const [key, setKey] = useState('');
  const [useDefaults, setUseDefaults] = useState(!preset.configured);
  const [publicUrl, setPublicUrl] = useState(preset.public_base_url || '');
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [notice, setNotice] = useState('');
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setError(''); setNotice('');
    try {
      const body: Value = {revision: preset.revision, use_defaults: useDefaults};
      if (key.trim()) body.api_key = key.trim();
      if (preset.id === 'hc') body.public_base_url = publicUrl.trim();
      const result = await request(`/admin/provider-presets/${preset.id}`, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
      });
      setKey(''); setUseDefaults(false); setNotice(result.message);
      await onSaved();
    } catch (e: any) {setError(e.message || '保存失败，请重试');}
    finally {setBusy(false);}
  }
  const blocked = preset.conflicts?.length > 0;
  return <form className="provider-setup-card" aria-label={`${preset.name} 配置`} onSubmit={save}>
    <div className="provider-card-heading"><h3>{preset.name}</h3>
      <span className={preset.configured ? 'provider-badge configured' : 'provider-badge'}>{preset.configured ? 'Key 已保存' : '待填写 Key'}</span>
    </div>
    <p className="muted">{preset.description}</p>
    <ul className="provider-preset-models">{preset.models.map((model: Value) => <li key={model.id}>
      <span className="model-kind">{KIND[model.kind]}</span><span>{model.name.split(' · ').slice(1).join(' · ') || model.name}</span>
      {model.is_default ? <small>当前默认</small> : !model.primary ? <small>可选</small> : null}
    </li>)}</ul>
    {preset.id === 'speech' && <p className="provider-footnote">默认音色：Vivi（zh_female_vv_uranus_bigtts），MP3 · 24 kHz。</p>}
    <label>{preset.name} API Key
      <input type="password" autoComplete="new-password" spellCheck={false} value={key}
        required={!preset.configured} disabled={busy || blocked}
        placeholder={preset.configured ? '已保存；留空保留，填写则替换' : '粘贴你的 API Key'}
        onChange={e => setKey(e.target.value)}/>
    </label>
    <label className="checkbox"><input type="checkbox" checked={useDefaults} disabled={busy || blocked}
      onChange={e => setUseDefaults(e.target.checked)}/>同时设为对应用途的默认模型</label>
    <p className="provider-footnote">勾选后，同用途以最后一次保存为默认；不改变已有作品的模型选择。不勾选也会添加模型供选择。</p>
    {preset.id === 'hc' && <details><summary>参考素材设置</summary>
      <label>平台的素材公网访问地址<input type="url" value={publicUrl} disabled={busy}
        placeholder="https://你的平台域名" onChange={e => setPublicUrl(e.target.value)}/></label>
      <p className="provider-footnote">幻场读取本地参考图片、音频时需要可访问的平台地址。没有公网地址时先留空，不影响保存 Key。</p>
    </details>}
    <button className="primary" type="submit" disabled={busy || blocked}>{busy ? '正在保存…' : preset.configured ? '保存配置' : '保存 Key 并配置模型'}</button>
    {blocked && <p role="alert" className="error">{preset.conflicts.join(' ')}</p>}
    {error && <p role="alert" className="error">{error} <button type="button" disabled={busy} onClick={() => void onSaved().catch(() => setError('刷新失败，请稍后重试'))}>刷新配置后重试</button></p>}
    {notice && <p role="status" className="notice">{notice}</p>}
  </form>;
}

export function ProviderSetupCards({presets, request, onSaved}: {presets: Value[]; request: Request; onSaved: () => Promise<void>}) {
  return <div className="provider-setup-grid">{presets.map(preset =>
    <ProviderCard key={preset.id} preset={preset} request={request} onSaved={onSaved}/>)}</div>;
}
