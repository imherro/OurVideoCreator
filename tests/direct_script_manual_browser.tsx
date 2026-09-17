import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {ScriptRoomPage} from '../src/pages/ScriptRoomPage';
import {ProjectSetupDialog} from '../src/pages/ProjectSetupDialog';
import {OwnedContentDrafts} from '../src/ownedContentDrafts';
import '../src/style.css';
const store=new OwnedContentDrafts('script');
const records:any={};
for(const number of [1,2])records[number]={project_id:'mock-'+number,revision:1,assignment_epoch:1,assignee_id:'me',
 status:'draft',title:'直接集 '+number,synopsis:'',body:'',estimatedDuration:15,sourceChapterRefs:[],storyGoal:'',paywallBeat:{},characters:[],scenes:[],props:[],metadata:{adaptationLinked:false}};
async function request(path:string,options?:RequestInit){
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
 return <main><p role="status">{notice} · 起点：{mode}</p>{setup?<ProjectSetupDialog providers={[]} localModels={[]} onCreate={async draft=>{setMode(draft.creationMode);setSetup(false)}}/>:
  <ScriptRoomPage productionId="mock" currentEpisodeNo={active} providers={[]} store={store} actorId="me" canManage canEdit request={request}
   notify={setNotice} report={error=>setNotice(String(error))} onChanged={()=>{}} onSelectEpisode={setActive} onEnterEpisode={no=>setNotice('进入分镜规划 EP'+no)}/>}
 </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
