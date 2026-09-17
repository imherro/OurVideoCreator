import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {MotionReferenceEditor} from '../src/components/MotionReferenceEditor';
import '../src/style.css';
const models=[{id:'mock',capabilities:{multimodal_reference:true,voice_sample_reference:true}}];
const assets=[{id:'motion',kind:'video',name:'历史绑定视频（无业务素材）'},
 {id:'fixture-sample',kind:'audio',name:'合成静音测试样本'},
 {id:'fixture-frame',kind:'image',name:'合成测试图片'},
 {id:'dedicated',kind:'video',name:'白模动作参考',category:'motion_reference'},
 {id:'ordinary',kind:'video',name:'不应列出的普通视频'},
 {id:'derived',kind:'video',name:'不应列出的衍生视频',category:'motion_reference',metadata:{motionDerivedFrom:'motion'}}];
let compileCount=0;
async function request(path:string,init?:RequestInit){
 if(!path.endsWith('/video-spec'))throw new Error('隔离页禁止其他请求');
 const body=JSON.parse(String(init?.body));
 const mode=body.shot.videoReferenceMode||body.videoReferenceMode;
 if(mode!=='multimodal'&&body.shot.motionReference)throw new Error('严格帧模式不能混入动作视频；绑定已保留');
 return {generation_mode:{actual:mode},planned_shot_duration:2,shot_duration:4,
  motion_reference:body.shot.motionReference?{media:{duration:2}}:null,
  reference_manifest:[{kind:'image',index:1,assetId:'fixture-frame',name:'合成测试图片'},
   {kind:'audio',index:1,assetId:'fixture-sample',name:'合成静音测试样本'},
   {kind:'image',index:2,source:{jobId:'pending'},name:'计划生成图片'},
   {kind:'audio',index:2,assetIds:['fixture-sample'],name:'尚未混合的对白'}],
  prompt:`编译次数 ${++compileCount}。隔离 Mock 预览，不调用供应商。\n[镜头]\n外观参考@图片1，声音参考@音频1。计划引用@图片2及@音频2不可冒充已有素材。\n`+('中文长提示词用于检验折行与阅读；'.repeat(10))+'\n[/镜头]',parameters:{duration:4,ratio:'16:9'}};
}
function App(){
 const [changes,setChanges]=useState(0),[busy,setBusy]=useState(true);
 const [confirmed,setConfirmed]=useState(true),[removed,setRemoved]=useState(false);
 const [shot,setShot]=useState<any>({id:'s',duration:2,video_prompt:'人物走动',dialogues:[{characterCardId:'hero',characterName:'测试角色',text:'真实对白不等于试听'}],motionReference:{assetId:'motion',cameraMode:'use_shot_camera'}});
 return <main style={{padding:20,maxWidth:700,margin:'auto'}}><h1>动作参考隔离测试</h1>
  <p>生成状态：{busy?'运行中':'空闲'} · 本地修改次数：{changes} · 素材数：{assets.length}</p>
  <button onClick={()=>setBusy(!busy)}>切换生成状态</button><button disabled={busy}>生成（隔离页不执行）</button>
  <button onClick={()=>setConfirmed(!confirmed)}>切换样本版本匹配（仅测试数据）</button>
  <button onClick={()=>setRemoved(!removed)}>切换图片可访问性（仅测试数据）</button>
  <MotionReferenceEditor busy={busy} document={{videoReferenceMode:'multimodal',dialogueMode:'voice_sample',filmBible:{voices:{profiles:{hero:{status:'locked',version:1,referenceVersion:confirmed?1:0,referenceAssetId:'fixture-sample'}}}}}} shot={shot} node={{id:'v',data:{model_id:'mock',prompt:'人物走动'}}}
   assets={removed?assets.filter(asset=>asset.id!=='fixture-frame'):assets} models={models} projectId="mock" request={request} onUploaded={()=>{throw new Error('隔离页不上传')}}
   onPatch={patch=>{setChanges(n=>n+1);setShot((old:any)=>({...old,...patch}))}}/>
  <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(shot,null,2)}</pre>
 </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
