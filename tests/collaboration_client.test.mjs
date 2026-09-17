import test from 'node:test';
import assert from 'node:assert/strict';
import {CollaborationClient} from '../src/collaborationClient.ts';
import {splitCollaborationDocument} from '../src/collaborationDocument.ts';

const copy=value=>structuredClone(value);
function setup(){
  const document={schemaVersion:6,nodes:['x','y'].map(key=>({id:key+'-image',type:'media',position:{x:0,y:0},
    data:{kind:'image',prompt:key,parameters:{}}})),edges:[],shots:[{id:'x',uid:'x',action:'old x',imageNode:'x-image'},
    {id:'y',uid:'y',action:'old y',imageNode:'y-image'}],timeline:[],characters:[],brief:'',style:'film',ratio:'16:9',duration:15,
    filmBible:{visual:{cards:{},versions:{}},voices:{profiles:{}}},generationPolicy:{text:null,image:null,video:null}};
  const parts=splitCollaborationDocument(document);
  const rows=[...parts.parts.values()].map(part=>({id:part.kind+'-'+part.key,kind:part.kind,object_key:part.key,
    content:copy(part.content),revision:1,assignment_epoch:1,assignee_id:part.key==='y'?'editor-b':'editor-a'}));
  const project={id:'episode',production_id:'production',revision:1,production_revision:1,name:'Episode',
    object_collaboration:true,permissions:{can_generate:true,can_manage:false},document,objects:rows};
  const calls=[],server=new Map(rows.map(row=>[row.id,copy(row)]));
  const request=async(path,init)=>{
    const body=JSON.parse(init.body);calls.push({path,method:init.method,body});
    if(path.endsWith('/lease'))return {token:'test-lease',lease_epoch:1,expires:Date.now()/1000+90};
    assert.ok(path.endsWith('/objects/commands'));
    for(const item of body.updates){if(server.get(item.id).revision!==item.expected_revision)throw Object.assign(new Error('版本冲突'),{status:409});}
    const updated=body.updates.map(item=>{
      const row={...server.get(item.id),revision:item.expected_revision+1,content:copy(item.content)};
      server.set(row.id,row);return copy(row);
    });
    const created=body.creates.map(part=>{
      const key=part.kind==='shot'?(part.content.shot.uid||part.content.shot.id):part.content.node.id;
      const row={id:part.kind+'-'+key,kind:part.kind,object_key:key,revision:1,assignment_epoch:1,
        assignee_id:'editor-a',content:copy(part.content)};
      server.set(row.id,row);return copy(row);
    });
    return {created,updated,deleted:body.deletes.map(item=>item.id)};
  };
  const client=new CollaborationClient(request,'editor-a');client.open(project,[]);
  return {client,project,server,calls,request};
}

test('actual persistence adapter sends only changed shot, never aggregate document or PUT',async()=>{
  const {client,project,calls}=setup(),edited=copy(project.document);
  edited.shots[0].action='new x';client.mark(edited,[]);
  await client.save(edited,project.name,[]);
  assert.equal(calls.length,1);assert.equal(calls[0].method,'POST');
  assert.equal(calls[0].path,'/projects/episode/objects/commands');
  assert.deepEqual(calls[0].body.updates.map(row=>row.id),['shot-x']);
  assert.equal('document' in calls[0].body,false);
  assert.equal(client.drafts.entries.get('shot-x').state,'saved');
});

test('attached child identity edits already send current graph and shot in one command',async()=>{
  for(const mode of ['add','remove','rename']){
    const {client,project,calls}=setup(),edited=copy(project.document);
    if(mode==='add'){
      edited.shots[0].videoNode='x-video';
      edited.nodes.push({id:'x-video',type:'media',position:{x:10,y:20},data:{kind:'video'}});
    }else if(mode==='remove'){
      delete edited.shots[0].imageNode;
      edited.nodes=edited.nodes.filter(node=>node.id!=='x-image');
    }else{
      edited.shots[0].imageNode='x-renamed';
      edited.nodes.find(node=>node.id==='x-image').id='x-renamed';
    }
    client.mark(edited,[]);await client.save(edited,project.name,[]);
    assert.equal(calls.length,1);
    assert.deepEqual(calls[0].body.updates.map(row=>row.id).sort(),['graph-graph','shot-x']);
    assert.equal(calls[0].body.updates.find(row=>row.id==='graph-graph').expected_revision,1);
    assert.equal(calls[0].body.creates.length,0);
    assert.equal(calls[0].body.deletes.length,0);
  }
});

