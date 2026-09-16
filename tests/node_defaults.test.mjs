import test from 'node:test';
import assert from 'node:assert/strict';
import {nodeDefaults} from '../src/nodeDefaults.ts';
test('creation paths require explicit external model policies',()=>{
 const providers=[{id:'cloud',kind:'video',model:'remote'}, {id:'connected-video',kind:'video',local:true,model:'minimax_h3'}, {id:'connected-image',kind:'image',local:true,model:'flux2_klein_base_9b'}];
 const explicit={text:{providerId:'ark',modelId:'doubao-seed'},image:{providerId:'connected-image',modelId:'flux-cloud'},video:{providerId:'cloud',modelId:'remote'}};
 assert.equal(nodeDefaults('video',providers,[],explicit).provider,'cloud');
 assert.equal(nodeDefaults('video',providers,[],explicit).resolution,'832x480');
 assert.equal(nodeDefaults('video',providers,[],explicit).frames,121);
 assert.equal(nodeDefaults('image',providers,[],explicit).provider,'connected-image');
 assert.equal(nodeDefaults('video',[],[]).provider,'');
 const policy={text:{providerId:'ark',modelId:'doubao-seed'},image:{providerId:'connected-image',modelId:'flux-cloud'},video:null};
 const withArk=[...providers,{id:'ark',type:'volcengine_ark',local:false,models:{text:'doubao-seed'}}];
 assert.deepEqual(nodeDefaults('storyboard',withArk,[{id:'qwen'}],policy),{
  provider:'ark',model:'doubao-seed',resolution:'832x480',frames:121,seed:-1,
 });
 assert.equal(nodeDefaults('image',withArk,[],policy).model,'flux-cloud');
});
