import {useEffect, useState} from 'react';
import './platformModels.css';

type Value = Record<string, any>;
type Request = (path: string, init?: RequestInit) => Promise<any>;
const send = (method: string, body?: Value): RequestInit => ({
  method, headers: {'Content-Type': 'application/json'},
  ...(body === undefined ? {} : {body: JSON.stringify(body)}),
});
const encode = encodeURIComponent;
const TYPES = ['openai', 'volcengine_ark', 'volcengine_speech', 'runninghub', 'hc_atom', 'replicate', 'minimax', 'comfy', 'maestro', 'video_api'];
const nativeAnonymous = (type: string) => type === 'maestro' || type === 'comfy';
const emptyProvider = () => ({id: '', revision: 0, name: '', enabled: true,
  config: {type: 'openai', url: '', auth_mode: 'api_key'}});
const emptyModel = () => ({id: '', revision: 0, provider_id: '', kind: 'text', published: false, enabled: true,
  definition: {name: '', upstream_model: ''}});

function parseObject(raw: string, label: string) {
  let value: unknown;
  try {value = JSON.parse(raw);} catch {throw new Error(`${label}必须是有效 JSON 对象`);}
  if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error(`${label}必须是 JSON 对象`);
  return value;
}

export function PlatformModels({request}: {request: Request}) {
  const [providers, setProviders] = useState<Value[]>([]), [models, setModels] = useState<Value[]>([]);
  const [defaults, setDefaults] = useState<Value>({}), [keyStatus, setKeyStatus] = useState('');
  const [provider, setProvider] = useState<Value>(emptyProvider), [model, setModel] = useState<Value>(emptyModel);
  const [key, setKey] = useState(''), [replaceKey, setReplaceKey] = useState(true), [options, setOptions] = useState('{}');
  const [caps, setCaps] = useState('{}'), [params, setParams] = useState('{}'), [rules, setRules] = useState('{}');
  const [isDefault, setIsDefault] = useState(false), [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(''), [error, setError] = useState(''), [revokeId, setRevokeId] = useState('');
  async function load() {
    const [p, m] = await Promise.all([request('/admin/model-providers'), request('/admin/models')]);
    setProviders(p.providers); setKeyStatus(p.key_service); setModels(m.models); setDefaults(m.defaults);
  }
  useEffect(() => {void load().catch(e => setError(e.message));}, []);
  async function act(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try {await action(); await load();} catch (e: any) {setError(e.message || '操作失败');}
    finally {setBusy(false);}
  }
  function selectProvider(value: Value) {
    setProvider(value); setKey(''); setReplaceKey(!value.id); setRevokeId('');
    setOptions(JSON.stringify(value.config.options || {}, null, 2));
  }
  function selectModel(value: Value) {
    setModel(value); setIsDefault(defaults[value.kind] === value.id && Boolean(value.id));
    setCaps(JSON.stringify(value.definition.capabilities || {}, null, 2));
    setParams(JSON.stringify(value.definition.defaults || {}, null, 2));
    setRules(JSON.stringify(value.definition.rules || {}, null, 2));
  }
  return <section className="platform-models" aria-label="平台模型配置">
    <h2>平台模型与服务</h2>
    <p>仅平台管理员配置服务与 Key。普通成员只使用已发布模型。保存和检查不会发起生成。</p>
    {keyStatus === 'unavailable' && <p className="error">模型密钥服务未就绪：首次保存需要部署 OVC_PROVIDER_MASTER_KEY；已有配置请核对主密钥。账号管理不受影响。</p>}
    {error && <div role="alert" className="error">{error}</div>}
    {notice && <div role="status" className="notice">{notice}</div>}
    <div className="platform-model-grid">
      <div>
        <h3>Provider 与凭证</h3>
        <div className="admin-list">{providers.map(p => <div key={p.id}>
          <span><b>{p.name}</b><small>{p.enabled ? '启用' : '停用'} · 版本 {p.revision} · {p.api_key_set ? '凭证已配置' : '凭证不可用'}</small></span>
          <button disabled={busy} onClick={() => selectProvider(p)}>编辑 {p.name}</button>
        </div>)}</div>
        <button disabled={busy} onClick={() => selectProvider(emptyProvider())}>新建 Provider</button>
        <form onSubmit={e => {e.preventDefault(); void act(async () => {
          const body: Value = {revision: provider.revision, name: provider.name, enabled: provider.enabled,
            config: {...provider.config, options: parseObject(options, '协议选项')}};
          if (replaceKey || !provider.id) body.api_key = key;
          const result = await request('/admin/model-providers' + (provider.id ? '/' + encode(provider.id) : ''), send(provider.id ? 'PUT' : 'POST', body));
          selectProvider(result); setNotice('Provider 已保存；Key 不回显。上游鉴权与实际生成尚未验证。');
        });}}>
          <label>服务名称<input required maxLength={100} value={provider.name} onChange={e => setProvider({...provider, name: e.target.value})}/></label>
          <label>协议类型<select value={provider.config.type} onChange={e => {
            setReplaceKey(true); setKey('');
            setProvider({...provider, config: {...provider.config, type: e.target.value,
              auth_mode: nativeAnonymous(e.target.value) ? 'none' : 'api_key'}});
          }}>
            {TYPES.map(type => <option key={type}>{type}</option>)}
          </select></label>
          <label>服务基础地址<input required type="url" placeholder="https://api.example.com/v1" value={provider.config.url} onChange={e => setProvider({...provider, config: {...provider.config, url: e.target.value}})}/></label>
          <label>认证方式<select value={provider.config.auth_mode || 'api_key'} onChange={e => {setReplaceKey(true); setKey(''); setProvider({...provider, config: {...provider.config, auth_mode: e.target.value}});}}>
            <option value="api_key" disabled={nativeAnonymous(provider.config.type)}>API Key</option><option value="none">无认证（仅明确支持的私有服务）</option>
          </select></label>
          {nativeAnonymous(provider.config.type) && <p className="muted">当前 Maestro/Comfy 仅接通无认证 API；不接受 API Key。私有地址仍需部署精确出站例外，旧 Key 模式必须显式改为无认证后保存。</p>}
          {provider.id && <label className="checkbox"><input type="checkbox" checked={replaceKey} onChange={e => {setReplaceKey(e.target.checked); setKey('');}}/>替换 Key（不选则保持原凭证）</label>}
          {(replaceKey || !provider.id) && provider.config.auth_mode !== 'none' && <label>新 API Key<input type="password" autoComplete="off" required value={key} onChange={e => setKey(e.target.value)}/></label>}
          <label className="checkbox"><input type="checkbox" checked={provider.enabled} onChange={e => setProvider({...provider, enabled: e.target.checked})}/>启用新调用</label>
          <details><summary>非秘密协议选项（JSON）</summary><p>保留现有适配器的 parameters、workflow、resource_id 等配置；不得填入 Key 或认证 headers。</p><textarea aria-label="Provider 非秘密选项" rows={6} value={options} onChange={e => setOptions(e.target.value)}/></details>
          <button className="primary" disabled={busy} type="submit">保存 Provider</button>
          {provider.id && <button disabled={busy} type="button" onClick={() => void act(async () => {
            const result = await request(`/admin/model-providers/${encode(provider.id)}/check`, send('POST'));
            setNotice(result.message);
          })}>检查已保存配置（不生成）</button>}
        </form>
        {provider.credentials?.length > 0 && <details><summary>凭证版本与吊销</summary>
          <p>正常轮换保留旧任务原凭证。吊销会阻止旧任务查询，不会替换账号或重新生成。</p>
          {provider.credentials.map((credential: Value) => <div className="credential-row" key={credential.id}>
            <code>{credential.id}</code><span>{credential.state}</span>
            {credential.state !== 'revoked' && <button disabled={busy} onClick={() => setRevokeId(credential.id)}>吊销此版本</button>}
            {revokeId === credential.id && <div role="alert"><p>确认吊销该凭证版本？引用它的任务将受阻。</p>
              <button disabled={busy} className="danger" onClick={() => void act(async () => {
                const result = await request(`/admin/model-providers/${encode(provider.id)}/credentials/${encode(credential.id)}/revoke`, send('POST'));
                selectProvider(result); setNotice('指定凭证版本已吊销。');
              })}>确认吊销</button><button onClick={() => setRevokeId('')}>暂不吊销</button>
            </div>}
          </div>)}
        </details>}
      </div>
      <div>
        <h3>发布平台模型</h3>
        <div className="admin-list">{models.map(m => <div key={m.id}>
          <span><b>{m.name}</b><small>{m.kind} · {m.published ? '已发布' : '草稿'} · {m.enabled ? '启用' : '停用'}{defaults[m.kind] === m.id ? ' · 默认' : ''}</small></span>
          <button disabled={busy} onClick={() => selectModel(m)}>编辑 {m.name}</button>
        </div>)}</div>
        <button disabled={busy} onClick={() => selectModel(emptyModel())}>新建模型</button>
        {!providers.length && <p className="muted">请先保存 Provider，再发布模型。</p>}
        <form onSubmit={e => {e.preventDefault(); void act(async () => {
          const body = {revision: model.revision, provider_id: model.provider_id, kind: model.kind,
            published: model.published, enabled: model.enabled, default: isDefault,
            definition: {...model.definition, capabilities: parseObject(caps, '能力'), defaults: parseObject(params, '默认参数'), rules: parseObject(rules, '参数规则')}};
          const result = await request('/admin/models' + (model.id ? '/' + encode(model.id) : ''), send(model.id ? 'PUT' : 'POST', body));
          setModel(result); setNotice(result.published ? '模型已保存并发布；普通用户可在目录中选择可用模型。' : '模型草稿已保存，普通目录不可见。');
        });}}>
          <label>模型显示名称<input required maxLength={100} value={model.definition.name} onChange={e => setModel({...model, definition: {...model.definition, name: e.target.value}})}/></label>
          <label>所属 Provider<select required value={model.provider_id} onChange={e => setModel({...model, provider_id: e.target.value})}>
            <option value="">请选择服务</option>{providers.map(p => <option key={p.id} value={p.id}>{p.name}{p.enabled ? '' : '（停用）'}</option>)}
          </select></label>
          <label>模型用途<select value={model.kind} disabled={Boolean(model.id)} onChange={e => setModel({...model, kind: e.target.value})}>
            <option value="text">文本</option><option value="image">图片</option><option value="video">视频</option><option value="audio">语音</option>
          </select></label>
          {providers.find(p => p.id === model.provider_id)?.config.type === 'replicate' && <p className="muted">Replicate 当前仅接通文本、图片和视频；语音用途未接通，服务端会拒绝发布。</p>}
          <label>上游模型标识（仅管理员）<input required maxLength={500} value={model.definition.upstream_model} onChange={e => setModel({...model, definition: {...model.definition, upstream_model: e.target.value}})}/></label>
          <label>能力（JSON）<textarea rows={3} value={caps} onChange={e => setCaps(e.target.value)} placeholder={'{"image_reference":true,"max_references":1}'}/></label>
          <label>允许参数规则（JSON）<textarea rows={4} value={rules} onChange={e => setRules(e.target.value)} placeholder={'{"max_tokens":{"type":"integer","min":1,"max":12000}}'}/></label>
          <label>默认参数（JSON）<textarea rows={3} value={params} onChange={e => setParams(e.target.value)} placeholder={'{"max_tokens":4096}'}/></label>
          <p className="muted">仅允许规则中列出的参数；每个受限参数都须提供合法默认值或由用户提交，缺省不会使用适配器的隐藏默认值。支持 integer/number/string/boolean/strings 及 min/max/enum/max_length。</p>
          <label className="checkbox"><input type="checkbox" checked={model.published} onChange={e => setModel({...model, published: e.target.checked})}/>发布到普通模型目录</label>
          <label className="checkbox"><input type="checkbox" checked={model.enabled} onChange={e => setModel({...model, enabled: e.target.checked})}/>启用模型</label>
          <label className="checkbox"><input type="checkbox" checked={isDefault} onChange={e => setIsDefault(e.target.checked)}/>设为该用途默认模型</label>
          <button className="primary" disabled={busy || !providers.length} type="submit">保存模型</button>
        </form>
      </div>
    </div>
  </section>;
}
