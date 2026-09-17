import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {AdaptationPage} from '../src/pages/AdaptationPage';
import {ScriptRoomPage} from '../src/pages/ScriptRoomPage';
import {OwnedContentDrafts} from '../src/ownedContentDrafts';
import {createEpisodePlans} from '../src/adaptation';
import '../src/style.css';

const chapters=[
  {id:'chapter-1',display_no:1,title:'山门旧约'},
  {id:'chapter-2',display_no:2,title:'夜雨来客'},
  {id:'chapter-3',display_no:3,title:'尚未分配的密信'},
];
const plans=createEpisodePlans(3,60);
plans[0]={...plans[0],status:'approved',sourceChapterRefs:['chapter-1'],logline:'旧约开端'};
plans[1]={...plans[1],status:'review',sourceChapterRefs:['chapter-2'],logline:'夜雨冲突'};
plans[2]={...plans[2],status:'draft',sourceChapterRefs:[],logline:'待写第三集'};
let remote:any={
  revision:7,sourceEventCount:12,protectedEpisodeNos:[1],
  adaptationPlan:{status:'draft',format:{episodeCount:3,targetDuration:60,ratio:'16:9',platform:'抖音'},
    storyCore:{premise:'服务器原始前提',theme:'',protagonist:'',goal:'',stakes:''},
    storyArc:{opening:'',development:'',turningPoint:'',climax:'',ending:''},
    adaptationStrategy:{audience:'',tone:'',changes:'',constraints:''}},
  episodePlans:plans,
  monetizationPlan:{mode:'free',freeEpisodes:1,firstPaywallEpisode:2,beats:[]},
};
const clone=<T,>(value:T):T=>structuredClone(value);
const scriptStore=new OwnedContentDrafts('script');
function defaultScript(no:number){
  const plan=remote.episodePlans.find((item:any)=>item.episodeNo===no);
  return {project_id:no<=2?'episode-'+no:null,revision:0,assignment_epoch:0,assignee_id:'tester',status:'draft',
    title:`第 ${String(no).padStart(2,'0')} 集`,synopsis:plan?.logline||'',body:'',estimatedDuration:plan?.targetDuration||60,
    sourceChapterRefs:plan?.sourceChapterRefs||[],storyGoal:plan?.coreConflict||'',paywallBeat:{},characters:[],scenes:[],props:[],metadata:{adaptationLinked:true}};
}
async function request(path:string,options?:RequestInit){
  if(path.endsWith('/adaptation')&&options?.method==='PUT'){
    const body=JSON.parse(String(options.body||'{}'));
    remote={...remote,...body,revision:remote.revision+1,sourceEventCount:remote.sourceEventCount,protectedEpisodeNos:remote.protectedEpisodeNos};
    return clone(remote);
  }
  if(path.endsWith('/adaptation'))return clone(remote);
  if(path.endsWith('/chapters'))return clone(chapters);
  if(path.endsWith('/scripts'))return remote.episodePlans.map((plan:any)=>({episodeNo:plan.episodeNo,projectId:plan.episodeNo<=2?'episode-'+plan.episodeNo:null,
    episodeTitle:`第 ${String(plan.episodeNo).padStart(2,'0')} 集`,plan:clone(plan),script:plan.episodeNo<=2?defaultScript(plan.episodeNo):null}));
  const script=/\/episode-scripts\/(\d+)$/.exec(path);
  if(script)return clone(defaultScript(Number(script[1])));
  throw new Error('隔离页禁止此请求：'+path);
}
function App(){
  const [stage,setStage]=useState<'adaptation'|'script'>('adaptation');
  const [focus,setFocus]=useState(3),[refreshKey,setRefreshKey]=useState(0),[notice,setNotice]=useState('内存 Mock；不访问业务数据库或 Provider');
  const [adaptationDirty,setAdaptationDirty]=useState(false);
  const changeStage=(next:'adaptation'|'script')=>{
    if(stage==='adaptation'&&next!==stage&&adaptationDirty){setNotice('改编策划仍有未保存修改；阶段切换已阻止');return;}
    setStage(next);
  };
  const serverRefresh=()=>{
    remote={...remote,revision:remote.revision+1,adaptationPlan:{...remote.adaptationPlan,
      storyCore:{...remote.adaptationPlan.storyCore,premise:'服务器后台更新，不应覆盖本地输入'}}};
    setRefreshKey(value=>value+1);
  };
  return <main>
    <nav className="settings-actions"><button onClick={()=>changeStage('adaptation')}>改编工作台</button><button onClick={()=>changeStage('script')}>剧本室</button>
      <button onClick={serverRefresh}>模拟后台刷新</button><b id="harness-state">阶段 {stage} · 焦点 EP{String(focus).padStart(2,'0')} · {adaptationDirty?'有草稿':'已保存'}</b></nav>
    <p role="status">{notice}</p>
    {stage==='adaptation'?<AdaptationPage productionId="mock-production" projectId="episode-1" focusedEpisodeNo={focus} onSelectEpisode={setFocus}
      providers={[]} refreshKey={refreshKey} request={request} notify={setNotice} report={error=>setNotice(String(error))}
      onDirtyChange={setAdaptationDirty} onRevision={()=>{}} onOpenSource={()=>setNotice('隔离页不进入原著页')}/>:
      <ScriptRoomPage productionId="mock-production" currentEpisodeNo={focus} onFocusEpisode={setFocus} providers={[]} store={scriptStore}
        actorId="tester" canManage canEdit request={request} notify={setNotice} report={error=>setNotice(String(error))} onChanged={()=>{}}
        onSelectEpisode={setFocus} onEnterEpisode={()=>{}}/>}
  </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
