import {useEffect,useRef,useState} from 'react';
type Value=Record<string,any>;

/** An explicit, read-only comparison precedes every candidate adoption. */
export function CandidateReview({job,request,onAdopt}:{job:Value;
  request:(path:string,init?:RequestInit)=>Promise<any>;
  onAdopt:(job:Value,body:Value)=>Promise<void>}){
  const [comparison,setComparison]=useState<Value|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const alive=useRef(true),sequence=useRef(0);
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;sequence.current++;};},[]);
  const target=job.collaboration?.target;
  if(!target||job.status!=='succeeded'||job.collaboration?.mode==='export')return null;
  if(job.collaboration.adopted)return <p className="muted">此候选已明确采纳为 r{job.collaboration.adopted.revision}；生成成功与采纳分别记录。</p>;
  const stale=comparison&&(comparison.current.revision!==target.revision||comparison.current.assignment_epoch!==target.assignment_epoch);
  async function compare(){
    const seq=++sequence.current;setBusy(true);setError('');
    try{const value=await request(`/projects/${job.project_id}/candidates/${job.id}`);
      if(alive.current&&seq===sequence.current)setComparison(value);
    }catch(e:any){if(alive.current&&seq===sequence.current)setError(e.message);}
    finally{if(alive.current&&seq===sequence.current)setBusy(false);}
  }
  async function adopt(){
    if(!comparison)return;setBusy(true);setError('');
    try{await onAdopt(job,{expected_revision:comparison.current.revision,
      assignment_epoch:comparison.current.assignment_epoch,accept_stale:Boolean(stale)});
      if(alive.current)setComparison(null);
    }catch(e:any){if(alive.current)setError(e.message);}
    finally{if(alive.current)setBusy(false);}
  }
  return <section className="candidate-review">
    <p>候选结果 · 尚未写入正式内容 · 提交时 r{target.revision} / epoch {target.assignment_epoch}</p>
    <button disabled={busy} onClick={()=>void compare()}>比较候选与当前内容</button>
    {comparison&&<>
      <details open><summary>当前内容 r{comparison.current.revision} / epoch {comparison.current.assignment_epoch}</summary>
        <pre style={{maxHeight:220,overflow:'auto',whiteSpace:'pre-wrap'}}>{JSON.stringify(comparison.current,null,2)}</pre></details>
      <details open><summary>本次生成候选（不会自动覆盖）</summary>
        <pre style={{maxHeight:220,overflow:'auto',whiteSpace:'pre-wrap'}}>{JSON.stringify(comparison.job.result,null,2)}</pre></details>
      {comparison.impact&&<details open><summary>分镜导入影响范围（负责人、版本及待移除对象）</summary>
        <p>{comparison.impact.scope}。导入 {comparison.impact.candidate_shot_count} 个镜头、{comparison.impact.new_card_count} 张新卡；移除 {comparison.impact.removed_ids.length} 个旧镜头。</p>
        {comparison.impact.needs_artist&&<p>新共享资产已列入资产师待办。请资产师在“作品分工 → 分镜资产候选”接手后，再刷新比较并采纳分镜。<a href={`/workflow?production=${encodeURIComponent(job.production_id)}`}>查看资产待办</a></p>}
        <p>{comparison.impact.business_mode?'必须负责所有被替换镜头；共享资产由资产师负责，不随分镜替换。':'必须负责所有被替换镜头；移除旧镜头还需 manager/owner 权限。'}任何引用版本改变都会拒绝整批导入。</p>
        <pre style={{maxHeight:220,overflow:'auto',whiteSpace:'pre-wrap'}}>{JSON.stringify(comparison.impact.shots,null,2)}</pre></details>}
      {stale&&<p className="error">目标已编辑或重新分配。采纳会替换刚刚比较的当前版本，原版本留在历史中；若版本再次变化，服务器将拒绝。</p>}
      <button disabled={busy||!comparison.can_adopt} onClick={()=>void adopt()}>
        {stale?'已比较，明确将旧候选采纳到当前版本':'已比较，明确采纳此候选'}</button>
      {!comparison.can_adopt&&<p className="muted">当前仅可查看；需要目标负责人或改编管理权限才能采纳。</p>}
    </>}
    {error&&<p className="error">{error}</p>}
  </section>;
}
