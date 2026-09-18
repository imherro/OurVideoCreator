import {useEffect,useRef,useState} from 'react';
type V=Record<string,any>;
type Request=(path:string,options?:RequestInit)=>Promise<any>;

export function EpisodeSamples({episodes,request}:{episodes:V[];request:Request}){
  const [pid,setPid]=useState(episodes[0]?.id||''),[data,setData]=useState<V|null>(null),[deliveries,setDeliveries]=useState<V[]>([]);
  const [delivery,setDelivery]=useState(''),[selected,setSelected]=useState(''),[file,setFile]=useState<File|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const uploadId=useRef(crypto.randomUUID()),input=useRef<HTMLInputElement>(null),base=`/projects/${pid}/samples`;
  useEffect(()=>{let alive=true;setData(null);setError('');setNotice('');setFile(null);setSelected('');
    if(input.current)input.current.value='';uploadId.current=crypto.randomUUID();
    if(pid)Promise.all([request(base),request(`/projects/${pid}/deliveries`)]).then(([value,packages])=>{
      if(alive){setData(value);setSelected(value.latest_id);setDeliveries(packages);setDelivery(packages[0]?.id||'');}
    }).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[pid]);
  async function refresh(){setBusy(true);setError('');try{
    const [value,packages]=await Promise.all([request(base),request(`/projects/${pid}/deliveries`)]);
    setData(value);setDeliveries(packages);if(!selected)setSelected(value.latest_id);
    if(!delivery)setDelivery(packages[0]?.id||'');
  }catch(e:any){setError(e.message);}finally{setBusy(false);}}
  async function upload(){if(!file||!data)return;setBusy(true);setError('');setNotice('');
    const form=new FormData();form.append('file',file);form.append('delivery_id',delivery);form.append('upload_id',uploadId.current);
    form.append('previous_id',data.latest_id);form.append('staffing_revision',String(data.staffing_revision));
    try{const result=await request(base,{method:'POST',body:form});setData(await request(base));setSelected(result.id);
      setNotice(`样片 V${result.version} 已上传，原文件和审片副本已保留。`);setFile(null);
      if(input.current)input.current.value='';uploadId.current=crypto.randomUUID();
    }catch(e:any){setError(e.message||'上传未完成，请核对后重试');}finally{setBusy(false);}}
  const sample=data?.items.find((item:V)=>item.id===selected);
  return <section aria-label="剪辑样片版本"><h2>剪辑样片版本</h2>
    <p>剪辑师在线下完成初剪后上传样片。每次上传追加版本，不覆盖原文件或旧样片。</p>
    <label>审片分集<select value={pid} disabled={busy} onChange={e=>setPid(e.target.value)}>
      {episodes.map(ep=><option key={ep.id} value={ep.id}>第 {ep.episode_no} 集 · {ep.episode_title}</option>)}</select></label>
    <button disabled={busy||!pid} onClick={()=>void refresh()}>刷新样片版本</button>
    {error&&<p role="alert">{error}。若版本或分工有变化，请刷新核对后再上传。</p>}
    {notice&&<p role="status">{notice}</p>}
    {data?.can_upload?<fieldset disabled={busy}><legend>上传新样片</legend>
      <label>本次使用的交付包<select value={delivery} onChange={e=>{setDelivery(e.target.value);uploadId.current=crypto.randomUUID();}}>
        <option value="">请选择交付包</option>{deliveries.map(item=><option key={item.id} value={item.id}>交付 V{item.version}</option>)}</select></label>
      {!deliveries.length&&<p>请先由抽卡师生成本集剪辑素材包。</p>}
      <label>样片文件<input ref={input} type="file" accept=".mp4,.mov,.webm" onChange={e=>{setFile(e.target.files?.[0]||null);uploadId.current=crypto.randomUUID();}}/></label>
      <p>支持 MP4 / MOV / WebM，最多 2 GB、60 分钟。固定帧率原片保留帧率；变帧率素材规范为 25 fps 审片副本。处理期间请保留此页。</p>
      <button disabled={!file||!delivery||busy} onClick={()=>void upload()}>上传为新版本</button>
    </fieldset>:<p>由本集剪辑负责人上传，其他作品成员可以查看历史样片。</p>}
    {busy&&<p role="status">正在处理，请稍候；不会覆盖已有样片。</p>}
    {!!data?.items.length&&<><label>样片版本<select value={selected} disabled={busy} onChange={e=>setSelected(e.target.value)}>
      {data.items.map((item:V)=><option key={item.id} value={item.id}>V{item.version} · {item.original_name}</option>)}</select></label>
      {sample&&<article><h3>样片 V{sample.version}</h3>
        <p>{sample.metadata.timeline_note} · {sample.metadata.frame_count} 帧</p>
        <video key={sample.id} controls preload="metadata" style={{width:'100%',maxHeight:540}} src={`/api/projects/${pid}/samples/${sample.id}/review`}/>
        <p><a href={`/api/projects/${pid}/samples/${sample.id}/original`}>下载 V{sample.version} 原文件</a> · 上传于 {new Date(sample.created*1000).toLocaleString()}</p>
      </article>}
    </>}
    {data&&!data.items.length&&<p>暂无剪辑样片。</p>}
  </section>;
}
