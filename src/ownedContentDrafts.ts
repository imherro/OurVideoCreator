import {ObjectDrafts} from './objectDrafts.ts';
import type {ObjectRow} from './objectDrafts';

type Value=Record<string,any>;
export type ContentKind='chapter'|'script';
export type ContentRequest=(path:string,options?:RequestInit)=>Promise<any>;
const scriptFields=['title','synopsis','body','estimatedDuration','sourceChapterRefs','storyGoal','paywallBeat','characters','scenes','props'];

/** Adapter for existing relational APIs, using the same conflict state machine as shots. */
export class OwnedContentDrafts {
  readonly drafts=new ObjectDrafts();
  selectedId='';
  readonly kind:ContentKind;
  constructor(kind:ContentKind){this.kind=kind;}
  get productionId(){return this.drafts.projectId;}
  get generation(){return this.drafts.generation;}
  get unsaved(){return this.drafts.unsaved;}
  open(productionId:string){if(this.productionId!==productionId)this.drafts.open(productionId,[]);}
  matches(productionId:string,generation:number){return this.productionId===productionId&&this.generation===generation;}
  row(id:string,value:Value):ObjectRow {
    const fields=this.kind==='chapter'?['title','content']:scriptFields;
    return {id,kind:this.kind,revision:value.revision,assignment_epoch:value.assignment_epoch,
      assignee_id:value.assignee_id,value:structuredClone(value),
      content:Object.fromEntries(fields.map(key=>[key,structuredClone(value[key])]))};
  }
  receive(id:string,value:Value,productionId=this.productionId,generation=this.generation){
    const result=this.drafts.remote(productionId,generation,this.row(id,value));
    if(this.matches(productionId,generation)){const entry=this.drafts.entries.get(id);if(entry)delete entry.base.unavailable;}
    return result;
  }
  value(id:string){const entry=this.drafts.entries.get(id);return entry?{...entry.base.value,...entry.content}:null;}
  patch(id:string,patch:Value){const entry=this.drafts.entries.get(id);if(entry)this.drafts.edit(id,{...entry.content,...patch});}
  path(id:string){return `/productions/${this.productionId}/${this.kind==='chapter'?'chapters':'episode-scripts'}/${id}`;}
  commandPath(id:string){const value=this.value(id);const target=this.kind==='chapter'?value?.id:value?.project_id;
    return target?`/productions/${this.productionId}/owned-content/${this.kind}/${target}`:null;}
  editable(id:string,actorId:string){const entry=this.drafts.entries.get(id);
    return !!entry&&(entry.base.revision===0||entry.base.assignee_id===actorId);}
  async save(id:string,actorId:string,request:ContentRequest){
    if(!this.editable(id,actorId))throw new Error('仅负责人可保存；管理者请先明确接管');
    const ticket=this.drafts.begin(id);
    if(!ticket){if(this.drafts.entries.get(id)?.state==='saved')return null;throw new Error('请先比较并处理冲突，或等待当前保存结束');}
    const path=this.path(id);
    try{
      const value=await request(path,{method:'PUT',body:JSON.stringify({revision:ticket.expected_revision,
        assignment_epoch:ticket.assignment_epoch,...ticket.content})});
      return this.drafts.acknowledge(ticket,this.row(id,value))?value:null;
    }catch(error:any){this.drafts.reject(ticket,error.status||0,error.message||'保存失败');throw error;}
  }
  /** Lists may hide deleted rows, but must not silently drop their unsaved drafts. */
  reconcileIds(ids:string[]){const live=new Set(ids);
    for(const [id,entry] of this.drafts.entries)if(!live.has(id)){
      if(entry.state==='saved')this.drafts.entries.delete(id);
      else {entry.base.unavailable=true;entry.state='conflict';entry.error='远端内容已删除或不可见；本地草稿保留，请先复制保存';}
    }
  }
}
