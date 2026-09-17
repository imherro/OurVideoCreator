import {useEffect,useState} from 'react';
import {ModelSelector} from './ModelSelector';
import {nodeDefaults} from './nodeDefaults';
import './imageGenerationSettings.css';

type Value=Record<string,any>;
type Props={node:Value;document:Value;projectId:string;models:Value[];
 request:(path:string,init?:RequestInit)=>Promise<any>;onChange:(patch:Value)=>void};

/** The same node settings are used by canvas, storyboard table and grid. */
export function ImageGenerationSettings(props:Props){
 const {node,document,projectId,models,request,onChange}=props;
 const data=node.data,settings=data.imageSettings||{};
 const [open,setOpen]=useState(false),[result,setResult]=useState<Value>(),[error,setError]=useState('');
 const [options,setOptions]=useState<Value[]>([{value:'project',label:'跟随项目画幅 · 推荐尺寸'}]);
 const [seedSupported,setSeedSupported]=useState(false);
 useEffect(()=>{
  setOptions([{value:'project',label:'跟随项目画幅 · 推荐尺寸'}]);setSeedSupported(false);
 },[data.model_id]);
 const model=models.find(item=>item.id===data.model_id);
 const body=JSON.stringify({node_id:node.id,model_id:data.model_id||'',node_data:data,
  parameters:{...model?.defaults,...data.parameters},
  imageSettings:settings,ratio:document.ratio,videoResolution:document.videoResolution});
 useEffect(()=>{
  if(!open)return;
  let active=true;
  setResult(undefined);setError('');
  const timer=window.setTimeout(()=>{
   request(`/projects/${projectId}/image-spec`,{method:'POST',headers:{'Content-Type':'application/json'},body})
    .then(spec=>{if(active){setResult({key:body,spec});setOptions(spec.sizeOptions);setSeedSupported(spec.seedSupported)}})
    .catch(reason=>{if(active)setError(reason.message||String(reason))});
  },250);
  return()=>{active=false;window.clearTimeout(timer)};
 },[open,body,projectId,request]);
 const spec=result?.key===body?result.spec:undefined;
 const change=(patch:Value)=>onChange({imageSettings:{...settings,...patch}});
 function reset(){
  try{
   onChange({...nodeDefaults('image',models,[],document.generationPolicy),imageSettings:{sizeMode:'project'},
    provider:undefined,model:undefined,resolution:undefined,seed:undefined});
  }catch(reason:any){setError(reason.message||String(reason))}
 }
 return <details className="image-generation-settings" open={open} onToggle={event=>setOpen(event.currentTarget.open)}>
  <summary>图片生成设置与提交规格</summary>
  {open&&<div className="image-generation-settings-body">
   <ModelSelector data={{...data,kind:'image'}} providers={models} modelPool={document.modelPool} request={request} onChange={onChange} preserveParameters
    hideControl={(name,rule,model)=>['size','ratio','aspect_ratio','seed'].includes(name)
      ||(name==='resolution'&&(['maestro','comfy'].includes(model.type)||rule.enum?.some((v:any)=>/^\d+x\d+$/.test(String(v)))))} />
   <p className="muted">切换模型保留当前图片设置；不兼容时请调整或显式恢复项目默认。设置通过原对象保存流程生效，提交前须保存成功。</p>
   <label>图片尺寸<select aria-label="图片尺寸模式" value={settings.sizeMode||'project'} onChange={e=>change({sizeMode:e.target.value})}>
    {!options.some(item=>item.value===(settings.sizeMode||'project'))&&<option value={settings.sizeMode}>{settings.sizeMode}（当前模型可能不支持）</option>}
    {options.map(item=><option key={item.value} value={item.value}>{item.label}</option>)}
   </select></label>
   {settings.sizeMode==='custom'&&<label>宽×高<input aria-label="自定义图片尺寸" placeholder="1280x720" value={settings.size||''} onChange={e=>change({size:e.target.value})}/></label>}
   {(seedSupported||settings.seed!==undefined||model?.rules?.seed)&&<label>种子（-1为随机）<input aria-label="图片随机种子" type="number" min={-1} max={2147483647} step={1}
    value={settings.seed??data.parameters?.seed??-1} onChange={e=>change({seed:Number(e.target.value)})}/></label>}
   {!seedSupported&&<small>当前未确认固定种子能力；不会把未实现的种子设置当作生效。</small>}
   <button type="button" className="quiet" onClick={reset}>恢复项目默认</button>
   {error?<p className="error" role="alert">规格校验：{error}</p>:spec?<div role="status">
    <p>本次预览：{spec.ratio} · {spec.size||'未发布像素尺寸控制'} · {spec.seedSupported?(spec.seed===-1?'提交时冻结随机种子':`种子 ${spec.seed??'未设置'}`):'供应商控制随机性'}</p>
    <small>{spec.sizeNote} 视频输出规格：{document.videoResolution||'720p'}。</small>
    <details><summary>实际解析参数（只读预览，不排任务）</summary><pre>{JSON.stringify(spec.parameters,null,2)}</pre></details>
   </div>:<p className="muted">正在校验本地提交规格…</p>}
  </div>}
 </details>;
}
