import type {GenerationKind,GenerationPolicy} from './generationPolicy';
type Value=Record<string,any>;
const labels:Record<GenerationKind,string>={text:'默认文本模型',image:'默认图片模型',video:'默认视频模型'};
export function GenerationPolicyPanel({value,providers:models,onChange}:{value:GenerationPolicy|undefined;providers:Value[];localModels?:Value[];onChange:(next:GenerationPolicy)=>void}){
 const policy=value||{text:null,image:null,video:null};
 return <section className="generation-policy"><h3>项目默认模型</h3>
 <p className="muted">只选择平台发布的模型。项目保存平台模型 ID，不保存上游地址或 Key；未配置时不会自动切换。</p>
 {(['text','image','video'] as GenerationKind[]).map(kind=>{
  const target=policy[kind],available=models.filter(item=>item.kind===kind);
  const missing=target&&!available.some(item=>item.id===target.model_id);
  return <div className="policy-row" key={kind}><label>{labels[kind]}<select value={target?.model_id||''}
   onChange={e=>onChange({...policy,[kind]:e.target.value?{model_id:e.target.value}:null})}>
   <option value="">未配置（生成时明确报错）</option>
   {available.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}
   {missing&&<option value={target!.model_id} disabled>原模型不可用，请重新选择</option>}
  </select></label>{!available.length&&<small>暂无此用途的可用平台模型，请联系管理员。</small>}</div>;
 })}
 </section>;
}
