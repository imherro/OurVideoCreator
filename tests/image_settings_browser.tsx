import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {ImageGenerationSettings} from '../src/ImageGenerationSettings';
import {patchNode} from '../src/graph';
import '../src/style.css';
const models=[{id:'native',kind:'image',type:'maestro',name:'隔离测试模型',rules:{resolution:{type:'string'},seed:{type:'integer',min:-1,max:100}},defaults:{resolution:'2048x1152',seed:-1}},
 {id:'cloud',kind:'image',type:'runninghub',name:'隔离云端模型',rules:{size:{type:'string'}},defaults:{size:'2048x1152'}}];
let previews=0;
async function request(path:string,init?:RequestInit){
 if(path==='/models')return {models};
 if(!path.endsWith('/image-spec'))throw new Error('Unexpected route');
 previews++;
 const body=JSON.parse(String(init?.body)),settings=body.imageSettings;
 if(body.model_id==='cloud'&&(settings.sizeMode==='custom'||body.parameters.seed!==undefined))throw new Error('此模型不支持保留的尺寸或种子，请调整或恢复项目默认');
 if(settings.sizeMode==='custom'&&!/^\d+x\d+$/.test(settings.size))throw new Error('自定义尺寸格式无效');
 return {ratio:body.ratio,size:settings.sizeMode==='custom'?settings.size:'2048x1152',seed:settings.seed??-1,seedSupported:body.model_id==='native',
  sizeOptions:[{value:'project',label:'跟随项目画幅 · 推荐尺寸'},...(body.model_id==='native'?[{value:'custom',label:'自定义像素尺寸'}]:[])],
  parameters:{...body.parameters,...(settings.sizeMode==='custom'?{resolution:settings.size}:{})},sizeNote:'隔离模拟预览，没有调用业务后端或供应商。'};
}
function App(){
 const [surface,setSurface]=useState('分镜列表'),[changes,setChanges]=useState(0);
 const [document,setDocument]=useState<any>({ratio:'16:9',videoResolution:'720p',generationPolicy:{image:{model_id:'native'}},
  nodes:[{id:'image',data:{kind:'image',model_id:'native',parameters:{resolution:'2048x1152',seed:-1},assetId:'kept-original'}}],edges:[]});
 return <main style={{padding:24,maxWidth:720,margin:'auto'}}><h1>图片设置隔离测试</h1>
  <p>当前入口：{surface} · 本地修改次数：{changes}</p><button onClick={()=>setSurface(surface==='分镜列表'?'高级画布':'分镜列表')}>切换入口</button>
  <ImageGenerationSettings key={surface} projectId="mock" document={document} node={document.nodes[0]} models={models} request={request}
   onChange={patch=>{setChanges(v=>v+1);setDocument((d:any)=>patchNode(d,'image',patch))}}/>
  <pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(document.nodes[0].data,null,2)}</pre><small>模拟预览次数（下次重绘更新）：{previews}</small>
 </main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
