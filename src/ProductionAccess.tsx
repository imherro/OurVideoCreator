import {useEffect,useState} from 'react';

type V=Record<string,any>;
type Request=(path:string,options?:RequestInit)=>Promise<any>;
const roles:Record<string,string>={producer:'制片人',writer:'编剧',artist:'资产师',generator:'抽卡师',editor:'剪辑师'};
const send=(method:string,value?:V):RequestInit=>({method,headers:{'Content-Type':'application/json'},body:value?JSON.stringify(value):undefined});

/** Team administration stays separate from production business roles. */
export function ProductionAccess({productions,request}:{productions:V[];request:Request}){
  const [pid,setPid]=useState(''),[state,setState]=useState<V|null>(null),[members,setMembers]=useState<V[]>([]);
  const [user,setUser]=useState(''),[role,setRole]=useState('viewer'),[error,setError]=useState('');
  const [busy,setBusy]=useState(false),[remove,setRemove]=useState<V|null>(null);
  const selected=productions.find(p=>p.id===pid),path=`/productions/${pid}`;
  useEffect(()=>{setPid(old=>productions.some(p=>p.id===old)?old:productions[0]?.id||'');},[productions]);
  useEffect(()=>{
    let alive=true;setState(null);setMembers([]);setError('');setRemove(null);setUser('');
    if(pid)Promise.all([request(path+'/workflow'),request(path+'/members')]).then(([workflow,rows])=>{
      if(alive){setState(workflow);setMembers(rows);}
    }).catch(e=>{if(alive)setError(e.message);});
    return()=>{alive=false;};
  },[pid]);
  const canManage=state&&(state.enabled?state.can_manage:['owner','manager'].includes(selected?.role));
  async function mutate(suffix:string,method:string,value?:V){
    setBusy(true);setError('');
    try {
      await request(path+suffix,send(method,value));
      const [workflow,rows]=await Promise.all([request(path+'/workflow'),request(path+'/members')]);
      setState(workflow);setMembers(rows);setRemove(null);setUser('');
    }catch(e:any){setError(e.message||'操作失败，请重新载入核对');}
    finally{setBusy(false);}
  }
  return <section><h2>作品成员</h2>
    {productions.length?<select aria-label="选择作品" disabled={busy} value={pid} onChange={e=>setPid(e.target.value)}>
      {productions.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</select>:<p>当前团队没有你可见的作品。</p>}
    {error&&<p role="alert" className="error">{error}</p>}
    {state?.enabled?<p>本作品使用五角色分工。<a href={`/workflow?production=${encodeURIComponent(pid)}`}>管理业务角色和分集负责人</a>，不需要设置 manager/editor。</p>
      :state&&canManage?<div className="inline-fields"><input placeholder="团队成员 user_id" value={user} disabled={busy} onChange={e=>setUser(e.target.value)}/>
        <select value={role} disabled={busy} onChange={e=>setRole(e.target.value)}>{['viewer','editor','manager'].map(r=><option key={r} value={r}>{r}</option>)}</select>
        <button disabled={busy||!user.trim()} onClick={()=>void mutate(`/members/${encodeURIComponent(user.trim())}`,'PUT',{role})}>授权作品</button>
        <a href={`/workflow?production=${encodeURIComponent(pid)}`}>启用五角色流程</a></div>:null}
    {remove&&<div role="alert"><p>确认将 {remove.nickname} 移出本作品？业务角色、编辑权限及相关租约将撤销，内容与历史保留。</p>
      <button disabled={busy} onClick={()=>void mutate(`/members/${remove.id}`,'DELETE')}>确认移出作品</button>
      <button disabled={busy} onClick={()=>setRemove(null)}>取消</button></div>}
    <div className="admin-list">{members.map(m=><div key={m.id}><b>{m.nickname}</b>
      <em>{state?.enabled?(state.members.find((entry:V)=>entry.id===m.id)?.roles||[]).map((r:string)=>roles[r]).join('、')||'只读成员':m.role}</em>
      {canManage&&<button disabled={busy} className="danger" onClick={()=>setRemove(m)}>移出作品</button>}
    </div>)}</div>
  </section>;
}
