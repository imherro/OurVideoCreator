import test from 'node:test';
import assert from 'node:assert/strict';
import {emptyGenerationPolicy,resolveGenerationTarget} from '../src/generationPolicy.ts';

const providers=[
 {id:'ark',type:'volcengine_ark',models:{text:'doubao',image:'seedream',video:'seedance'},local:false},
 {id:'connected-image',kind:'image',model:'flux',local:true},
];

test('generation target resolves only explicit override or project policy',()=>{
 const policy={...emptyGenerationPolicy(),image:{providerId:'ark',modelId:'seedream-custom'}};
 assert.deepEqual(resolveGenerationTarget('image',undefined,policy,providers),{providerId:'ark',modelId:'seedream-custom',source:'project'});
 assert.deepEqual(resolveGenerationTarget('image',{mode:'override',providerId:'connected-image',modelId:'flux-special'},policy,providers),{providerId:'connected-image',modelId:'flux-special',source:'override'});
 assert.throws(()=>resolveGenerationTarget('image',undefined,emptyGenerationPolicy(),providers),/不会自动选择/);
});

test('deleted project provider is invalid and never falls back silently',()=>{
 const policy={...emptyGenerationPolicy(),video:{providerId:'deleted',modelId:'paid'}};
 assert.throws(()=>resolveGenerationTarget('video',undefined,policy,providers),/不会自动切换/);
});
