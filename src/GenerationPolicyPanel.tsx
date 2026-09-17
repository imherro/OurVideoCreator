import type {GenerationKind,GenerationPolicy,GenerationTarget} from './generationPolicy';
import {MODEL_POOL_KINDS,defaultProjectModelPool,targetKey,type ModelPoolKind,type ProjectModelPool} from './modelAccess.ts';

type Value=Record<string,any>;
const labels:Record<ModelPoolKind,string>={text:'文本模型',image:'图片模型',video:'视频模型',audio:'声音模型'};

export function GenerationPolicyPanel({value,modelPool,providers:models,onChange,onModelPoolChange}:{
 value:GenerationPolicy|undefined;modelPool?:Partial<ProjectModelPool>|null;providers:Value[];localModels?:Value[];
 onChange:(next:GenerationPolicy)=>void;onModelPoolChange?:(next:ProjectModelPool)=>void;
}){
 const policy=value||{text:null,image:null,video:null};
 const systemPool=defaultProjectModelPool(models);
 const pool=Object.fromEntries(MODEL_POOL_KINDS.map(kind=>[
  kind,(Array.isArray(modelPool?.[kind])?modelPool![kind]:systemPool[kind]).filter(target=>
   systemPool[kind].some(available=>available.model_id===target.model_id)),
 ])) as ProjectModelPool;
 function patchDefault(kind:GenerationKind,target:GenerationTarget|null){onChange({...policy,[kind]:target})}
 function toggle(kind:ModelPoolKind,target:GenerationTarget,checked:boolean){
  if(!onModelPoolChange)return;
  const nextTargets=checked
   ?[...pool[kind],target].filter((item,index,all)=>all.findIndex(candidate=>targetKey(candidate)===targetKey(item))===index)
   :pool[kind].filter(item=>targetKey(item)!==targetKey(target));
  onModelPoolChange({...pool,[kind]:nextTargets});
  if(kind!=='audio'&&policy[kind]?.model_id===target.model_id)patchDefault(kind,nextTargets[0]||null);
 }
 return <section className="generation-policy">
  <h3>项目可用模型</h3>
  <p className="muted">新作品默认包含创建时全部已启用的平台模型。这里只保存公开 model_id，不包含供应商、密钥或连接配置。</p>
  {MODEL_POOL_KINDS.map(kind=>{
   const options=systemPool[kind],selected=new Set(pool[kind].map(targetKey)),defaultTarget=kind==='audio'?null:policy[kind];
   return <div className="policy-row" key={kind}>
    <div className="field-heading"><b>{labels[kind]}</b><small>已选 {pool[kind].length} / {options.length}</small></div>
    {options.length?<div className="model-choice-grid">{options.map(target=>{
     const model=models.find(item=>item.id===target.model_id);
     return <label className="model-choice" key={target.model_id}><input type="checkbox" disabled={!onModelPoolChange} checked={selected.has(target.model_id)} onChange={event=>toggle(kind,target,event.target.checked)}/><span>{model?.name||target.model_id}</span></label>;
    })}</div>:<small>系统模型库尚未启用此类模型。</small>}
    {kind!=='audio'&&<label>默认{labels[kind]}<select value={defaultTarget?.model_id||''} onChange={event=>patchDefault(kind,event.target.value?{model_id:event.target.value}:null)}>
     <option value="">未配置（生成时明确报错）</option>
     {pool[kind].map(target=>{const model=models.find(item=>item.id===target.model_id);return <option key={target.model_id} value={target.model_id}>{model?.name||target.model_id}</option>})}
     {defaultTarget&&!pool[kind].some(item=>item.model_id===defaultTarget.model_id)&&<option value={defaultTarget.model_id} disabled>原模型不在项目范围，请重新选择</option>}
    </select></label>}
   </div>;
  })}
 </section>;
}
