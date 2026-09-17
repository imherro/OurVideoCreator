import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {ScriptRoomPage} from '../src/pages/ScriptRoomPage';
import {ProjectSetupDialog} from '../src/pages/ProjectSetupDialog';
import {EpisodeSetupDialog} from '../src/pages/EpisodeSetupDialog';
import {WorkflowStageNav} from '../src/app/WorkflowStageNav';
import type {WorkflowStage} from '../src/app/workflow';
import {OwnedContentDrafts} from '../src/ownedContentDrafts';
import '../src/style.css';
const store=new OwnedContentDrafts('script');
const records:any={};
let assistCount=0;
for(const number of [1,2])records[number]={project_id:'mock-'+number,revision:1,assignment_epoch:1,assignee_id:'me',
 status:'draft',title:'直接集 '+number,synopsis:'',body:'',estimatedDuration:15,sourceChapterRefs:[],storyGoal:'',paywallBeat:{},characters:[],scenes:[],props:[],metadata:{adaptationLinked:false}};
async function request(path:string,options?:RequestInit){
 const assist=/\/episode-scripts\/(\d+)\/assist$/.exec(path);
 if(assist){const body=JSON.parse(String(options?.body||'{}'));if(body.revision!==records[assist[1]].revision)throw new Error('测试版本冲突');
  document.getElementById('assist-counter')!.textContent=`辅助提交 ${++assistCount} 次 · EP${assist[1]} · ${body.instruction}`;
  return {id:'mock-assist-'+assistCount,status:'queued'};}
 if(path.endsWith('/scripts'))return Object.entries(records).map(([no,script])=>({episodeNo:Number(no),projectId:(script as any).project_id,episodeTitle:'直接集 '+no,plan:null,script:structuredClone(script)}));
 if(path.endsWith('/chapters')||path.endsWith('/comments')||path.endsWith('/history'))return [];
 if(path.endsWith('/members'))return [{id:'me',nickname:'隔离测试负责人',role:'manager'}];
 const match=/\/episode-scripts\/(\d+)(?:\/(review|approve))?$/.exec(path);
 if(match){const row=records[match[1]],body=JSON.parse(String(options?.body||'{}'));
  if(options?.method){if(body.revision!==row.revision)throw Object.assign(new Error('测试版本冲突'),{status:409});
   if(match[2]==='approve'&&row.status!=='review')throw new Error('须先提交审核');
   Object.assign(row,body,{revision:row.revision+1,status:match[2]==='approve'?'approved':match[2]==='review'?'review':'draft'});}
  return structuredClone(row);
 }
 throw new Error('隔离页禁止此请求：'+path);
}
function App(){const [setup,setSetup]=useState(true),[active,setActive]=useState(1),[notice,setNotice]=useState('只有内存Mock，无业务库/供应商'),[mode,setMode]=useState('');
 const [adding,setAdding]=useState(false);
 const [stage,setStage]=useState<WorkflowStage>('script');
 return <main><p role="status">{notice} · 起点：{mode} · 当前导航：{stage}</p><p id="assist-counter">辅助提交 0 次</p>
 {!setup&&<WorkflowStageNav active={stage} directCreation={mode==='direct'} onChange={setStage}/>}
 {setup?<ProjectSetupDialog providers={[]} localModels={[]} onCreate={async draft=>{setMode(draft.creationMode);setSetup(false)}}/>:
  <ScriptRoomPage productionId="mock" currentEpisodeNo={active} onFocusEpisode={setActive} providers={[{id:'mock-text',kind:'text',name:'隔离 Mock 文本模型'}]} defaultTarget={{model_id:'mock-text'}} store={store} actorId="me" canManage canEdit request={request}
   notify={setNotice} report={error=>setNotice(String(error))} onChanged={()=>{}} onSelectEpisode={setActive} onEnterEpisode={no=>setNotice('进入分镜规划 EP'+no)} onAddEpisode={()=>setAdding(true)}/>}
 {adding&&<EpisodeSetupDialog name="隔离作品" next={3} defaultMode={mode} onClose={()=>setAdding(false)}
   onCreate={async(title,nextMode)=>{setNotice(`新增请求：${title} · ${nextMode} · 不调用AI`);setAdding(false);}}/>}
 </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