test('canvas child order never dirties another owner shot or blocks its remote update',async()=>{
  const {project,request,calls,server}=setup();
  const video={id:'y-video',type:'media',data:{kind:'video',prompt:'y video'}};
  project.document.shots[1].videoNode=video.id;
  project.document.nodes.push({...copy(video),position:{x:0,y:0}});
  const y=project.objects.find(row=>row.id==='shot-y');
  y.content.shot.videoNode=video.id;
  // Stored envelope order differs from projected canvas order; the latter
  // belongs only to graph.nodeOrder, not to this owner's shot content.
  y.content.nodes.unshift(copy(video));
  server.set(y.id,copy(y));
  const client=new CollaborationClient(request,'editor-a');client.open(project,[]);
  const edited=copy(project.document);edited.shots[0].action='new x';
  client.mark(edited,[]);
  assert.equal(client.drafts.entries.get(y.id).state,'saved');
  await client.save(edited,project.name,[]);
  assert.deepEqual(calls[0].body.updates.map(row=>row.id),['shot-x']);
  const remote=copy(y);remote.revision++;remote.content.shot.action='remote y';
  const merged=client.mergeRemote(remote,edited,[]);
  assert.equal(merged.shots.find(shot=>shot.uid==='y').action,'remote y');
  client.mark(merged,[]);
  assert.equal(client.drafts.entries.get(y.id).state,'saved');
});

test('actual save conflict retains draft and a second timer cannot resend',async()=>{
  const {client,project,server,calls}=setup(),edited=copy(project.document);
  edited.shots[0].action='my draft';client.mark(edited,[]);
  server.get('shot-x').revision=2;
  await assert.rejects(client.save(edited,project.name,[]),/版本冲突/);
  assert.equal(client.drafts.entries.get('shot-x').content.shot.action,'my draft');
  assert.equal(client.drafts.entries.get('shot-x').state,'conflict');
  await assert.rejects(client.save(edited,project.name,[]),/冲突/);
  assert.equal(calls.length,1);
});

test('remote capture node and graph are composed together without a phantom local edit',async()=>{
  for(const graphFirst of [true,false])for(const explicitPosition of [true,false]){
    const {client,project,calls}=setup();
    const node={id:'node-capture',kind:'node',object_key:'capture',revision:1,
      assignment_epoch:1,assignee_id:'editor-b',content:{node:{id:'capture',type:'media',
        data:{kind:'image',prompt:'captured'}}}};
    const graph=copy(project.objects.find(row=>row.kind==='graph'));graph.revision++;
    graph.content.nodeOrder.push('capture');
    if(explicitPosition)graph.content.positions.capture={x:640,y:180};
    const rows=project.objects.filter(row=>row.kind!=='graph');
    rows.push(...(graphFirst?[graph,node]:[node,graph]));
    const merged=client.mergeRemoteRows(rows,project.document,[]);
    client.mark(merged,[]);
    assert.equal(client.hasChanges(merged,project.name,[]),false);
    assert.equal(client.drafts.unsaved,false);
    assert.deepEqual(merged.nodes.find(row=>row.id==='capture').position,
      explicitPosition?{x:640,y:180}:{x:0,y:0});
    await client.save(merged,project.name,[]);
    assert.equal(calls.length,0);
  }
});

test('remote snapshot preserves a real local shot draft while accepting independent structural changes',()=>{
  const {client,project}=setup(),edited=copy(project.document);
  edited.shots[0].action='local draft';client.mark(edited,[]);
  const rows=copy(project.objects),x=rows.find(row=>row.id==='shot-x');
  x.revision++;x.content.shot.action='remote x';
  const graph=rows.find(row=>row.kind==='graph');graph.revision++;
  graph.content.positions['y-image']={x:250,y:120};
  const merged=client.mergeRemoteRows(rows,edited,[]);
  assert.equal(merged.shots.find(row=>row.uid==='x').action,'local draft');
  assert.equal(client.drafts.entries.get('shot-x').state,'conflict');
  assert.deepEqual(merged.nodes.find(row=>row.id==='y-image').position,{x:250,y:120});
});

