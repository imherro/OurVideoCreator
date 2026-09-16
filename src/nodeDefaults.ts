import type {GenerationPolicy} from './generationPolicy.ts';
import {resolveGenerationTarget} from './generationPolicy.ts';
type Value=Record<string,any>;
/** Shared by canvas, storyboard and browser tools. Never route media to the text engine. */
export function nodeDefaults(kind:string,providers:Value[],models:Value[],policy?:GenerationPolicy){
 const generationKind=kind==='storyboard'?'text':kind as 'text'|'image'|'video';
 const target=policy?.[generationKind]
  ? resolveGenerationTarget(generationKind,undefined,policy,providers,models)
  : {providerId:'',modelId:''};
 const model=target.modelId;
 return {provider:target.providerId,model,resolution:model==='minimax_h3'?'864x480':'832x480',frames:model==='minimax_h3'?124:121,seed:-1};
}
