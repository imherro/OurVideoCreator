import test from 'node:test';
import assert from 'node:assert/strict';
import {defaultVoiceProfile,voiceParameters} from '../src/filmBible/voices.ts';
import {shotParameters} from '../src/generationParameters.ts';

test('voice uses published defaults and submits only published optional controls',()=>{
 const model={id:'voice',kind:'audio',rules:{voice_type:{enum:['allowed']}},defaults:{voice_type:'allowed'}};
 const profile=defaultVoiceProfile('hero',model.id,model.defaults);
 assert.equal(profile.voiceType,'allowed');
 assert.deepEqual(voiceParameters([model],profile,{emotion:'开心',contextTexts:['演绎']}),{voice_type:'allowed'});
 assert.throws(()=>voiceParameters([],profile),/停用或未发布/);
 assert.throws(()=>voiceParameters([model],{...profile,voiceType:'other'}),/允许列表/);
});

test('shot dimensions respect published enums and frames never infer upstream model identity',()=>{
 assert.deepEqual(shotParameters('image',{rules:{resolution:{type:'string',enum:['1024x1024']}}},{resolution:'1024x1024'},{},'9:16'),{resolution:'1024x1024'});
 assert.deepEqual(shotParameters('video',{id:'minimax_h3',rules:{}},{},{duration:8}),{});
 assert.deepEqual(shotParameters('image',{rules:{resolution:{type:'string'}}},{},{},'2:1'),{resolution:'1024x512'});
 const model={rules:{frames:{type:'integer'}},capabilities:{fps:24,min_frames:124,frame_step:17,max_frames:345}};
 assert.equal(shotParameters('video',model,{},{duration:8},undefined,4).frames,124);
});
