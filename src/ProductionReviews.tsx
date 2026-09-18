import {useEffect,useRef,useState} from 'react';

type V=Record<string,any>;
type Request=(path:string,options?:RequestInit)=>Promise<any>;
const status:Record<string,string>={in_progress:'制作中 / 修改后需重新提交',pending_review:'待制片人验收',completed:'此版本已通过',returned:'已退回修改',draft:'草稿',review:'待制片人验收',approved:'此版本已通过',stale:'已过期，需修订'};

export function ProductionReviews({productionId,request}:{productionId:string;request:Request}){
  const [data,setData]=useState<V|null>(null),[selected,setSelected]=useState<string[]>([]),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const alive=useRef(true),base=`/productions/${productionId}`,path=base+'/workflow/reviews';
  useEffect(()=>{alive.current=true;request(path).then(value=>{if(alive.current)setData(value);}).catch(e=>{if(alive.current)setError(e.message);});
    return()=>{alive.current=false;};},[productionId]);
  async function action(endpoint?:string,payload?:V){
    setBusy(true);setError('');
    try{
      if(endpoint)await request(endpoint,{method:'POST',body:JSON.stringify(payload)});
      const value=await request(path);
      if(alive.current){setData(value);setSelected([]);}
    }catch(e:any){if(alive.current)setError(e.message||'审核失败，请重新载入核对版本');}
    finally{if(alive.current)setBusy(false);}
  }
  const producer=data?.roles.includes('producer'),artist=data?.roles.includes('artist');
  const chosen=(data?.assets||[]).filter((row:V)=>selected.includes(row.id));
  const canSubmit=artist&&chosen.length>0&&chosen.every((row:V)=>row.assignee_id===data?.actor_id&&['in_progress','returned'].includes(row.status));
  const canReview=producer&&chosen.length>0&&chosen.every((row:V)=>row.status==='pending_review');
  function assetAction(kind:string){void action(path+'/assets',{action:kind,items:chosen.map((row:V)=>({id:row.id,revision:row.revision,assignment_epoch:row.assignment_epoch}))});}
  return <section aria-label="剧本与总资产验收"><h2>剧本与总资产验收</h2>
    <p>按当前显示的版本提交和验收。内容修改后需要重新审核，已绑定的旧资产版本不会自动替换。</p>
    <button disabled={busy} onClick={()=>void action()}>刷新验收列表</button>
    {error&&<p role="alert" className="error">{error}。请刷新后重新阅读内容，不要直接重复批准。</p>}
    {data&&<><h3>分集剧本</h3>{!data.scripts.length&&<p>暂无剧本。</p>}
      {data.scripts.map((row:V)=><article key={row.id} className="workflow-episode">
        <h4>第 {row.episode_no} 集 · {row.title||row.episode_title}</h4>
        <p>{status[row.status]||row.status} · 版本 {row.revision}</p>
        <details><summary>阅读本次剧本内容</summary><pre style={{whiteSpace:'pre-wrap'}}>{row.body||'尚未填写正文'}</pre></details>
        {producer&&row.status==='review'&&<div className="workflow-checks">
          <button disabled={busy} onClick={()=>void action(`${base}/episode-scripts/${row.episode_no}/approve`,{revision:row.revision,assignment_epoch:row.assignment_epoch})}>批准此版本剧本</button>
          <button disabled={busy} onClick={()=>void action(`${base}/episode-scripts/${row.episode_no}/needs-changes`,{revision:row.revision,assignment_epoch:row.assignment_epoch})}>退回修改</button></div>}
      </article>)}
      <h3>作品共享总资产</h3><p>资产师勾选自己负责的内容提交；制片人可逐项阅读后批量验收。不同负责人的资产无需等全片一起完成。</p>
      {!data.assets.length&&<p>暂无共享资产，请由资产师先建立角色、场景等资产。</p>}
      {data.assets.map((row:V)=><article className="workflow-episode" key={row.id}>
        <label><input type="checkbox" disabled={busy||(!producer&&row.assignee_id!==data.actor_id)} checked={selected.includes(row.id)}
          onChange={e=>setSelected(old=>e.target.checked?[...old,row.id]:old.filter(id=>id!==row.id))}/>{row.content.card.name||'未命名资产'} · {status[row.status]||row.status} · 版本 {row.revision}</label>
        <details><summary>查看资产内容与参考图</summary>
          {Object.values(row.content.versions).map((version:any)=><div key={version.id}><h4>资产版本 {version.version}{version.id===row.content.card.currentVersionId?'（当前）':''}</h4>
            <p style={{whiteSpace:'pre-wrap'}}>{version.spec?.description||'未填写描述'}</p>
            {(version.references||[]).filter((ref:V)=>ref.assetId).map((ref:V,index:number)=><a key={index} href={`/api/assets/${encodeURIComponent(ref.assetId)}/file`} target="_blank" rel="noreferrer">查看参考素材 {index+1} </a>)}
          </div>)}
          {row.content.voice_profile&&<p>音色：{row.content.voice_profile.voiceType||'已配置'} · 版本 {row.content.voice_profile.version}</p>}
        </details>
      </article>)}
      <p>已选择 {chosen.length} 项（每批最多 200 项）。</p>
      <div className="workflow-checks">
        {artist&&<button disabled={busy||!canSubmit||chosen.length>200} onClick={()=>assetAction('submit')}>提交选中资产</button>}
        {producer&&<><button disabled={busy||!canReview||chosen.length>200} onClick={()=>assetAction('approve')}>批准选中资产版本</button>
          <button disabled={busy||!canReview||chosen.length>200} onClick={()=>assetAction('return')}>退回选中资产</button></>}
      </div>
    </>}
  </section>;
}
