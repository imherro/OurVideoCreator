import test from 'node:test';
import assert from 'node:assert/strict';
import {updateShot,framesForDuration,updateLinkedNodePrompt,migrateLinkedNodePrompts} from '../src/shotSync.ts';
test('shot prompt edits update linked inputs and invalidate descendants',()=>{
 const doc={shots:[{id:'s',imageNode:'i',videoNode:'v'}],nodes:['i','v'].map(id=>({id,position:{x:0,y:0},data:{prompt:'old',resultJob:'old-job',model_id:'v',model_rules:{frames:{type:'integer'}},model_capabilities:{fps:24,min_frames:124,frame_step:17,max_frames:345}}})),edges:[{id:'e',source:'i',target:'v'}]};
 const updated=updateShot(doc,'s',{image_prompt:'new'});
 assert.equal(updated.nodes[0].data.prompt,'new');assert.equal(updated.nodes[1].data.prompt,'old');
 assert.ok(updated.nodes.every(n=>n.data.stale));assert.equal(doc.nodes[0].data.prompt,'old');
 const duration=updateShot(doc,'s',{duration:8});assert.equal(duration.nodes[1].data.parameters.frames,192);
});
test('frame conversion respects different model lattices',()=>{
 assert.equal(framesForDuration('minimax_h3',1),124);
 assert.equal(framesForDuration('minimax_h3',30),345);
 assert.equal((framesForDuration('ltx2_22B',5)-17)%8,0);
 assert.equal(framesForDuration('custom',3,{fps:30,min_frames:10,frame_step:10,max_frames:100}),90);
});
test('canvas prompt edits update the canonical shot used by reference compilation',()=>{
 const doc={shots:[{id:'s',imageNode:'i',videoNode:'v',image_prompt:'old image',video_prompt:'old video'}],nodes:[
  {id:'i',position:{x:0,y:0},data:{kind:'image',prompt:'old image',assetId:'image'}},
  {id:'v',position:{x:0,y:0},data:{kind:'video',prompt:'old video',assetId:'video'}},
 ],edges:[{id:'iv',source:'i',target:'v'}]};
 const image=updateLinkedNodePrompt(doc,'i','无手臂、无手掌');
 assert.equal(image.shots[0].image_prompt,'无手臂、无手掌');
 assert.equal(image.nodes[0].data.prompt,'无手臂、无手掌');
 assert.equal(image.nodes[0].data.stale,true);
 assert.equal(image.nodes[1].data.stale,true);
 const video=updateLinkedNodePrompt(doc,'v','角色说出原文');
 assert.equal(video.shots[0].video_prompt,'角色说出原文');
 assert.equal(video.nodes[1].data.prompt,'角色说出原文');
});
test('legacy node-only edits migrate once into canonical shot prompts',()=>{
 const doc={shots:[{id:'s',pipeline:{imageNodeId:'i',videoNodeId:'v'},image_prompt:'old image',video_prompt:'old video'}],nodes:[
  {id:'i',position:{x:0,y:0},data:{prompt:'old image\n无手臂'}},
  {id:'v',position:{x:0,y:0},data:{prompt:'new video'}},
 ],edges:[]};
 const migrated=migrateLinkedNodePrompts(doc);
 assert.equal(migrated.shots[0].image_prompt,'old image\n无手臂');
 assert.equal(migrated.shots[0].video_prompt,'new video');
 assert.equal(migrateLinkedNodePrompts(migrated),migrated);
});
