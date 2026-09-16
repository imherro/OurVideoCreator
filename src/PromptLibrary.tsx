import {useEffect,useState} from 'react';
import {Plus,Save,RefreshCw,Trash2} from 'lucide-react';

type Template={id:string;name:string;kind:string;content:string;version:number;deleted?:boolean;history?:Template[]};
type Library={revision:number;templates:Template[]};
const names:Record<string,string>={text:'剧本',storyboard:'分镜',image:'图像',video:'视频'};
export function PromptLibrary({templates,request,newId,onApply,canManage=false}:{templates:Record<string,string>;request:(path:string,options?:RequestInit)=>Promise<any>;newId:()=>string;onApply:(kind:string,content:string)=>void;canManage?:boolean}){
 const [library,setLibrary]=useState<Library>({revision:0,templates:[]});
 const [draft,setDraft]=useState<Template|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[ready,setReady]=useState(false);
 async function refresh(){try{setLibrary(await request('/prompt-library'));setReady(true);setError('')}catch(e:any){setError(e.message)}}
 useEffect(()=>{refresh()},[]);
 async function save(deleted=false){if(!draft||!canManage)return;setBusy(true);try{const result=await request('/admin/prompt-templates/'+draft.id,{method:'PUT',body:JSON.stringify({name:draft.name,kind:draft.kind,content:draft.content,revision:library.revision,deleted})});setLibrary(result);setDraft(null);setError('')}catch(e:any){setError(e.message)}finally{setBusy(false)}}
 return <><p className="muted">平台模板由管理员统一维护，普通成员只读。剧本与分镜模板作为阶段规则；图像与视频模板填入创作描述。应用不会提交生成。</p>
 <div className="settings-actions">{canManage&&<button disabled={!ready} onClick={()=>setDraft({id:newId(),name:'新模板',kind:'text',content:'',version:0})}><Plus size={15}/>新建模板</button>}<button onClick={refresh}><RefreshCw size={15}/>刷新模板库</button></div>
 {error&&<div className="error">{error}</div>}
 {draft&&<article className="template-editor"><label>模板名称<input value={draft.name} onChange={e=>setDraft({...draft,name:e.target.value})}/></label><label>用途<select value={draft.kind} onChange={e=>setDraft({...draft,kind:e.target.value})}>{Object.entries(names).map(([k,n])=><option value={k} key={k}>{n}</option>)}</select></label><label>模板内容<textarea className="prompt-input" value={draft.content} onChange={e=>setDraft({...draft,content:e.target.value})}/></label>
 {!!draft.history?.length&&<label>载入历史版本<select defaultValue="" onChange={e=>{const old=draft.history?.find(v=>String(v.version)===e.target.value);if(old)setDraft({...draft,name:old.name,kind:old.kind,content:old.content})}}><option value="" disabled>恢复为草稿，保存后创建新版本</option>{draft.history.map(v=><option key={v.version} value={v.version}>版本 {v.version} · {v.name}</option>)}</select></label>}
 <div className="settings-actions"><button className="primary" disabled={busy||!draft.content.trim()||!draft.name.trim()} onClick={()=>save()}><Save size={15}/>保存模板</button><button onClick={()=>setDraft(null)}>关闭草稿</button>{draft.version>0&&<button disabled={busy} onClick={()=>save(true)}><Trash2 size={15}/>归档</button>}</div></article>}
 <h3>平台模板</h3>{library.templates.filter(t=>!t.deleted).map(t=><article className="template-card" key={t.id}><h3>{t.name} <small>v{t.version} · {names[t.kind]}</small></h3><p>{t.content}</p><button onClick={()=>onApply(t.kind,t.content)}>应用</button>{canManage&&<button onClick={()=>setDraft({...t})}>编辑 / 历史</button>}</article>)}
 {!library.templates.some(t=>!t.deleted)&&<p className="muted">暂无已发布的平台模板，可先使用下方内置模板。</p>}
 {canManage&&library.templates.some(t=>t.deleted)&&<details><summary>已归档模板</summary>{library.templates.filter(t=>t.deleted).map(t=><button key={t.id} onClick={()=>setDraft({...t})}>{t.name} · 编辑并恢复</button>)}</details>}
 <h3>内置模板</h3>{Object.entries(templates).map(([kind,content])=><article className="template-card" key={kind}><h3>{names[kind]}</h3><p>{content}</p><button onClick={()=>onApply(kind,content)}>应用</button>{canManage&&<button disabled={!ready} onClick={()=>setDraft({id:newId(),name:names[kind]+' · 平台模板',kind,content,version:0})}>复制并编辑</button>}</article>)}
 </>;
}
