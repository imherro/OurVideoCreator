import test from 'node:test';
import assert from 'node:assert/strict';
import {videoGenerationMode,motionCharacters} from '../src/motionReference.ts';
import {defaultProjectSetupDraft,projectSetupPayload} from '../src/projectSetup.ts';
import {updateShot} from '../src/shotSync.ts';
import {deriveVideoProductionRows} from '../src/videoProduction.ts';

test('new UI projects explicitly choose multimodal, old documents stay legacy',()=>{
 assert.equal(projectSetupPayload(defaultProjectSetupDraft([])).video_reference_mode,'multimodal');
 assert.equal(videoGenerationMode({},{}),'legacy');
 assert.equal(videoGenerationMode({videoReferenceMode:'multimodal'},{}),'multimodal');
 assert.equal(videoGenerationMode({videoReferenceMode:'multimodal'},{videoReferenceMode:'first_frame'}),'first_frame');
});
test('motion actor menu includes bound state and base, not unrelated roles',()=>{
 const doc={filmBible:{visual:{cards:{state:{id:'state',parentCardId:'base'},base:{id:'base'},other:{id:'other'}},versions:{v:{cardId:'state'}}}}};
 assert.deepEqual(motionCharacters(doc,{assetBindings:{characters:[{versionId:'v'}]}}).map(x=>x.id),['state','base']);
});
test('switching shot mode preserves bindings and local edits only bump its owned video',()=>{
 const doc={shots:[{id:'s',videoNode:'v',motionReference:{assetId:'motion',cameraMode:'use_shot_camera'}}],nodes:[
  {id:'v',data:{kind:'video',assetId:'old',end_asset_id:'tail'}},{id:'other',data:{kind:'video',assetId:'other-old'}}],edges:[{source:'v',target:'other'}]};
 const updated=updateShot(doc,'s',{videoReferenceMode:'first_frame'});
 assert.deepEqual(updated.shots[0].motionReference,doc.shots[0].motionReference);
 assert.equal(updated.nodes[0].data.end_asset_id,'tail');
 assert.equal(updated.nodes[0].data.generation_revision,1);
 assert.equal(updated.nodes[0].data.stale,true);
 assert.deepEqual(updated.nodes[1],doc.nodes[1]); // server handles other owners' stale flags transactionally
});
test('multimodal accepts video-only or bound visual references but rejects missing capability and excessive duration',()=>{
 const doc={videoReferenceMode:'multimodal',shots:[{id:'s',videoNode:'v',duration:2,motionReference:{assetId:'motion'}}],nodes:[{id:'v',data:{kind:'video',prompt:'动作',model_id:'m'}}]};
 const assets=[{id:'motion',kind:'video'}],models=[{id:'m',kind:'video',type:'hc_atom',capabilities:{multimodal_reference:true,video_reference:true,max_video_duration:15}}];
 let row=deriveVideoProductionRows(doc,assets,[],models)[0];assert.equal(row.status,'ready');assert.equal(row.submissionDuration,4);
 assert.match(deriveVideoProductionRows(doc,assets,[],[{...models[0],capabilities:{}}])[0].readinessReason,/未发布多模态/);
 const visual={...doc,shots:[{id:'s',videoNode:'v',duration:2,assetBindings:{characters:[{versionId:'locked'}]}}]};
 assert.equal(deriveVideoProductionRows(visual,[],[],models)[0].status,'ready');
 row=deriveVideoProductionRows({...doc,shots:[{...doc.shots[0],duration:35}]},assets,[],models)[0];
 assert.match(row.readinessReason,/时长上限/);assert.equal(row.submissionDuration,35);
 assert.equal(deriveVideoProductionRows(doc,assets,[{node_id:'v',status:'running'}],models)[0].status,'generating');
});
