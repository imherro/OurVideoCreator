import type {GenerationKind,GenerationTarget} from './generationPolicy.ts';

type Value=Record<string,any>;
export type ModelPoolKind=GenerationKind|'audio';
export type ProjectModelPool=Record<ModelPoolKind,GenerationTarget[]>;
export const MODEL_POOL_KINDS:ModelPoolKind[]=['text','image','video','audio'];

export const emptyProjectModelPool=():ProjectModelPool=>({text:[],image:[],video:[],audio:[]});
export const targetKey=(target:GenerationTarget)=>target.model_id;

export function defaultProjectModelPool(models:Value[]):ProjectModelPool {
 return Object.fromEntries(MODEL_POOL_KINDS.map(kind=>[
  kind,models.filter(model=>model.kind===kind).map(model=>({model_id:String(model.id)})),
 ])) as ProjectModelPool;
}

/** Missing pools are legacy Productions and keep the former global-catalog behavior. */
export function effectiveProjectModels(pool:Partial<ProjectModelPool>|null|undefined,models:Value[],kind?:ModelPoolKind):Value[] {
 if(!pool)return models.filter(model=>!kind||model.kind===kind);
 const ids=new Set((kind?[kind]:MODEL_POOL_KINDS).flatMap(item=>
  Array.isArray(pool[item])?pool[item]!.map(target=>target?.model_id).filter(Boolean):[],
 ));
 return models.filter(model=>(!kind||model.kind===kind)&&ids.has(model.id));
}