test('remote deletion and graph removal arrive as one clean projection',async()=>{
  const {client,project,calls}=setup();
  const rows=copy(project.objects.filter(row=>row.id!=='shot-y'));
  const graph=rows.find(row=>row.kind==='graph');graph.revision++;
  delete graph.content.positions['y-image'];
  graph.content.nodeOrder=graph.content.nodeOrder.filter(id=>id!=='y-image');
  graph.content.shotOrder=graph.content.shotOrder.filter(id=>id!=='y');
  const merged=client.mergeRemoteRows(rows,project.document,[],'shot-y');
  client.mark(merged,[]);
  assert.equal(merged.shots.length,1);assert.equal(merged.nodes.length,1);
  assert.equal(client.hasChanges(merged,project.name,[]),false);
  assert.equal(client.drafts.unsaved,false);
  await client.save(merged,project.name,[]);assert.equal(calls.length,0);
});

test('a late full object read cannot roll back newer revisions or clear graph conflicts',()=>{
  const {client,project}=setup(),fresh=copy(project.objects);
  fresh.find(row=>row.id==='shot-y').revision=3;
  fresh.find(row=>row.id==='shot-y').content.shot.action='newer y';
  let doc=client.mergeRemoteRows(fresh,project.document,[]);
  doc=client.mergeRemoteRows(project.objects,doc,[]);
  assert.equal(doc.shots.find(row=>row.uid==='y').action,'newer y');
  doc.nodes[0].position={x:99,y:88};client.mark(doc,[]);
  const graph=fresh.find(row=>row.kind==='graph');graph.revision=2;
  graph.content.positions['x-image']={x:777,y:888};
  doc=client.mergeRemoteRows(fresh,doc,[]);
  assert.deepEqual(doc.nodes.find(row=>row.id==='x-image').position,{x:99,y:88});
  assert.equal(client.drafts.entries.get(graph.id).state,'conflict');
});

test('remote Y update during X save is retained in baseline and never resent as our edit',async()=>{
  const {project,request,calls,server}=setup();
  let release,entered;
  const gate=new Promise(resolve=>release=resolve),started=new Promise(resolve=>entered=resolve);
  const client=new CollaborationClient(async(path,init)=>{entered();await gate;return request(path,init);},'editor-a');
  client.open(project,[]);
  const edited=copy(project.document);edited.shots[0].action='new x';client.mark(edited,[]);
  const saving=client.save(edited,project.name,[]);await started;
  const y=copy(server.get('shot-y'));y.revision=2;y.content.shot.action='remote y';
  const merged=client.mergeRemote(y,edited,[]);release();await saving;
  await client.save(merged,project.name,[]);
  assert.equal(calls.length,1);
  assert.equal(merged.shots.find(shot=>shot.uid==='y').action,'remote y');
});

test('new shot and graph revision share one atomic command',async()=>{
  const {client,project,calls}=setup(),edited=copy(project.document);
  edited.shots.push({id:'z',uid:'z',action:'new shot'});
  await client.save(edited,project.name,[]);
  assert.equal(calls.length,1);assert.equal(calls[0].body.creates.length,1);
  assert.equal(calls[0].body.creates[0].kind,'shot');
  assert.deepEqual(calls[0].body.updates.map(row=>row.id),['graph-graph']);
  assert.equal(client.rows.get('shot:z').assignee_id,'editor-a');
});

test('timeline save acquires object lease and sends its token only to timeline command',async()=>{
  const {client,project,calls}=setup(),edited=copy(project.document);
  edited.editor={version:1,timeline:{version:2,tracks:[],backgroundColor:'#123456'}};
  await client.save(edited,project.name,[]);
  assert.ok(calls[0].path.endsWith('/timeline-timeline/lease'));
  assert.equal(calls[1].body.updates[0].lease_token,'test-lease');
  assert.equal(calls[1].body.updates[0].lease_epoch,1);
});

