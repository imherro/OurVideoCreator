type Value=Record<string,any>;
export type GenerationKind='text'|'image'|'video';
export type GenerationTarget={model_id:string};
export type GenerationPolicy=Record<GenerationKind,GenerationTarget|null>;
export const emptyGenerationPolicy=():GenerationPolicy=>({text:null,image:null,video:null});

/** The platform publishes all choices. A missing selection never falls back. */
export function resolveGenerationTarget(kind:GenerationKind,override:Value|undefined,policy:GenerationPolicy|undefined,models:Value[],_localModels:Value[]=[]){
 const source=override?.mode==='override'?'override' as const:'project' as const;
 const target=source==='override'?{model_id:override!.model_id}:policy?.[kind];
 if(!target?.model_id)throw new Error(`尚未为项目配置默认 ${kind} 平台模型；不会自动切换其他服务`);
 const model=models.find(item=>item.id===target.model_id&&item.kind===kind);
 if(!model)throw new Error('所选平台模型未发布、已停用或用途不匹配，请重新选择；不会自动切换');
 return {model_id:model.id as string,source};
}
