import {useEffect,useState} from 'react';

type V=Record<string,any>;
type Request=(path:string,options?:RequestInit)=>Promise<any>;

export function EpisodeDeliveries({episodes,actorId,roles,request}:{episodes:V[];actorId:string;roles:string[];request:Request}){
  const [pid,setPid]=useState(episodes[0]?.id||''),[preview,setPreview]=useState<V|null>(null);
  const [history,setHistory]=useState<V[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const episode=episodes.find(item=>item.id===pid),base=`/projects/${pid}/deliveries`;
  const canDeliver=roles.includes('generator')&&(episode?.effective_generator_id||episode?.generator_id)===actorId;
  useEffect(()=>{let live=true;setPreview(null);setHistory([]);setError('');setNotice('');
    if(pid)Promise.all([request(base+'/preview'),request(base)]).then(([p,h])=>{if(live){setPreview(p);setHistory(h);}}).catch(e=>{if(live)setError(e.message);});
    return()=>{live=false;};},[pid]);
  async function refresh(){
    setBusy(true);setError('');
    try{const [p,h]=await Promise.all([request(base+'/preview'),request(base)]);setPreview(p);setHistory(h);}
    catch(e:any){setError(e.message||'清单加载失败');}finally{setBusy(false);}
  }
  async function deliver(){
    if(!preview)return;setBusy(true);setError('');setNotice('');
    try{const result=await request(base,{method:'POST',body:JSON.stringify({fingerprint:preview.fingerprint})});
      setHistory(await request(base));setNotice(`已交付 V${result.version}，剪辑师可以下载。后续编辑不会更改这个包。`);
    }catch(e:any){setError(e.message||'交付未成功，请刷新清单核对');}finally{setBusy(false);}
  }
  return <section aria-label="剪辑素材交接"><h2>剪辑素材交接</h2>
    <p>抽卡师在制作页明确采纳可用视频后，在这里确认交付。无需额外的分集素材审批；剪辑师下载后在剪映或达芬奇中剪辑。</p>
    <label>交接分集<select value={pid} disabled={busy} onChange={e=>setPid(e.target.value)}>
      {episodes.map(ep=><option value={ep.id} key={ep.id}>第 {ep.episode_no} 集 · {ep.episode_title}</option>)}</select></label>
    <button disabled={!pid||busy} onClick={()=>void refresh()}>刷新交付清单</button>
    {error&&<p role="alert">{error}。请刷新后核对，不要直接重复提交。</p>}
    {notice&&<p role="status">{notice}</p>}
    {preview&&<><h3>当前选定内容</h3>
      <p>{preview.manifest.shots.length} 个镜头 · {preview.manifest.files.length} 个文件。包含剧本、对白、镜头顺序及已用音频，不包含未选中的生成候选。</p>
      {!!preview.issues.length&&<div role="alert"><b>尚不能交付：</b><ul>{preview.issues.map((issue:string,index:number)=><li key={index}>{issue}</li>)}</ul></div>}
      <details><summary>核对本次镜头与文件清单</summary>
        {preview.manifest.shots.map((shot:V)=><p key={shot.shot_uid}>镜头 {shot.number}（{shot.shot_id}） · {shot.video||'缺少视频'}</p>)}
      </details>
      {canDeliver?<button disabled={busy||preview.issues.length>0} onClick={()=>void deliver()}>{busy?'正在处理…':'确认选定内容，生成固定交付包'}</button>
        :<p>由本集抽卡师确认交付；查看和下载不需要制作对象编辑权限。</p>}
    </>}
    <h3>已交付版本</h3>
    {!history.length&&<p>还没有交付包。</p>}
    {history.map(item=><article key={item.id}><b>交付 V{item.version}</b> · {new Date(item.created*1000).toLocaleString()} · {item.manifest.shots.length} 镜
      {' '}<a href={`/api/projects/${pid}/deliveries/${item.id}/download`}>下载剪辑素材包 V{item.version}</a></article>)}
  </section>;
}
