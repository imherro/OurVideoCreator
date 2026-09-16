import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from 'typescript';
import {CollaborationClient} from '../src/collaborationClient.ts';
import {splitCollaborationDocument,composeCollaborationDocument} from '../src/collaborationDocument.ts';

const copy=value=>structuredClone(value);

// Execute the real host callbacks, not a handwritten substitute for their
// save-success/error branches. React setters/refs are the test boundary; this
// is host callback integration, not browser rendering or HTTP evidence.
const source=ts.createSourceFile('main.tsx',fs.readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8'),
  ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const callbacks=new Map();
function visit(node){
  if(ts.isFunctionDeclaration(node)&&['save','saveObject','acceptObjectDocument'].includes(node.name?.text)){
    assert.ok(!callbacks.has(node.name.text),'host callback must be unambiguous');
    callbacks.set(node.name.text,node.getText(source));
  }
  ts.forEachChild(node,visit);
}
visit(source);assert.equal(callbacks.size,3);
const callbackCode=ts.transpileModule([...callbacks.values()].join('\n'),{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}).outputText;

function host(client,project){
  const state={project:copy(project),doc:copy(project.document),saved:'已保存',conflict:false,errors:[]};
  const refs={current:{current:{project:state.project,doc:state.doc}},dirty:{current:false},
    saving:{current:false},saveFlight:{current:null},conflictRef:{current:false},
    collaboration:{current:client},collaborationAssets:{current:[]},
    revision:{current:project.revision},productionRevision:{current:project.production_revision}};
  const bindings={...refs,setSaved:value=>{state.saved=value;},setConflict:value=>{state.conflict=value;},
    setProject:value=>{state.project=typeof value==='function'?value(state.project):value;},
    setDoc:value=>{state.doc=value;},setProjects:()=>{},setNotice:()=>{},report:error=>state.errors.push(error.message)};
  const actual=new Function('bindings',`const {${Object.keys(bindings).join(',')}}=bindings;\n${callbackCode}\nreturn {save,saveObject,acceptObjectDocument};`)(bindings);
  return {...actual,state,refs,edit(mutator){
    const doc=copy(state.doc);mutator(doc);state.doc=doc;refs.current.current.doc=doc;
    refs.dirty.current=true;client.mark(doc,[]);
  },remote(rows){actual.acceptObjectDocument(client.mergeRemoteRows(rows,state.doc,[]));}};
}

function fixture(){
  const document={nodes:[],edges:[],shots:[{id:'x',uid:'x',action:'v1',note:''},
    {id:'y',uid:'y',action:'y1',note:''}],timeline:[],ratio:'16:9',style:'film'};
  const seed=splitCollaborationDocument(document);
  const rows=[...seed.parts.values()].map(part=>({id:`${part.kind}-${part.key}`,kind:part.kind,
    object_key:part.key,revision:1,assignment_epoch:1,assignee_id:'editor-a',content:copy(part.content)}));
  const server=new Map(rows.map(row=>[row.id,copy(row)])),requests=[];
  let release,notifyCommit,delay=true;
  const gate=new Promise(resolve=>{release=resolve;});
  const committed=new Promise(resolve=>{notifyCommit=resolve;});
  function snapshot(){
    const parts=copy(seed);parts.parts=new Map([...server.values()].map(row=>[
      `${row.kind}:${row.object_key}`,{kind:row.kind,key:row.object_key,content:copy(row.content)}]));
    return {id:'episode',production_id:'production',name:'Episode',revision:1,production_revision:1,
      object_collaboration:true,permissions:{can_manage:false},document:composeCollaborationDocument(parts),
      objects:[...server.values()].map(copy)};
  }
  const request=label=>async(path,init)=>{
    assert.equal(path,'/projects/episode/objects/commands');
    const body=JSON.parse(init.body);requests.push({label,body:copy(body)});
    assert.deepEqual(body.creates,[]);assert.deepEqual(body.deletes,[]);
    // Validate the WHOLE batch before mutation; every caller uses actual CAS
    // and epoch/ownership checks. Delay only the already committed r2 receipt.
    for(const item of body.updates){
      const row=server.get(item.id);assert.ok(row);
      if(row.assignee_id!=='editor-a')throw Object.assign(new Error('owner changed'),{status:403});
      if(row.revision!==item.expected_revision||row.assignment_epoch!==item.assignment_epoch)
        throw Object.assign(new Error('CAS/epoch conflict'),{status:409});
    }
    const updated=body.updates.map(item=>{
      const row={...server.get(item.id),revision:item.expected_revision+1,content:copy(item.content)};
      server.set(row.id,copy(row));return copy(row);
    });
    if(label==='first'&&delay){delay=false;notifyCommit();await gate;}
    return {created:[],updated,deleted:[]};
  };
  const first=new CollaborationClient(request('first'),'editor-a');const project=snapshot();first.open(project,[]);
  const page=host(first,project);
  async function other(mutator){
    const project=snapshot(),client=new CollaborationClient(request('second'),'editor-a');
    client.open(project,[]);const doc=copy(project.document);mutator(doc);client.mark(doc,[]);
    await client.save(doc,project.name,[]);return snapshot();
  }
  return {first,page,server,requests,committed,release,snapshot,other};
}

async function race({during=false,only=false,echoOlder=false}={}){
  const f=fixture();f.page.edit(doc=>{doc.shots[0].action='v2';});
  const pending=only?f.page.saveObject('shot-x'):f.page.save();
  // Attach an observer immediately: saveObject intentionally propagates a
  // conflict; the global host save catches it and updates its visible state.
  const outcome=pending.then(()=>null,error=>error);
  await f.committed;
  assert.equal(f.server.get('shot-x').revision,2);
  const ownEcho=copy(f.server.get('shot-x'));
  await f.other(doc=>{doc.shots[0].action='v3 from second page';});
  if(during)f.page.edit(doc=>{doc.shots[0].note='typed while saving';});
  f.page.remote([copy(f.server.get('shot-x'))]);
  if(echoOlder)f.page.remote([ownEcho]);
  f.release();const error=await outcome;
  return {...f,error};
}

for(const only of [false,true])for(const during of [false,true]){
  test(`late receipt preserves host/body/CAS consistency (only=${only}, during=${during})`,async()=>{
    const f=await race({only,during});
    const draft=f.first.drafts.entries.get('shot-x');
    console.log('P5-R2 receipt observation:',JSON.stringify({only,during,host:f.page.state.doc.shots[0],
      hostSaved:f.page.state.saved,hostConflict:f.page.state.conflict,
      row:f.first.rows.get('shot:x'),baseline:f.first.baseline.parts.get('shot:x'),draft,
      requests:f.requests,server:f.server.get('shot-x')}));
    // The chosen safe behavior is an explicit conflict, not an invisible
    // revision upgrade. No subsequent timer or note edit may resend v2.
    assert.equal(draft.state,'conflict');
    assert.equal(draft.base.revision,2);assert.equal(draft.remote.revision,3);
    assert.equal(f.first.rows.get('shot:x').revision,2);
    assert.equal(f.first.baseline.parts.get('shot:x').content.shot.action,'v2');
    assert.equal(f.page.state.doc.shots[0].action,'v2');
    assert.equal(f.page.state.doc.shots[0].note,during?'typed while saving':'');
    assert.equal(f.page.state.saved,'保存冲突');assert.equal(f.page.state.conflict,true);
    assert.ok(only?f.error?.status===409:f.error===null);
    const count=f.requests.length;
    f.page.edit(doc=>{doc.shots[0].note='note only after receipt';});
    await f.page.save();await f.page.save();
    assert.equal(f.requests.length,count);
    assert.equal(f.server.get('shot-x').content.shot.action,'v3 from second page');
    assert.equal(f.server.get('shot-x').revision,3);
  });
}

test('note-only autosave after late receipt never silently overwrites unaccepted v3',async()=>{
  const f=await race();
  const before={host:copy(f.page.state),row:copy(f.first.rows.get('shot:x')),
    baseline:copy(f.first.baseline.parts.get('shot:x')),draft:copy(f.first.drafts.entries.get('shot-x'))};
  f.page.edit(doc=>{doc.shots[0].note='only note changed after receipt';});
  await f.page.save();
  console.log('P5-R2 final note observation:',JSON.stringify({before,host:f.page.state,
    row:f.first.rows.get('shot:x'),baseline:f.first.baseline.parts.get('shot:x'),
    draft:f.first.drafts.entries.get('shot-x'),requests:f.requests,server:f.server.get('shot-x')}));
  assert.equal(f.server.get('shot-x').content.shot.action,'v3 from second page');
  assert.equal(f.server.get('shot-x').revision,3);
  assert.equal(f.requests.filter(item=>item.label==='first').length,1);
});

test('older echo cannot replace the newer snapshot cached during flight',async()=>{
  const f=await race({echoOlder:true});
  assert.equal(f.first.drafts.entries.get('shot-x').remote?.revision,3);
  assert.equal(f.page.state.conflict,true);
});

test('own echo and receipt settle normally without another HTTP save',async()=>{
  const f=fixture();f.page.edit(doc=>{doc.shots[0].action='v2';});
  const pending=f.page.save();await f.committed;
  f.page.remote([copy(f.server.get('shot-x'))]);f.release();await pending;
  await f.page.save(); // Existing timer may clear the host's pending dirty flag.
  assert.equal(f.page.state.saved,'已保存');assert.equal(f.page.state.conflict,false);
  assert.equal(f.first.drafts.entries.get('shot-x').state,'saved');
  assert.equal(f.requests.length,1);
  await f.other(doc=>{doc.shots[0].action='normal remote v3';});
  f.page.remote([copy(f.server.get('shot-x'))]);
  assert.equal(f.page.state.doc.shots[0].action,'normal remote v3');
  assert.equal(f.first.rows.get('shot:x').revision,3);
});

test('explicit discard accepts v3 body before a new note save',async()=>{
  const f=await race();
  const latest=copy(f.server.get('shot-x'));
  f.page.acceptObjectDocument(f.first.resolve('shot-x',latest,'discard',f.page.state.doc,[]));
  assert.equal(f.page.state.doc.shots[0].action,'v3 from second page');
  f.page.edit(doc=>{doc.shots[0].note='note on accepted v3';});await f.page.save();
  assert.equal(f.server.get('shot-x').revision,4);
  assert.equal(f.server.get('shot-x').content.shot.action,'v3 from second page');
  assert.equal(f.server.get('shot-x').content.shot.note,'note on accepted v3');
});

test('explicit keep-draft is still CAS checked against a further remote save',async()=>{
  const f=await race({during:true});const compared=copy(f.server.get('shot-x'));
  f.page.acceptObjectDocument(f.first.resolve('shot-x',compared,'keep-draft',f.page.state.doc,[]));
  await f.other(doc=>{doc.shots[0].action='v4 after comparison';});
  await f.page.save();
  assert.equal(f.page.state.conflict,true);
  assert.equal(f.server.get('shot-x').content.shot.action,'v4 after comparison');
  assert.equal(f.page.state.doc.shots[0].note,'typed while saving');
});