test('another assignee and production metadata are blocked before network writes',async()=>{
  const {client,project,calls}=setup(),edited=copy(project.document);
  edited.shots[1].action='unauthorized';
  await assert.rejects(client.save(edited,project.name,[]),/负责人/);
  const metadata=copy(project.document);metadata.style='different';
  await assert.rejects(client.save(metadata,project.name,[]),/manager/);
  assert.equal(calls.length,0);
});

test('per-object save ignores a different dirty conflict and preserves its draft',async()=>{
  const {client,project,server,calls}=setup(),edited=copy(project.document);
  edited.shots[0].action='x clean save';edited.shots[1].action='y local draft';client.mark(edited,[]);
  const remote=copy(server.get('shot-y'));remote.revision=2;remote.content.shot.action='y remote';
  client.mergeRemote(remote,edited,[]);
  assert.equal(client.drafts.entries.get('shot-y').state,'conflict');
  await client.saveOnly('shot-x',edited,[]);
  assert.deepEqual(calls[0].body.updates.map(row=>row.id),['shot-x']);
  assert.equal(client.drafts.entries.get('shot-y').content.shot.action,'y local draft');
  assert.equal(client.drafts.entries.get('shot-y').state,'conflict');
});

test('explicit discard restores just the selected object, not another dirty object',()=>{
  const {client,project,server}=setup(),edited=copy(project.document);
  edited.shots[0].action='x draft';edited.shots[1].action='y draft';client.mark(edited,[]);
  const remote=copy(server.get('shot-y'));remote.revision=2;remote.content.shot.action='y remote';
  const resolved=client.resolve('shot-y',remote,'discard',edited,[]);
  assert.equal(resolved.shots[0].action,'x draft');assert.equal(resolved.shots[1].action,'y remote');
  assert.equal(client.drafts.entries.get('shot-x').state,'dirty');
  assert.equal(client.drafts.entries.get('shot-y').state,'saved');
  assert.equal(client.hasChanges(resolved,project.name,[]),true);
});

test('explicit compare and reapply uses exactly the compared revision and still detects a later race',async()=>{
  const {client,project,server,calls}=setup(),edited=copy(project.document);
  edited.shots[0].action='keep this';client.mark(edited,[]);
  const compared=copy(server.get('shot-x'));compared.revision=2;server.set(compared.id,copy(compared));
  client.mergeRemote(compared,edited,[]);
  client.resolve('shot-x',compared,'keep-draft',edited,[]);
  server.get('shot-x').revision=3;
  await assert.rejects(client.saveOnly('shot-x',edited,[]),/版本冲突/);
  assert.equal(calls[0].body.updates[0].expected_revision,2);
  assert.equal(client.drafts.entries.get('shot-x').state,'conflict');
});

test('reverting local content clears dirty state without network writes',()=>{
  const {client,project}=setup(),edited=copy(project.document);
  edited.shots[0].action='temporary';client.mark(edited,[]);
  client.mark(project.document,[]);
  assert.equal(client.drafts.entries.get('shot-x').state,'saved');
  assert.equal(client.hasChanges(project.document,project.name,[]),false);
});

test('a delayed lease response from the previous episode cannot populate the new episode',async()=>{
  const {project}=setup();let release;
  const client=new CollaborationClient(()=>new Promise(resolve=>release=resolve),'editor-a');
  client.open(project,[]);const pending=client.lease('timeline-timeline','acquire');
  client.open({...project,id:'other-episode'},[]);release({token:'old',expires:999999});
  await assert.rejects(pending,/切换作品/);assert.equal(client.leases.size,0);
});

test('derived downstream stale flags cannot turn another assignee into a write target',async()=>{
  const {client,project,calls}=setup(),edited=copy(project.document);
  edited.shots[0].action='actual own edit';
  edited.nodes.forEach(node=>Object.assign(node.data,{stale:true,staleReason:'upstream-change',generation_revision:1}));
  client.mark(edited,[]);await client.save(edited,project.name,[]);
  assert.deepEqual(calls[0].body.updates.map(row=>row.id),['shot-x']);
  assert.equal(client.drafts.entries.get('shot-y').state,'saved');
  assert.equal(client.hasChanges(edited,project.name,[]),false);
});

