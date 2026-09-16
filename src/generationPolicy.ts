type Value=Record<string,any>;
export type GenerationKind='text'|'image'|'video';
export type GenerationTarget={providerId:string;modelId:string};
export type GenerationPolicy=Record<GenerationKind,GenerationTarget|null>;

export const emptyGenerationPolicy=():GenerationPolicy=>({text:null,image:null,video:null});

export function resolveGenerationTarget(kind:GenerationKind,override:Value|undefined,policy:GenerationPolicy|undefined,providers:Value[],localModels:Value[]=[]){
 let target:GenerationTarget|undefined,source:'override'|'project'|'system'='system';
 if(override?.mode==='override'){target={providerId:override.providerId,modelId:override.modelId||''};source='override'}
 else if(policy?.[kind]){target=policy[kind]||undefined;source='project'}
 if(target){
  if(target.providerId==='local')throw new Error(`${source==='project'?'项目默认':'节点自定义'}仍指向已移除的本地推理，请选择外部 Provider`);
  const provider=providers.find(p=>p.id===target!.providerId);
  if(!provider)throw new Error(`${source==='project'?'项目默认':'节点自定义'}模型服务已不存在，请重新选择；系统不会自动切换到其他服务`);
  if(provider.kind&&provider.kind!==kind)throw new Error(`所选模型服务不支持${kind}`);
  return {providerId:provider.id,modelId:target.modelId||provider.models?.[kind]||provider.model||'',source};
 }
 throw new Error(`尚未为项目配置默认 ${kind} Provider；系统不会自动选择其他付费模型`);
}
