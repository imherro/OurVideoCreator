import type {GenerationPolicy} from './generationPolicy.ts';
import {resolveGenerationTarget} from './generationPolicy.ts';
type Value=Record<string,any>;
/** Only published platform model IDs and their safe defaults enter a node. */
export function nodeDefaults(kind:string,models:Value[],_localModels:Value[],policy?:GenerationPolicy){
 const generationKind=kind==='storyboard'?'text':kind as 'text'|'image'|'video';
 const target=policy?.[generationKind]
  ? resolveGenerationTarget(generationKind,undefined,policy,models)
  : {model_id:''};
 const model=models.find(item=>item.id===target.model_id);
 return {model_id:target.model_id,parameters:{...model?.defaults},
  model_capabilities:{...model?.capabilities},model_rules:{...model?.rules}};
}
