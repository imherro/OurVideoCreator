import {useEffect,useState} from 'react';
type V=Record<string,any>;
const names:Record<string,string>={producer:'制片人',writer:'编剧',artist:'资产师',generator:'抽卡师',editor:'剪辑师'};
export function RoleWorkInbox({productionId,request,onOpen}:{productionId:string;request:(path:string)=>Promise<any>;onOpen:(task:V)=>Promise<void>}){
  const [data,setData]=useState<V|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[refresh,setRefresh]=useState(0);
  useEffect(()=>{let alive=true;setData(null);setError('');request(`/productions/${productionId}/workflow/tasks`).then(value=>{if(alive)setData(value);})
    .catch(e=>{if(alive)setError(e.message);});return()=>{alive=false;};},[productionId,refresh]);
  async function open(task:V){setBusy(true);setError('');try{await onOpen(task);}catch(e:any){setError(e.message);}finally{setBusy(false);}}
  return <section aria-label="我的工作"><h2>我的工作</h2><p>按当前职责和实际分工安排；一人兼任时合并显示，不改变任何编辑权限。</p>
    <button disabled={busy} onClick={()=>setRefresh(v=>v+1)}>刷新我的工作</button>
    {error&&<p role="alert">{error}，请刷新后重试。</p>}
    {!data&&!error&&<p>正在核对当前分工和交接状态…</p>}
    {data&&<p>当前职责：{data.roles?.map((role:string)=>names[role]).join('、')||'只读成员'}</p>}
    {data&&!data.tasks.length&&<p>暂无分配给你的工作。可以查看作品内容；需要制作时，请联系制片人安排业务角色和负责人。</p>}
    {data?.tasks.map((task:V,index:number)=><article className="workflow-episode" key={`${task.role}:${task.project_id}:${task.stage}:${index}`}>
      <h3>{task.title} <small>· {names[task.role]}</small></h3><p>{task.next_step}</p>
      {task.recipient&&<p>交接对象：{task.recipient}</p>}<button disabled={busy} onClick={()=>void open(task)}>打开：{task.title}</button>
    </article>)}
  </section>;
}
