import {useEffect,useRef,useState} from 'react';
import type {CollaborationClient} from './collaborationClient';
import type {ObjectRow} from './objectDrafts';
import type {EditorAsset} from './editor/editorDocument';
import './collaboration.css';

type Value=Record<string,any>;
const kindNames:Value={shot:'镜头',node:'自由节点',visual_card:'视觉卡 / 音色',graph:'画布结构',timeline:'剪辑时间线',director:'3D 导演台'};
const states:Value={saved:'已保存',dirty:'未保存',saving:'保存中',conflict:'冲突 · 草稿保留',error:'保存失败'};
const reviews:Value={in_progress:'进行中',pending_review:'待确认',completed:'已完成',returned:'已退回'};
const label=(row:ObjectRow)=>`${kindNames[row.kind]||row.kind} · ${row.content.shot?.id||row.content.card?.name||row.content.node?.data?.label||row.object_key}`;

/** Existing editor side panel; all state-changing actions use object commands. */
export function CollaborationPanel({client,document,assets,actorId,canManage,canEdit,request,onDocument,onSave}: {
  client:CollaborationClient;document:Value;assets:EditorAsset[];actorId:string;canManage:boolean;canEdit:boolean;
  request:(path:string,init?:RequestInit)=>Promise<any>;
  onDocument:(document:Value)=>void;onSave:(id:string)=>Promise<void>;
}){
  const [selected,setSelected]=useState(''),[members,setMembers]=useState<Value[]>([]),[assignee,setAssignee]=useState('');
  const [history,setHistory]=useState<Value[]>([]),[comments,setComments]=useState<Value[]>([]),[body,setBody]=useState('');
  const [comparison,setComparison]=useState<ObjectRow|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const [,render]=useState(0),mounted=useRef(true),selectionRef=useRef(selected),documentRef=useRef(document);
  selectionRef.current=selected;documentRef.current=document;
  const rows=[...client.rows.values()],row=rows.find(item=>item.id===selected),draft=row&&client.drafts.entries.get(row.id);
  const businessMode=Boolean(client.project?.permissions?.workflow_enabled);
  const own=row?.assignee_id===actorId,editable=canEdit&&(own||(!businessMode&&row?.kind==='graph'));
  const pid=client.project?.id,productionId=client.project?.production_id;
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{let cancelled=false;
    // Member names are convenience only; the server validates effective membership again.
    request(`/productions/${productionId}/members`).then(items=>{if(!cancelled)setMembers(items);})
      .catch(()=>{if(!cancelled)setMembers([]);});
    return()=>{cancelled=true;};
  },[productionId,request]);
  useEffect(()=>{if(!rows.some(item=>item.id===selected))setSelected(rows[0]?.id||'');},[pid,rows.map(item=>item.id).join('|'),selected]);
  useEffect(()=>{
    setComparison(null);setHistory([]);setComments([]);setError('');setBody('');setAssignee(row?.assignee_id||'');
    let cancelled=false;
    if(selected)Promise.all([client.read(selected,'history'),client.read(selected,'comments')]).then(([h,c])=>{
      if(!cancelled){setHistory(h);setComments(c);}
    }).catch(e=>{if(!cancelled)setError(e.message);});
    return()=>{cancelled=true;};
  },[pid,selected,row?.revision,client]);
  const run=async(action:()=>Promise<void>)=>{
    setBusy(true);setError('');
    try{await action();}catch(e:any){if(mounted.current)setError(e.message);}
    finally{if(mounted.current){setBusy(false);render(value=>value+1);}}
  };
  const change=async(action:'assign'|'review'|'restore',data:Value)=>{
    if(!row)return;
    const latest=await client.action(row.id,action,data);
    if(mounted.current)onDocument(client.mergeRemote(latest,documentRef.current,assets));
  };
  const person=(id:string|null)=>members.find(member=>member.id===id)?.nickname|| (id===actorId?'我':id||'待分配');
  const held=row&&client.leases.get(row.id);
  return <section className="collaboration-panel" aria-label="对象协作">
    <p>{businessMode?'这里查看制作内容的保存状态、历史与冲突。日常角色和分集负责人请在作品分工中设置。':'只保存自己负责的对象。管理者请先明确接管再改内容；分配与接管会撤销旧页面的编辑凭证。'}</p>
    <label>{businessMode?'制作内容':'协作对象'}<select aria-label="协作对象" value={selected} disabled={busy} onChange={e=>setSelected(e.target.value)}>
      {rows.map(item=><option key={item.id} value={item.id}>{businessMode?(item.content.card?.name||item.content.node?.data?.label||item.content.shot?.scene||kindNames[item.kind]):label(item)} · {states[client.drafts.entries.get(item.id)?.state||'saved']}</option>)}
    </select></label>
    {error&&<p role="alert" className="danger">{error}</p>}
    {row&&<>
      <dl className="collaboration-summary"><div><dt>负责人</dt><dd>{person(row.assignee_id)}</dd></div>
        <div><dt>内容版本</dt><dd>r{row.revision}{!businessMode&&` / 分配代际 ${row.assignment_epoch}`}</dd></div>
        <div><dt>保存状态</dt><dd role="status">{states[draft?.state||'saved']}</dd></div>
        <div><dt>审核状态</dt><dd>{reviews[row.status]||row.status}</dd></div></dl>
      {draft?.error&&<p className="danger">{draft.error}</p>}
      <div className="collaboration-actions">
        <button disabled={busy||!editable||!draft||!['dirty','error'].includes(draft.state)}
          onClick={()=>void run(()=>onSave(row.id))}>仅保存此对象</button>
        <button disabled={busy||draft?.state==='saving'} onClick={()=>void run(async()=>{
          const latest=await client.read(row.id);
          if(mounted.current&&selectionRef.current===row.id)setComparison(latest);
        })}>比较本地与远端</button>
      </div>
      {comparison&&comparison.id===row.id&&<section className="collaboration-comparison" aria-label="对象草稿比较">
        <p>比较远端 r{comparison.revision}。不会自动重新提交；若负责人变更，只能保留备份后载入远端。</p>
        <details open><summary>本地草稿</summary><pre>{JSON.stringify(draft?.content,null,2)}</pre></details>
        <details open><summary>远端内容</summary><pre>{JSON.stringify(comparison.content,null,2)}</pre></details>
        <div className="collaboration-actions">
          <button disabled={busy} onClick={()=>{const blob=new Blob([JSON.stringify({object_id:row.id,
            revision:draft?.base.revision,assignment_epoch:draft?.base.assignment_epoch,content:draft?.content},null,2)],{type:'application/json'});
            const url=URL.createObjectURL(blob),link=window.document.createElement('a');link.href=url;
            link.download=`object-draft-${row.id}.json`;link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);
          }}>下载此对象草稿</button>
          <button disabled={busy} onClick={()=>void run(async()=>{
            onDocument(client.resolve(row.id,comparison,'discard',documentRef.current,assets));setComparison(null);
          })}>放弃此对象草稿，载入远端</button>
          <button disabled={busy||!editable||comparison.assignment_epoch!==draft?.base.assignment_epoch}
            onClick={()=>void run(async()=>{onDocument(client.resolve(row.id,comparison,'keep-draft',documentRef.current,assets));setComparison(null);await onSave(row.id);})}>
            已比较，明确提交此对象草稿</button>
        </div>
      </section>}
      {canManage&&<details open={businessMode?undefined:true}><summary>制片人高级异常处理</summary><fieldset disabled={busy}><legend>特殊分配 / 明确接管</legend>
        <label>负责人账号<select aria-label="分配对象负责人" value={assignee} onChange={e=>setAssignee(e.target.value)}>
          <option value="">待分配</option>
          <option value={actorId}>我（当前账号）</option>
          {members.filter(member=>member.id!==actorId).map(member=><option key={member.id} value={member.id}>{member.nickname} · {member.role}</option>)}
        </select></label>
        <div className="collaboration-actions"><button onClick={()=>void run(()=>change('assign',{assignee_id:assignee||null}))}>确认重新分配</button>
          <button onClick={()=>void run(()=>change('assign',{assignee_id:actorId}))}>明确接管到我（旧凭证失效）</button></div>
      </fieldset></details>}
      {row.kind==='timeline'&&<fieldset disabled={busy||!own||!canEdit}><legend>时间线独占租约</legend>
        <p>{held?`本页租约到期：${new Date(held.expires*1000).toLocaleTimeString()}`:'本页尚未取得租约。另一页面持有时不可编辑提交。'}</p>
        <div className="collaboration-actions">
          <button onClick={()=>void run(async()=>{await client.lease(row.id,'acquire');})}>申请租约 / 过期后重新申请</button>
          <button disabled={!held} onClick={()=>void run(async()=>{await client.lease(row.id,'renew');})}>续租</button>
          <button disabled={!held} onClick={()=>void run(async()=>{await client.lease(row.id,'release');})}>释放本页租约</button>
        </div>
        <small>保存前会校验并按需续租；管理者明确接管会使旧租约失效。</small>
      </fieldset>}
      {businessMode?<p><a href={`/workflow?production=${encodeURIComponent(productionId)}`}>前往剧本与总资产验收</a>。镜头生成完成后由抽卡师选定素材，不设置额外分集制作审批。</p>:<fieldset disabled={busy||draft?.state!=='saved'}><legend>版本审核</legend>
        <div className="collaboration-actions">
          <button disabled={!editable||!['in_progress','returned'].includes(row.status)} onClick={()=>void run(()=>change('review',{action:'submit'}))}>提交当前 r{row.revision} 确认</button>
          {canManage&&<><button disabled={row.status!=='pending_review'} onClick={()=>void run(()=>change('review',{action:'approve'}))}>确认当前版本</button>
            <button disabled={row.status!=='pending_review'} onClick={()=>void run(()=>change('review',{action:'return'}))}>退回修改</button></>}
        </div>
      </fieldset>}
      <details><summary>历史版本（恢复会追加新版本）</summary>
        {history.map(item=><div className="collaboration-history" key={item.revision}>
          <span>r{item.revision} · {item.action} · {person(item.actor_user_id)} · {new Date(item.created*1000).toLocaleString()}</span>
          <button disabled={busy||!editable||draft?.state!=='saved'||item.revision===row.revision}
            onClick={()=>void run(()=>change('restore',{revision:item.revision}))}>恢复 r{item.revision}</button>
          <details><summary>查看内容</summary><pre>{JSON.stringify(item.snapshot.content,null,2)}</pre></details>
        </div>)}
      </details>
      <section aria-label="对象评论"><h3>对象评论</h3><p>viewer 也可以评论，评论不会改动对象内容或审核状态。</p>
        <button disabled={busy} onClick={()=>void run(async()=>{const result=await client.read(row.id,'comments');
          if(mounted.current&&selectionRef.current===row.id)setComments(result);})}>刷新评论</button>
        {comments.map(item=><article key={item.id}><small>{person(item.actor_user_id)} · {new Date(item.created*1000).toLocaleString()}</small><p className="collaboration-comment">{item.body}</p></article>)}
        <label>新评论<textarea maxLength={8000} value={body} onChange={e=>setBody(e.target.value)} /></label>
        <button disabled={busy||!body.trim()} onClick={()=>void run(async()=>{
          await client.comment(row.id,body);const result=await client.read(row.id,'comments');
          if(mounted.current&&selectionRef.current===row.id){setComments(result);setBody('');}
        })}>发送评论</button>
      </section>
    </>}
  </section>;
}
