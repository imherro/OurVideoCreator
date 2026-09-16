import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyGenerationPolicy,resolveGenerationTarget} from '../src/generationPolicy.ts';

const providers=[
 {id:'seedream-custom',kind:'image'},
 {id:'flux-special',kind:'image'},
];

test('generation target resolves only explicit override or project policy',()=>{
 const policy={...emptyGenerationPolicy(),image:{model_id:'seedream-custom'}};
 assert.deepEqual(resolveGenerationTarget('image',undefined,policy,providers),{model_id:'seedream-custom',source:'project'});
 assert.deepEqual(resolveGenerationTarget('image',{mode:'override',model_id:'flux-special'},policy,providers),{model_id:'flux-special',source:'override'});
 assert.throws(()=>resolveGenerationTarget('image',undefined,emptyGenerationPolicy(),providers),/不会自动切换/);
});

test('deleted project provider is invalid and never falls back silently',()=>{
 const policy={...emptyGenerationPolicy(),video:{model_id:'deleted'}};
 assert.throws(()=>resolveGenerationTarget('video',undefined,policy,providers),/不会自动切换/);
});
