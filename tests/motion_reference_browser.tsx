import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {MotionReferenceEditor} from '../src/components/MotionReferenceEditor';
import '../src/style.css';
const models=[{id:'mock',capabilities:{multimodal_reference:true}}];
const assets=[{id:'motion',kind:'video',name:'测试动作视频（没有业务素材）'}];
async function request(path:string,init?:RequestInit){
 if(!path.endsWith('/video-spec'))throw new Error('隔离页禁止其他请求');
 const body=JSON.parse(String(init?.body));
 const mode=body.shot.videoReferenceMode||body.videoReferenceMode;
 if(mode!=='multimodal'&&body.shot.motionReference)throw new Error('严格帧模式不能混入动作视频；绑定已保留');
 return {generation_mode:{actual:mode},planned_shot_duration:2,shot_duration:4,
  motion_reference:body.shot.motionReference?{media:{duration:2}}:null,
  reference_manifest:body.shot.motionReference?[{kind:'video',index:1,name:assets[0].name,audio:'stripped'}]:[],
  prompt:'隔离 Mock 预览，不调用供应商。'+('中文长提示词用于检验折行与阅读；'.repeat(35)),parameters:{duration:4,ratio:'16:9'}};
}
function App(){
 const [changes,setChanges]=useState(0),[busy,setBusy]=useState(true);
 const [shot,setShot]=useState<any>({id:'s',duration:2,video_prompt:'人物走动',motionReference:{assetId:'motion',cameraMode:'use_shot_camera'}});
 return <main style={{padding:20,maxWidth:700,margin:'auto'}}><h1>动作参考隔离测试</h1>
  <p>生成状态：{busy?'运行中':'空闲'} · 本地修改次数：{changes} · 素材数：{assets.length}</p>
  <button onClick={()=>setBusy(!busy)}>切换生成状态</button><button disabled={busy}>生成（隔离页不执行）</button>
  <MotionReferenceEditor document={{videoReferenceMode:'multimodal'}} shot={shot} node={{id:'v',data:{model_id:'mock',prompt:'人物走动'}}}
   assets={assets} models={models} projectId="mock" request={request} onUploaded={()=>{throw new Error('隔离页不上传')}}
   onPatch={patch=>{setChanges(n=>n+1);setShot((old:any)=>({...old,...patch}))}}/>
  <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(shot,null,2)}</pre>
 </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
