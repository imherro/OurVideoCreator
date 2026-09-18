import {useEffect,useState} from 'react';
import type {OwnedContentDrafts,ContentRequest} from './ownedContentDrafts';

type Value=Record<string,any>;
const labels:Value={saved:'已保存',dirty:'未保存',saving:'保存中',conflict:'冲突：草稿已保留',error:'保存失败'};

export function OwnedContentPanel({store,id,actorId,canManage,canEdit,request,onChange,onSave,businessMode=false}: {
  store:OwnedContentDrafts;id:string;actorId:string;canManage:boolean;canEdit:boolean;request:ContentRequest;
  onChange:()=>void;onSave:()=>Promise<void>;
  businessMode?:boolean;
}){
  const [members,setMembers]=useState<Value[]>([]),[assignee,setAssignee]=useState('');
  const [history,setHistory]=useState<Value[]>([]),[comments,setComments]=useState<Value[]>([]),[body,setBody]=useState('');
  const [comparison,setComparison]=useState<Value|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const entry=store.drafts.entries.get(id),value=store.value(id),path=store.commandPath(id);
  const productionId=store.productionId,generation=store.generation;
  useEffect(()=>{let alive=true;
    request(`/productions/${productionId}/members`).then(rows=>{if(alive)setMembers(rows);}).catch(()=>{});
    return()=>{alive=false;};
  },[productionId,request]);
  useEffect(()=>{let alive=true;setComparison(null);setError('');setAssignee(value?.assignee_id||'');
    if(path)Promise.all([request(path+'/history'),request(path+'/comments')]).then(([h,c])=>{
      if(alive){setHistory(h);setComments(c);}
    }).catch(e=>{if(alive)setError(e.message);});
    return()=>{alive=false;};
  },[path,value?.revision,request]);
  if(!entry||!value)return null;
  const clean=entry.state==='saved',editable=canEdit&&store.editable(id,actorId);
  const valid=()=>store.matches(productionId,generation)&&store.commandPath(id)===path;
  async function run(action:()=>Promise<void>){setBusy(true);setError('');try{await action();}
    catch(e:any){if(valid())setError(e.message);}finally{if(valid()){setBusy(false);onChange();}}}
  async function command(action:string,data:Value){
    if(!path)return;
    const result=await request(path+'/'+action,{method:'POST',body:JSON.stringify({
      expected_revision:value!.revision,assignment_epoch:value!.assignment_epoch,...data})});
    if(valid()){store.receive(id,result,productionId,generation);onChange();}
  }
  const person=(userId:string|null)=>members.find(m=>m.id===userId)?.nickname||(userId===actorId?'我':userId||'待分配');
  return <section className="collaboration-panel" aria-label={store.kind==='chapter'?'章节协作':'剧本协作'}>
    <p><b>{labels[entry.state]}</b> · 版本 {value.revision} · 负责人：{person(value.assignee_id)}</p>
    {!editable&&<p>当前只读。{businessMode?<><a href={`/workflow?production=${encodeURIComponent(productionId)}`}>请在作品分工中确认编剧职责与负责人</a>；已有草稿可以保留或复制。</>:'管理者须明确接管，才能编辑他人负责的正文。'}</p>}
    {(error||entry.error)&&<p role="alert" className="error">{error||entry.error}</p>}
    {path&&entry.state!=='saved'&&<div>
      <button disabled={busy||!!entry.flight} onClick={()=>void run(async()=>{
        const latest=await request(path);if(valid())setComparison(latest);
      })}>读取远端版本并比较</button>
      <details><summary>查看/复制本地草稿</summary><pre>{JSON.stringify(entry.content,null,2)}</pre></details>
      {entry.base.unavailable&&<button disabled={busy||!!entry.flight} onClick={()=>{
        store.drafts.entries.delete(id);onChange();
      }}>已复制需要的内容，明确放弃不可见对象的本地草稿</button>}
      {comparison&&<><details open><summary>远端 r{comparison.revision}（不会自动覆盖本地）</summary><pre>{JSON.stringify(comparison,null,2)}</pre></details>
        <button disabled={busy} onClick={()=>{store.drafts.resolve(id,store.row(id,comparison),'discard');setComparison(null);onChange();}}>明确放弃此草稿，采用远端</button>
        <button disabled={busy||!editable} onClick={()=>void run(async()=>{
          store.drafts.resolve(id,store.row(id,comparison),'keep-draft');setComparison(null);onChange();await onSave();
        })}>已比较，明确提交此草稿</button></>}
    </div>}
    {path&&canManage&&<details open={businessMode?undefined:true}><summary>制片人高级异常处理</summary><p>特殊转交会撤销旧负责人的写入资格。日常请通过作品分工安排工作。</p><div className="collaboration-actions">
      <select aria-label="内容负责人" value={assignee} disabled={busy||!clean} onChange={e=>setAssignee(e.target.value)}>
        <option value="">待分配</option><option value={actorId}>我</option>
        {members.filter(m=>m.id!==actorId).map(m=><option key={m.id} value={m.id}>{m.nickname} · {m.role}</option>)}
      </select>
      <button disabled={busy||!clean} onClick={()=>void run(()=>command('assign',{assignee_id:assignee||null}))}>确认分配</button>
      <button disabled={busy||!clean} onClick={()=>void run(()=>command('assign',{assignee_id:actorId}))}>明确接管到我</button>
    </div></details>}
    {path&&store.kind==='chapter'&&<div className="collaboration-actions">
      <button disabled={busy||!clean||!editable} onClick={()=>void run(()=>command('review',{action:'submit'}))}>提交章节审核</button>
      <button disabled={busy||!clean||!canManage||value.status!=='pending_review'} onClick={()=>void run(()=>command('review',{action:'approve'}))}>确认章节</button>
      <button disabled={busy||!clean||!canManage} onClick={()=>void run(()=>command('review',{action:'return'}))}>退回章节</button>
      <span>{value.status}</span>
    </div>}
    {path&&<details><summary>历史与评论</summary>
      {history.map(item=><div key={item.revision}><details><summary>r{item.revision}</summary><pre>{JSON.stringify(item.snapshot,null,2)}</pre></details>
        <button disabled={busy||!clean||!editable||item.revision===value.revision} onClick={()=>void run(()=>command('restore',{revision:item.revision}))}>恢复为新版本</button></div>)}
      {comments.map(item=><p key={item.id}><b>{person(item.actor_user_id)}：</b>{item.body}</p>)}
      <textarea aria-label="内容评论" value={body} maxLength={8000} onChange={e=>setBody(e.target.value)}/>
      <button disabled={busy||!body.trim()} onClick={()=>void run(async()=>{
        const sent=body;await request(path+'/comments',{method:'POST',body:JSON.stringify({body:sent})});
        const latest=await request(path+'/comments');if(valid()){setComments(latest);setBody(current=>current===sent?'':current);}
      })}>发表评论</button>
    </details>}
  </section>;
}
