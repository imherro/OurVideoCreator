import {useEffect, useState} from 'react';
import './productionWorkflow.css';
import {ProductionReviews} from './ProductionReviews';
import {EpisodeDeliveries} from './EpisodeDeliveries';
import {StoryboardAssetRequests} from './StoryboardAssetRequests';
import {EpisodeSamples} from './EpisodeSamples';

type V = Record<string, any>;
type Request = (path:string, options?:RequestInit)=>Promise<any>;
const ROLES:Record<string,string> = {producer:'制片人',writer:'编剧',artist:'资产师',generator:'抽卡师',editor:'剪辑师'};
const body = (method:string, value:V):RequestInit => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});

function RoleForm({member, save, busy}: {member:V;save:(id:string,roles:string[])=>void;busy:boolean}) {
  const [selected,setSelected]=useState<string[]>(member.roles||[]);
  return <form className="workflow-member" onSubmit={e=>{e.preventDefault();save(member.id,selected);}}>
    <b>{member.nickname}</b>
    <div className="workflow-checks">{Object.entries(ROLES).map(([role,label])=><label key={role}>
      <input type="checkbox" checked={selected.includes(role)} disabled={busy||!member.is_active}
        onChange={e=>setSelected(old=>e.target.checked?[...old,role]:old.filter(v=>v!==role))}/>{label}</label>)}</div>
    <button disabled={busy||!member.is_active}>保存角色</button>
  </form>;
}

function AssignSelect({label,value,members,role,busy,onSave,allowDefault=false}: {
  label:string;value:string|null;members:V[];role:string;busy:boolean;onSave:(id:string|null)=>void;allowDefault?:boolean;
}) {
  const [selected,setSelected]=useState(value||'');
  return <form className="workflow-assignment" onSubmit={e=>{e.preventDefault();onSave(selected||null);}}>
    <label>{label}<select value={selected} disabled={busy} onChange={e=>setSelected(e.target.value)}>
      <option value="">{allowDefault?'使用作品默认':'待分配'}</option>
      {members.filter(m=>m.is_active&&m.roles.includes(role)).map(m=><option key={m.id} value={m.id}>{m.nickname}</option>)}
    </select></label><button disabled={busy}>确认分工</button>
  </form>;
}

