import {ObjectDrafts,type ObjectRow,equalContent,type SaveTicket} from './objectDrafts.ts';
import {splitCollaborationDocument,composeCollaborationDocument,changedDocumentParts,samePartContent,type DocumentParts} from './collaborationDocument.ts';
import type {EditorAsset} from './editor/editorDocument.ts';

type Value=Record<string,any>;
type Request=(path:string,init?:RequestInit)=>Promise<any>;
const send=(method:string,body:unknown)=>({method,body:JSON.stringify(body)});
const rowKey=(row:ObjectRow)=>`${row.kind}:${row.object_key}`;
const copy=<T>(value:T):T=>structuredClone(value);

/** Actual editor persistence adapter: all writes are selected object commands. */
export class CollaborationClient {
  drafts=new ObjectDrafts();
  rows=new Map<string,ObjectRow>();
  baseline:DocumentParts|null=null;
  project:Value|null=null;
  leases=new Map<string,Value>();
  private request:Request;
  private actorId:string;

  constructor(request:Request,actorId:string){this.request=request;this.actorId=actorId;}

  open(project:Value,assets:EditorAsset[]){
    this.project=copy(project);
    this.rows=new Map((project.objects||[]).map((row:ObjectRow)=>[rowKey(row),copy(row)]));
    this.baseline=splitCollaborationDocument(project.document,assets);
    this.drafts.open(project.id,project.objects||[],true);
    this.leases.clear();
  }

  mark(document:Value,assets:EditorAsset[]){
    if(!this.baseline)return;
    const next=splitCollaborationDocument(document,assets);
    for(const part of next.parts.values()){
      const row=this.rows.get(`${part.kind}:${part.key}`);
      const entry=row&&this.drafts.entries.get(row.id);
      if(row&&entry&&!samePartContent(part.kind,entry.content,part.content)){
        this.drafts.edit(row.id,samePartContent(part.kind,entry.base.content,part.content)?entry.base.content:part.content);
      }
    }
  }

  hasChanges(document:Value,name:string,assets:EditorAsset[]){
    if(!this.baseline||!this.project)return false;
    const delta=changedDocumentParts(this.baseline,splitCollaborationDocument(document,assets));
    return Boolean(delta.created.length||delta.updated.length||delta.removed.length||delta.episodeMetadata||
      delta.productionMetadata||name!==this.project.name);
  }

  /** Save one independent existing object without resubmitting other drafts. */
  async saveOnly(id:string,document:Value,assets:EditorAsset[]){
    if(!this.baseline||!this.project)throw new Error('协作项目尚未载入');
    const row=this.row(id),key=rowKey(row),part=splitCollaborationDocument(document,assets).parts.get(key);
    if(!part)throw new Error('对象删除或新建结构请使用整体保存的原子命令');
    const selected=copy(this.baseline);selected.parts.set(key,copy(part));
    return this.save(composeCollaborationDocument(selected,
      (document.nodes||[]).filter((node:Value)=>node.data?.canonicalScriptProjection)),this.project.name,assets);
  }

  async read(id:string,resource=''){
    const pid=this.project?.id,generation=this.drafts.generation;
    if(!pid)throw new Error('协作项目尚未载入');
    const result=await this.request(`/projects/${pid}/objects/${id}${resource?'/' + resource:''}`);
    this.assertScope(pid,generation);return result;
  }

  async lease(id:string,action:'acquire'|'renew'|'release'){
    const row=this.row(id),pid=this.project!.id,generation=this.drafts.generation,held=this.leases.get(id);
    const result=await this.request(`/projects/${pid}/objects/${id}/lease`,send('POST',{
      action,assignment_epoch:row.assignment_epoch,...(action==='acquire'?{}:{token:held?.token,lease_epoch:held?.lease_epoch})}));
    this.assertScope(pid,generation);
    if(action==='release')this.leases.delete(id);else this.leases.set(id,result);
    return result;
  }

  async action(id:string,action:'assign'|'review'|'restore',data:Value){
    const row=this.row(id),pid=this.project!.id,generation=this.drafts.generation;
    if(action!=='assign'&&this.drafts.entries.get(id)?.state!=='saved')
      throw new Error('请先保存此对象或处理它的本地草稿，再审核/恢复历史');
    let lease:Value={};
    if(action==='restore'&&row.kind==='timeline'){
      const held=this.leases.get(id);
      if(!held)throw new Error('请先取得时间线编辑租约');
      lease={lease_token:held.token,lease_epoch:held.lease_epoch};
    }
    const result=await this.request(`/projects/${pid}/objects/${id}/${action}`,send('POST',{
      ...data,expected_revision:row.revision,assignment_epoch:row.assignment_epoch,...lease}));
    this.assertScope(pid,generation);
    if(action==='assign')this.leases.delete(id);
    return result as ObjectRow;
  }

  async comment(id:string,body:string){
    const pid=this.project?.id,generation=this.drafts.generation;
    if(!pid)throw new Error('协作项目尚未载入');
    const result=await this.request(`/projects/${pid}/objects/${id}/comments`,send('POST',{body}));
    this.assertScope(pid,generation);return result;
  }

