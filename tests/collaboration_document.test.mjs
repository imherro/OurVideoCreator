import test from 'node:test';
import assert from 'node:assert/strict';
import {splitCollaborationDocument,composeCollaborationDocument,changedDocumentParts} from '../src/collaborationDocument.ts';

function document(){return {schemaVersion:6,brief:'story',style:'film',ratio:'16:9',duration:15,
  generationPolicy:{text:null,image:null,video:null},characters:[],
  modelPool:{text:[{model_id:'text-a'}],image:[],video:[],audio:[]},
  filmBible:{styleVersion:1,story:{premise:'premise'},visual:{cards:{},versions:{}},voices:{profiles:{}}},
  nodes:[{id:'image-x',position:{x:1,y:2},data:{kind:'image',prompt:'x'}},
    {id:'image-y',position:{x:3,y:4},data:{kind:'image',prompt:'y'}},
    {id:'free',position:{x:10,y:20},data:{kind:'text',text:'free text'}}],
  shots:[{uid:'shot-x',id:'S01',order:1,imageNode:'image-x',image_prompt:'x'},
    {uid:'shot-y',id:'S02',order:2,imageNode:'image-y',image_prompt:'y'}],
  edges:[],timeline:[]};}

test('one shot and its child node form one save without touching another shot or graph revision',()=>{
  const before=document(),after=structuredClone(before);
  after.shots[0].image_prompt='changed';after.nodes[0].data.prompt='changed';
  const delta=changedDocumentParts(splitCollaborationDocument(before),splitCollaborationDocument(after));
  assert.deepEqual(delta.updated.map(part=>[part.kind,part.key]),[['shot','shot-x']]);
  assert.equal(delta.episodeMetadata,false);assert.equal(delta.productionMetadata,false);
  assert.equal(delta.created.length,0);assert.equal(delta.removed.length,0);
});
test('node selection and browser viewport are private, positions and ordering are structure-only',()=>{
  const before=document(),after=structuredClone(before);
  after.nodes[0].selected=true;after.nodes[0].dragging=false;after.nodes[0].measured={width:300,height:200};
  after.viewport={x:300,y:40,zoom:2};after.playhead=24;after.panel='assets';
  let delta=changedDocumentParts(splitCollaborationDocument(before),splitCollaborationDocument(after));
  assert.equal(delta.updated.length,0);assert.equal(delta.episodeMetadata,false);
  after.nodes[0].position.x=50;after.shots.reverse();
  delta=changedDocumentParts(splitCollaborationDocument(before),splitCollaborationDocument(after));
  assert.deepEqual(delta.updated.map(part=>part.kind),['graph']);
});
test('split/compose preserves shot identity, linked nodes, free nodes and production metadata',()=>{
  const original=document(),snapshot=splitCollaborationDocument(original),result=composeCollaborationDocument(snapshot);
  assert.deepEqual(result.shots,original.shots);assert.deepEqual(result.nodes,original.nodes);
  assert.deepEqual(result.filmBible,original.filmBible);assert.equal(result.brief,'story');
  assert.deepEqual(result.modelPool,original.modelPool);
  const roundtrip=changedDocumentParts(snapshot,splitCollaborationDocument(result));
  assert.equal(roundtrip.updated.length,0);assert.equal(roundtrip.episodeMetadata,false);
});
test('project model pool is production metadata, never episode metadata',()=>{
  const split=splitCollaborationDocument(document());
  assert.deepEqual(split.productionMetadata.modelPool,document().modelPool);
  assert.equal('modelPool' in split.episodeMetadata,false);
});
test('voice and versions share their visual card boundary, not a free graph node',()=>{
  const value=document();
  value.filmBible.visual={cards:{c:{id:'c',currentVersionId:'v'}},versions:{v:{id:'v',cardId:'c',version:1,status:'locked'}}};
  value.filmBible.voices.profiles.c={cardId:'c',version:1,status:'locked'};
  value.nodes.push({id:'visual-version:v',type:'visualAsset',position:{x:50,y:50},data:{kind:'visual_asset',managed:true,visualVersionId:'v'}});
  const split=splitCollaborationDocument(value);
  assert.equal(split.parts.has('node:visual-version:v'),false);
  assert.equal(split.parts.get('visual_card:c').content.voice_profile.status,'locked');
  const composed=composeCollaborationDocument(split);
  assert.deepEqual(composed.filmBible,value.filmBible);
  assert.deepEqual(composed.nodes.find(node=>node.id==='visual-version:v').position,{x:50,y:50});
  assert.equal(changedDocumentParts(split,splitCollaborationDocument(composed)).updated.length,0);
});
test('a child node shared by two shots is rejected instead of becoming an edit bypass',()=>{
  const value=document();value.shots[1].imageNode='image-x';
  assert.throws(()=>splitCollaborationDocument(value),/两个镜头/);
});