test('explicit initial-state review remains a real object edit subject to ownership',async()=>{
  const {client,project,calls}=setup(),edited=copy(project.document);
  edited.nodes[1].data.state_reviewed=true;
  await assert.rejects(client.save(edited,project.name,[]),/负责人/);
  assert.equal(calls.length,0);
});

test('switch during lease acquisition prevents subsequent writes of the old save command',async()=>{
  const {project}=setup(),calls=[];let release;
  const client=new CollaborationClient((path)=>{calls.push(path);return new Promise(resolve=>release=resolve);},'editor-a');
  client.open(project,[]);
  const edited=copy(project.document);edited.editor={version:1,timeline:{version:2,tracks:[],backgroundColor:'#987654'}};
  const pending=client.save(edited,project.name,[]);
  client.open({...project,id:'new-episode'},[]);release({token:'old-page',expires:999999,lease_epoch:1});
  await assert.rejects(pending,/切换作品/);
  assert.equal(calls.length,1);assert.ok(calls[0].endsWith('/lease'));
  assert.equal(client.leases.size,0);
});

test('deprecated visual restore uses object CAS and merges only the returned row',async()=>{
  const {project}=setup();
  const visual={id:'visual-hero',kind:'visual_card',object_key:'hero',revision:4,assignment_epoch:2,
    assignee_id:'editor-a',content:{
      card:{id:'hero',kind:'character',name:'Hero',parentCardId:null,currentVersionId:'hero-v1',status:'active'},
      versions:{'hero-v1':{id:'hero-v1',cardId:'hero',version:1,parentVersionId:null,status:'deprecated',
        spec:{description:'coat',attributes:[]},invariants:[],references:[],createdAt:1,provenance:{}}},
      voice_profile:null}};
  project.objects.push(copy(visual));
  project.document.filmBible.visual.cards.hero=copy(visual.content.card);
  project.document.filmBible.visual.versions['hero-v1']=copy(visual.content.versions['hero-v1']);
  const calls=[];
  const client=new CollaborationClient(async(path,init)=>{
    const body=JSON.parse(init.body);calls.push({path,body});
    const restored=copy(visual);restored.revision=5;restored.content.versions['hero-v1'].status='locked';
    return restored;
  },'editor-a');
  client.open(project,[]);
  const restored=await client.restoreVisualVersion('hero-v1');
  assert.equal(restored.content.versions['hero-v1'].status,'locked');
  assert.equal(calls[0].path,'/projects/episode/objects/visual-hero/visual-versions/hero-v1/restore');
  assert.deepEqual(calls[0].body,{expected_revision:4,assignment_epoch:2});
  const merged=client.mergeRemote(restored,project.document,[]);
  assert.equal(merged.filmBible.visual.versions['hero-v1'].status,'locked');
  assert.equal(client.drafts.entries.get('visual-hero').state,'saved');
});

test('visual restore refuses a local draft instead of replacing it with history',async()=>{
  const {client,project,calls}=setup();
  const visual={id:'visual-hero',kind:'visual_card',object_key:'hero',revision:1,assignment_epoch:1,
    assignee_id:'editor-a',content:{card:{id:'hero',kind:'character',name:'Hero',parentCardId:null,
      currentVersionId:'hero-v1',status:'active'},versions:{'hero-v1':{id:'hero-v1',cardId:'hero',version:1,
      parentVersionId:null,status:'deprecated',spec:{description:'old',attributes:[]},invariants:[],references:[],
      createdAt:1,provenance:{}}},voice_profile:null}};
  project.objects.push(copy(visual));
  project.document.filmBible.visual.cards.hero=copy(visual.content.card);
  project.document.filmBible.visual.versions['hero-v1']=copy(visual.content.versions['hero-v1']);
  client.open(project,[]);
  const edited=copy(project.document);edited.filmBible.visual.cards.hero.name='Local draft';client.mark(edited,[]);
  await assert.rejects(client.restoreVisualVersion('hero-v1'),/本地草稿/);
  assert.equal(calls.length,0);
  assert.equal(client.drafts.entries.get('visual-hero').content.card.name,'Local draft');
});