  resolve(id:string,latest:ObjectRow,choice:'discard'|'keep-draft',document:Value,assets:EditorAsset[]){
    if(!this.baseline)throw new Error('协作项目尚未载入');
    this.drafts.resolve(id,latest,choice);
    const key=rowKey(latest),part={key:latest.object_key,kind:latest.kind as any,content:copy(latest.content)};
    this.rows.set(key,copy(latest));this.baseline.parts.set(key,copy(part));
    if(choice==='keep-draft')return document;
    const parts=splitCollaborationDocument(document,assets);parts.parts.set(key,part);
    return composeCollaborationDocument(parts,(document.nodes||[]).filter((node:Value)=>node.data?.canonicalScriptProjection));
  }

  async save(document:Value,name:string,assets:EditorAsset[]){
    const project=this.project,base=this.baseline;
    if(!project||!base)throw new Error('协作项目尚未载入');
    if(!project.object_collaboration)throw new Error('旧测试项目只读，请创建新的协作项目；不会自动迁移旧内容');
    const pid=project.id,generation=this.drafts.generation;
    const next=splitCollaborationDocument(document,assets),delta=changedDocumentParts(base,next);
    if((delta.episodeMetadata||delta.productionMetadata||name!==project.name)&&!project.permissions?.can_manage){
      throw new Error('作品/分集设置需要 manager 或团队 owner；对象内容请按分工编辑');
    }
    const updateRows=delta.updated.map(part=>{
      const row=this.rows.get(`${part.kind}:${part.key}`);
      if(!row)throw new Error('对象未载入，请刷新后重新编辑');
      if(row.kind!=='graph'&&row.assignee_id!==this.actorId)throw new Error('当前不是对象负责人；请先在协作面板分配或显式接管');
      return {row,part};
    });
    const deletes=delta.removed.map(part=>{
      const row=this.rows.get(`${part.kind}:${part.key}`);
      if(!row)throw new Error('待删除对象未载入');
      if(!project.permissions?.can_manage||row.assignee_id!==this.actorId)throw new Error('删除需要管理权限并先接管对象');
      return {id:row.id,expected_revision:row.revision,assignment_epoch:row.assignment_epoch};
    });
    const tickets:SaveTicket[]=[];
    try{
      const updates=[];
      for(const {row,part} of updateRows){
        this.drafts.edit(row.id,part.content);
        const ticket=this.drafts.begin(row.id);
        if(!ticket)throw Object.assign(new Error('对象存在未解决冲突，请比较草稿或刷新'),{status:409});
        tickets.push(ticket);
        let lease:Value={};
        if(row.kind==='timeline'){
          let held=this.leases.get(row.id);
          if(!held){
            held=await this.request(`/projects/${pid}/objects/${row.id}/lease`,send('POST',{action:'acquire',assignment_epoch:row.assignment_epoch}));
            this.assertScope(pid,generation);
            this.leases.set(row.id,held!);
          }else if(Number(held.expires)*1000-Date.now()<45000){
            held=await this.request(`/projects/${pid}/objects/${row.id}/lease`,send('POST',{action:'renew',
              assignment_epoch:row.assignment_epoch,token:held.token,lease_epoch:held.lease_epoch}));
            this.assertScope(pid,generation);
            this.leases.set(row.id,held!);
          }
          lease={lease_token:held!.token,lease_epoch:held!.lease_epoch};
        }
        updates.push({id:row.id,expected_revision:ticket.expected_revision,assignment_epoch:ticket.assignment_epoch,
          content:ticket.content,...lease});
      }
      if(updates.length||delta.created.length||deletes.length){
        this.assertScope(pid,generation);
        const result=await this.request(`/projects/${pid}/objects/commands`,send('POST',{
          creates:delta.created.map(part=>({kind:part.kind,content:part.content})),updates,deletes}));
        this.assertScope(pid,generation);
        for(const row of result.updated as ObjectRow[]){
          this.rows.set(rowKey(row),copy(row));
          const ticket=tickets.find(item=>item.id===row.id);
          if(ticket)this.drafts.acknowledge(ticket,row);
        }
        for(const row of result.created as ObjectRow[]){
          this.rows.set(rowKey(row),copy(row));this.drafts.remote(pid,generation,row);
        }
        for(const part of delta.removed){
          const row=this.rows.get(`${part.kind}:${part.key}`);
          if(row)this.drafts.entries.delete(row.id);
          this.rows.delete(`${part.kind}:${part.key}`);
        }
        // A later metadata failure must not replay successful object creations.
        for(const part of [...delta.created,...delta.updated])base.parts.set(`${part.kind}:${part.key}`,copy(part));
        for(const part of delta.removed)base.parts.delete(`${part.kind}:${part.key}`);
      }
      if(delta.episodeMetadata||name!==project.name){
        const patch:Value={};
        for(const [key,value] of Object.entries(next.episodeMetadata)){
          if(key!=='schemaVersion'&&!equalContent(value,base.episodeMetadata[key]))patch[key]=value;
        }
        if(name!==project.name)patch.name=name;
        const result=await this.request(`/projects/${pid}/metadata`,send('PATCH',{expected_revision:project.revision,patch}));
        this.assertScope(pid,generation);project.revision=result.revision;project.name=name;
        base.episodeMetadata=next.episodeMetadata;
      }
      if(delta.productionMetadata){
        const patch=Object.fromEntries(Object.entries(next.productionMetadata).filter(([key,value])=>!equalContent(value,base.productionMetadata[key])));
        const result=await this.request(`/productions/${project.production_id}/context`,send('PATCH',{
          expected_revision:project.production_revision,patch}));
        this.assertScope(pid,generation);project.production_revision=result.revision;
        base.productionMetadata=next.productionMetadata;
      }
      return {revision:project.revision,production_revision:project.production_revision,objects:[...this.rows.values()]};
    }catch(error:any){
      for(const ticket of tickets)this.drafts.reject(ticket,error.status||0,error.message);
      throw error;
    }
  }

