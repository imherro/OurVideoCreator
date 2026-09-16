import test from 'node:test';
import assert from 'node:assert/strict';
import {nodeDefaults} from '../src/nodeDefaults.ts';
test('creation paths require explicit published platform model policies',()=>{
 const models=[{id:'cloud',kind:'video',defaults:{resolution:'832x480',frames:121}},
 {id:'connected-image',kind:'image',defaults:{}},{id:'text',kind:'text',defaults:{max_tokens:100}}];
 const policy={text:{model_id:'text'},image:{model_id:'connected-image'},video:{model_id:'cloud'}};
 assert.equal(nodeDefaults('video',models,[],policy).model_id,'cloud');
 assert.equal(nodeDefaults('video',models,[],policy).parameters.resolution,'832x480');
 assert.equal(nodeDefaults('video',models,[],policy).parameters.frames,121);
 assert.equal(nodeDefaults('image',models,[],policy).model_id,'connected-image');
 assert.equal(nodeDefaults('video',models,[]).model_id,'');
 assert.deepEqual(nodeDefaults('storyboard',models,[],policy),{
  model_id:'text',parameters:{max_tokens:100},model_capabilities:{},model_rules:{},
 });
 assert.throws(()=>nodeDefaults('image',[],[],policy),/不会自动切换/);
});
