import {useEffect,useState} from 'react';
type V=Record<string,any>;
type Request=(path:string,options?:RequestInit)=>Promise<any>;

export function SampleReview({pid,sample,samples,request,video}:{pid:string;sample:V;samples:V[];request:Request;video:React.RefObject<HTMLVideoElement|null>}){
  const [data,setData]=useState<V|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const [frame,setFrame]=useState(0),[body,setBody]=useState(''),[replies,setReplies]=useState<Record<string,string>>({});
  const base=`/projects/${pid}/samples/${sample.id}/review-events`,meta=sample.metadata;
  const seconds=(n:number)=>n*meta.fps_den/meta.fps_num;
  const label=(n:number)=>`${seconds(n).toFixed(3)} 秒 · 第 ${n+1} 帧`;
  useEffect(()=>{let alive=true;setData(null);setError('');setBody('');setFrame(0);setReplies({});
    request(base).then(value=>{if(alive)setData(value);}).catch(e=>{if(alive)setError(e.message);});
    return()=>{alive=false;};},[base]);
  useEffect(()=>{const player=video.current;if(!player)return;
    const update=()=>setFrame(Math.min(meta.frame_count-1,Math.max(0,Math.floor(player.currentTime*meta.fps_num/meta.fps_den+1e-6))));
    player.addEventListener('timeupdate',update);player.addEventListener('seeked',update);
    return()=>{player.removeEventListener('timeupdate',update);player.removeEventListener('seeked',update);};},[sample.id]);
  function seek(n:number){const player=video.current;if(!player||!Number.isFinite(n))return;player.pause();n=Math.trunc(n);
    const next=Math.max(0,Math.min(meta.frame_count-1,n));player.currentTime=seconds(next);setFrame(next);}
  async function refresh(){setBusy(true);setError('');try{setData(await request(base));}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  async function send(kind:string,fields:V={}){if(!data)return;setBusy(true);setError('');
    try{setData(await request(base,{method:'POST',body:JSON.stringify({kind,revision:data.revision,latest_id:data.latest_id,
      staffing_revision:data.staffing_revision,...fields})}));if(kind==='comment'||kind==='return')setBody('');
      if(kind==='reply')setReplies(prev=>({...prev,[fields.parent_id]:''}));
    }catch(e:any){setError(e.message);}finally{setBusy(false);}}
  const comments=data?.events.filter((event:V)=>event.kind==='comment'&&event.sample_id===sample.id)||[];
  const oldOpen=data?.events.filter((event:V)=>event.kind==='comment'&&event.sample_id!==sample.id&&data.unresolved_ids.includes(event.id))||[];
  return <section aria-label="秒帧批注与审批"><h4>样片 V{sample.version} · {{pending:'待审查',approve:'此版本已批准',return:'已退回修改'}[data?.status as string]||'正在加载'}</h4>
    <p>批注固定在当前版本。回复修改结果后，由制片人确认解决；新版不会继承旧版批准。</p>
    <div><button onClick={()=>seek(frame-1)}>上一帧</button> <output aria-label="当前审片位置">{label(frame)}</output> <button onClick={()=>seek(frame+1)}>下一帧</button></div>
    <label>定位到帧（从 1 开始）<input type="number" min={1} max={meta.frame_count} value={frame+1} onChange={e=>seek(Number(e.target.value)-1)}/></label>
    <button disabled={busy} onClick={()=>void refresh()}>刷新批注与审批</button>
    {error&&<p role="alert">{error}。输入内容已保留，请刷新核对。</p>}
    {data?.can_review&&<div><label>本帧批注或退回原因<textarea value={body} onFocus={()=>video.current?.pause()} onChange={e=>setBody(e.target.value)} maxLength={4000}/></label>
      <button disabled={busy||!body.trim()} onClick={()=>void send('comment',{frame,body})}>在当前帧添加批注</button>
      {data.latest_id===sample.id&&<><button disabled={busy||!body.trim()} onClick={()=>void send('return',{body})}>退回修改</button>
        <button disabled={busy||data.unresolved_ids.length>0} onClick={()=>void send('approve')}>批准当前样片 V{sample.version}</button></>}
    </div>}
    {!!oldOpen.length&&<p>其他版本还有 {oldOpen.length} 条待确认批注。请从上方“样片版本”切换到对应旧版查看、回复或确认解决，不会自动搬动批注位置。</p>}
    {!comments.length&&<p>此版本暂无批注。</p>}
    {comments.map((item:V)=><article key={item.id}><button onClick={()=>seek(item.frame)}>定位：{label(item.frame)}</button>
      <p>{item.author}：{item.body} · {data!.unresolved_ids.includes(item.id)?'待确认解决':'已确认解决'}</p>
      {data!.events.filter((e:V)=>e.parent_id===item.id).map((reply:V)=><p key={reply.id}>{reply.author}：{reply.kind==='reply'?reply.body:reply.kind==='resolve'?'确认解决':'重新打开'}
        {reply.related_sample_id&&`（修改结果：V${samples.find(s=>s.id===reply.related_sample_id)?.version??'?'}）`}</p>)}
      {data!.can_reply&&<><label>回复修改结果<textarea maxLength={4000} value={replies[item.id]||''} onChange={e=>setReplies(prev=>({...prev,[item.id]:e.target.value}))}/></label>
        <button disabled={busy||!replies[item.id]?.trim()} onClick={()=>void send('reply',{parent_id:item.id,body:replies[item.id],related_sample_id:data!.latest_id})}>回复（关联最新样片）</button></>}
      {data!.can_review&&<button disabled={busy} onClick={()=>void send(data!.unresolved_ids.includes(item.id)?'resolve':'reopen',{parent_id:item.id})}>{data!.unresolved_ids.includes(item.id)?'确认此项已解决':'重新打开此项'}</button>}
    </article>)}
    <details><summary>审批历史</summary>{data?.events.filter((e:V)=>e.sample_id===sample.id&&['approve','return'].includes(e.kind)).map((e:V)=><p key={e.id}>{e.author} · {e.kind==='approve'?'批准':'退回'} · {e.body} · {new Date(e.created*1000).toLocaleString()}</p>)}</details>
  </section>;
}