  /** A structural transaction emits several object events. Compose its read
   * snapshot once, so an arriving node cannot manufacture a local graph edit
   * before the corresponding graph row has been applied. */
  mergeRemoteRows(rows:ObjectRow[],document:Value,assets:EditorAsset[],eventObjectId?:string){
    if(!this.project||!this.baseline)return document;
    const parts=splitCollaborationDocument(document,assets);
    if(eventObjectId&&!rows.some(row=>row.id===eventObjectId)){
      const removed=[...this.rows.values()].find(row=>row.id===eventObjectId);
      if(removed){
        const key=rowKey(removed),current=parts.parts.get(key),base=this.baseline.parts.get(key);
        if(current&&base&&!samePartContent(removed.kind,current.content,base.content)){
          const draft=this.drafts.entries.get(removed.id);
          if(draft){draft.state='conflict';draft.error='对象已被移除；本地草稿保留，请备份或重新载入';}
        }else{
          parts.parts.delete(key);this.baseline.parts.delete(key);
          this.rows.delete(key);this.drafts.entries.delete(removed.id);
        }
      }
    }
    for(const row of rows){
      const key=rowKey(row),current=parts.parts.get(key),base=this.baseline.parts.get(key);
      if(current&&(!base||!samePartContent(row.kind,current.content,base.content))){
        this.drafts.remote(this.project.id,this.drafts.generation,row);continue;
      }
      if(!this.drafts.remote(this.project.id,this.drafts.generation,row))continue;
      this.rows.set(key,copy(row));
      const part={key:row.object_key,kind:row.kind as any,content:copy(row.content)};
      parts.parts.set(key,part);this.baseline.parts.set(key,copy(part));
    }
    return composeCollaborationDocument(parts,(document.nodes||[]).filter((node:Value)=>node.data?.canonicalScriptProjection));
  }

  mergeRemote(row:ObjectRow,document:Value,assets:EditorAsset[]){
    if(!this.project||!this.baseline)return document;
    const key=rowKey(row),parts=splitCollaborationDocument(document,assets),current=parts.parts.get(key),base=this.baseline.parts.get(key);
    const dirty=current&&(!base||!samePartContent(row.kind,current.content,base.content));
    if(dirty){this.drafts.remote(this.project.id,this.drafts.generation,row);return document;}
    if(!this.drafts.remote(this.project.id,this.drafts.generation,row))return document;
    this.rows.set(key,copy(row));
    const part={key:row.object_key,kind:row.kind as any,content:copy(row.content)};
    parts.parts.set(key,part);this.baseline.parts.set(key,copy(part));
    return composeCollaborationDocument(parts,(document.nodes||[]).filter((node:Value)=>node.data?.canonicalScriptProjection));
  }

  removeRemote(id:string,document:Value,assets:EditorAsset[]){
    if(!this.project||!this.baseline)return document;
    const row=[...this.rows.values()].find(item=>item.id===id);
    if(!row)return document;
    const key=rowKey(row),parts=splitCollaborationDocument(document,assets),current=parts.parts.get(key),base=this.baseline.parts.get(key);
    if(current&&base&&!samePartContent(row.kind,current.content,base.content)){
      const draft=this.drafts.entries.get(id);
      if(draft){draft.state='conflict';draft.error='对象已被移除；本地草稿保留，请备份或重新载入';}
      return document;
    }
    parts.parts.delete(key);this.baseline.parts.delete(key);this.rows.delete(key);this.drafts.entries.delete(id);
    return composeCollaborationDocument(parts,(document.nodes||[]).filter((node:Value)=>node.data?.canonicalScriptProjection));
  }

  private assertScope(pid:string,generation:number){
    if(this.project?.id!==pid||this.drafts.generation!==generation)throw new Error('已切换作品，忽略旧保存响应');
  }

  private row(id:string){
    const row=[...this.rows.values()].find(item=>item.id===id);
    if(!row||!this.project)throw new Error('对象尚未载入');
    return row;
  }
}
