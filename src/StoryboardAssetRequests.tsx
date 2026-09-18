import {useEffect,useState} from 'react';
type V=Record<string,any>;
type Request=(path:string,options?:RequestInit)=>Promise<any>;

export function StoryboardAssetRequests({productionId,request}:{productionId:string;request:Request}){
  const [data,setData]=useState<V|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
  const base=`/productions/${productionId}/workflow/asset-candidates`;
  useEffect(()=>{let alive=true;request(base).then(value=>{if(alive)setData(value);}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[productionId]);
  async function reload(){setBusy(true);setError('');try{setData(await request(base));}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  async function prepare(item:V){setBusy(true);setError('');setNotice('');
    try{const result=await request(base+'/'+item.job_id,{method:'POST',body:JSON.stringify({fingerprint:item.fingerprint})});setNotice(result.message);setData(await request(base));}
    catch(e:any){setError(e.message);}finally{setBusy(false);}}
  return <section aria-label="分镜资产候选"><h2>分镜资产候选</h2>
    <p>抽卡师生成的新角色、场景等在这里交给默认资产师。确认只建立资产草稿，不自动通过验收；已有资产不被覆盖。</p>
    <button disabled={busy} onClick={()=>void reload()}>刷新资产待办</button>
    {error&&<p role="alert">{error}，请刷新后核对。</p>}{notice&&<p role="status">{notice}</p>}
    {data&&!data.items.length&&<p>暂无需要资产师接手的分镜新资产。</p>}
    {data&&!data.can_prepare&&!!data.items.length&&<p>请由作品默认资产师接手；未设置时由制片人在“作品默认负责人”中指定。</p>}
    {data?.items.map((item:V)=><article key={item.job_id}><h3>第 {item.episode_no} 集 · {item.episode_title}</h3>
      {Object.values(item.visual.cards).map((card:any)=><details key={card.id}><summary>{card.name}</summary>
        {Object.values(item.visual.versions).filter((v:any)=>v.cardId===card.id).map((v:any)=><p key={v.id}>{v.spec?.description||'待补充设定'}</p>)}
      </details>)}
      {data.can_prepare&&<button disabled={busy} onClick={()=>void prepare(item)}>接手这些新资产，建立草稿</button>}
    </article>)}
  </section>;
}
