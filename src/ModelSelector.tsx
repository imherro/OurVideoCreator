import {useEffect,useState} from 'react';
import {RefreshCw} from 'lucide-react';
type Value=Record<string,any>;
export function ModelSelector({data,providers,request,onChange}:{data:Value;providers:Value[];localModels?:Value[];request:(path:string)=>Promise<any>;onChange:(patch:Value)=>void}){
 const [models,setModels]=useState<Value[]>(providers),[loading,setLoading]=useState(false),[error,setError]=useState(''),[refresh,setRefresh]=useState(0);
 const kind=data.kind==='storyboard'?'text':data.kind;
 useEffect(()=>{
  let active=true;setLoading(true);setError('');
  request('/models').then(value=>{if(active)setModels(value.models||[])}).catch(e=>{if(active){setModels([]);setError(e.message)}}).finally(()=>{if(active)setLoading(false)});
  return()=>{active=false};
 },[kind,refresh,request]);
 const available=models.filter(item=>item.kind===kind),selected=available.find(item=>item.id===data.model_id),caps=selected?.capabilities;
 function choose(id:string){
  const model=available.find(item=>item.id===id);
  onChange({model_id:id,parameters:{...model?.defaults},provider:undefined,model:undefined,
            resolution:undefined,frames:undefined,seed:undefined,
            model_capabilities:{...model?.capabilities},model_rules:{...model?.rules}});
 }
 return <>
 <div className="field-heading"><label>平台模型</label><button className="quiet" disabled={loading} onClick={()=>setRefresh(value=>value+1)}><RefreshCw size={13}/>刷新目录</button></div>
 <select aria-label="平台模型" value={data.model_id||''} onChange={e=>choose(e.target.value)}>
 <option value="">{loading?'正在读取平台目录':'请选择平台模型'}</option>
 {data.model_id&&!selected&&<option value={data.model_id} disabled>原模型不可用，请重新选择</option>}
 {available.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}
 </select>
 {!loading&&!available.length&&<p className="error">暂无已发布且可用的平台模型，请联系管理员。系统不会自动回退其他服务。</p>}
 {error&&<p className="error">{error}</p>}
 {caps&&<p className="muted">{caps.image_reference?'支持参考图':'不支持参考图'}{caps.max_references?` · 最多 ${caps.max_references} 张`:''}{caps.end_frame?' · 支持尾帧':''}{caps.audio_reference?' · 支持参考音频':''}</p>}
 {selected&&Object.entries(selected.rules||{}).filter(([,rule])=>(rule as Value).type!=='strings').map(([name,value])=>{
   const rule=value as Value,current=data.parameters?.[name]??selected.defaults?.[name]??'';
   const change=(v:any)=>onChange({parameters:{...data.parameters,[name]:v}});
   return <label key={name}>{name}
    {rule.enum?<select value={String(current)} onChange={e=>change(rule.enum.find((v:any)=>String(v)===e.target.value))}>
     <option value="" disabled>请选择允许值</option>{rule.enum.map((v:any)=><option key={String(v)} value={String(v)}>{String(v)}</option>)}
    </select>:rule.type==='boolean'?<input type="checkbox" checked={!!current} onChange={e=>change(e.target.checked)}/>:
    <input type={['number','integer'].includes(rule.type)?'number':'text'} value={current} min={rule.min} max={rule.max} maxLength={rule.max_length}
     step={rule.type==='integer'?1:'any'} onChange={e=>change(['number','integer'].includes(rule.type)?Number(e.target.value):e.target.value)}/>}
   </label>;
 })}
 </>;
}