export function ProductionWorkflow({request}:{request:Request}) {
  const [productions,setProductions]=useState<V[]>([]),[pid,setPid]=useState(new URLSearchParams(location.search).get('production')||'');
  const [data,setData]=useState<V|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[notice,setNotice]=useState('');
  const [person,setPerson]=useState(''),[selected,setSelected]=useState<string[]>([]),[kind,setKind]=useState('chapter');
  const [target,setTarget]=useState(''),[special,setSpecial]=useState<V|null>(null);
  useEffect(()=>{let alive=true;request('/productions').then(rows=>{if(alive){setProductions(rows);setPid(old=>old||rows[0]?.id||'');}}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[]);
  const path=`/productions/${pid}/workflow`;
  useEffect(()=>{let alive=true;setData(null);setError('');setNotice('');setSelected([]);setSpecial(null);
    if(pid)request(path).then(v=>{if(alive)setData(v);}).catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[pid]);
  async function change(suffix:string,method:string,value:V) {
    setBusy(true);setError('');setNotice('');
    try {setData(await request(path+suffix,body(method,{revision:data?.config?.revision,...value})));setSelected([]);setSpecial(null);setNotice('已保存分工。现有内容、历史作者和生成记录保留。');}
    catch(e:any){setError(e.message||'保存失败，草稿已保留');if(e.detail?.type==='special_assignments')setSpecial({suffix,method,value,count:e.detail.count});}
    finally{setBusy(false);}
  }
  async function reload() {
    setBusy(true);
    try {setData(await request(path));setSpecial(null);setError('');}
    catch(e:any){setError(e.message||'加载失败');}
    finally{setBusy(false);}
  }
  const name=(id:string|null)=>data?.members?.find((m:V)=>m.id===id)?.nickname||'待分配';
  return <main className="admin-page workflow-page">
    <header><div><span className="eyebrow">PRODUCTION WORKFLOW</span><h1>作品分工</h1></div><nav><a href="/">返回工作室</a><a href="/members">团队成员</a></nav></header>
    <p>按角色和分集安排工作。一人可兼任，多人可承担相同角色；分工不改变平台管理员或团队权限。</p>
    <label>当前作品<select value={pid} disabled={busy} onChange={e=>setPid(e.target.value)}>
      {productions.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select></label>
    {!productions.length&&<p>暂无可访问作品，请先在工作室创建作品或联系制片人加入。</p>}
    {error&&<div role="alert" className="error">{error}<button disabled={busy||!pid} onClick={()=>void reload()}>重新载入分工</button></div>}
    {notice&&<p role="status" className="notice">{notice}</p>}
    {special&&<section role="alert"><h2>整集转交确认</h2><p>将覆盖 {special.count} 项已有特殊分配，旧负责人不能再编辑，旧租约失效。剧本和共享资产不会转交。</p>
      <button disabled={busy} onClick={()=>void change(special.suffix,special.method,{...special.value,confirm_special:true})}>确认覆盖这些分配并整集转交</button>
      <button disabled={busy} onClick={()=>setSpecial(null)}>取消</button></section>}
    {data&&!data.enabled&&<section><h2>启用五角色生产流程</h2><p>原作品内容和现有对象负责人保留。启用者成为本作品制片人；请随后给成员设置业务角色和分工，否则他们将只能查看。</p>
      {data.can_enable?<button className="primary" disabled={busy} onClick={()=>void change('/enable','POST',{})}>保留原分工，启用五角色流程</button>:<p>请联系作品管理者启用。</p>}</section>}
    {data?.enabled&&<>
      <ProductionReviews key={pid} productionId={pid} request={request}/>
      <StoryboardAssetRequests key={`assets:${pid}:${data.config.revision}`} productionId={pid} request={request}/>
      <EpisodeDeliveries key={`delivery:${pid}:${data.config.revision}`} episodes={data.episodes} actorId={data.actor_id} roles={data.my_roles} request={request}/>
      <EpisodeSamples key={`samples:${pid}:${data.config.revision}`} episodes={data.episodes} request={request}/>
      <section><h2>作品成员与角色</h2><p>我的角色：{data.my_roles.map((r:string)=>ROLES[r]).join('、')||'只读成员'}</p>
        {data.can_manage?<>{data.members.map((m:V)=><RoleForm key={`${m.id}:${data.config.revision}`} member={m} busy={busy}
          save={(id,roles)=>void change(`/members/${id}`,'PUT',{roles})}/>)}
          <form className="workflow-assignment" onSubmit={e=>{e.preventDefault();if(person)void change(`/members/${person}`,'PUT',{roles:[]});}}>
            <label>添加团队成员到作品<select value={person} onChange={e=>setPerson(e.target.value)}><option value="">选择成员</option>
              {data.available_members.filter((m:V)=>!data.members.some((existing:V)=>existing.id===m.id)).map((m:V)=><option key={m.id} value={m.id}>{m.nickname}</option>)}</select></label>
            <button disabled={busy||!person}>加入作品后分配角色</button></form></>:data.members.map((m:V)=><p key={m.id}>{m.nickname}：{m.roles.map((r:string)=>ROLES[r]).join('、')||'只读成员'}</p>)}
      </section>
      <section><h2>作品默认负责人</h2><p>只决定后续新增内容，不转交已有内容。同角色只有一人时自动采用该人；多人时请明确设置。</p>
        {['writer','artist','editor'].map(role=>data.can_manage?<AssignSelect key={`${role}:${data.config.revision}`} label={`默认${ROLES[role]}`}
          value={data.config[role+'_id']} role={role} members={data.members} busy={busy} onSave={id=>void change('/defaults','PUT',{role,user_id:id})}/>
          :<p key={role}>{ROLES[role]}：{name(data.effective_defaults?.[role])}</p>)}
        {data.can_manage&&<p>当前新内容实际负责人：{['writer','artist','editor'].map(role=>`${ROLES[role]}：${name(data.effective_defaults?.[role])}`).join('；')}</p>}
      </section>
      <section><h2>分集负责人</h2><p>分配抽卡师会一次转交本集制作对象，不转交剧本或共享资产。剪辑师只负责素材交接与样片。</p>
        {data.episodes.map((ep:V)=><article className="workflow-episode" key={ep.id}><h3>第 {ep.episode_no} 集 · {ep.episode_title}</h3>
          {['writer','generator','editor'].map(role=>data.can_manage?<AssignSelect key={`${ep.id}:${role}:${data.config.revision}`}
            label={ROLES[role]} value={ep[role+'_id']} role={role} members={data.members} busy={busy} allowDefault={role!=='generator'}
            onSave={id=>void change(`/episodes/${ep.id}`,'PUT',{role,user_id:id})}/>:<p key={role}>{ROLES[role]}：{name(ep['effective_'+role+'_id']||ep[role+'_id'])}</p>)}
        </article>)}
      </section>
      <section><h2>章节与共享资产分工</h2><p>多人编剧或资产师在这里按业务内容批量分工，不需要挑选内部协作对象。</p>
        <label>工作范围<select value={kind} onChange={e=>{setKind(e.target.value);setSelected([]);setTarget('');}}><option value="chapter">原著章节</option><option value="visual_card">共享资产</option></select></label>
        <div className="workflow-items">{data.items.filter((item:V)=>item.kind===kind).map((item:V)=><label key={item.id}>
          {data.can_manage&&<input type="checkbox" disabled={busy} checked={selected.includes(item.id)} onChange={e=>setSelected(old=>e.target.checked?[...old,item.id]:old.filter(id=>id!==item.id))}/>}
          <span>{item.source_title?`${item.source_title} · `:''}{item.title}</span><small>{name(item.assignee_id)}</small></label>)}</div>
        {data.can_manage&&<div className="workflow-assignment"><label>将选中内容分配给<select value={target} onChange={e=>setTarget(e.target.value)}><option value="">待分配</option>
          {data.members.filter((m:V)=>m.is_active&&m.roles.includes(kind==='chapter'?'writer':'artist')).map((m:V)=><option key={m.id} value={m.id}>{m.nickname}</option>)}</select></label>
          <button disabled={busy||!selected.length||selected.length>200} onClick={()=>void change('/assign','POST',{kind,user_id:target||null,
            items:data.items.filter((v:V)=>selected.includes(v.id)).map((v:V)=>({id:v.id,revision:v.revision,assignment_epoch:v.assignment_epoch}))})}>分配选中的 {selected.length} 项</button></div>}
      </section>
    </>}
  </main>;
}
