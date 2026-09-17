import test from 'node:test';
import assert from 'node:assert/strict';
import {saveVoiceProfile,acceptVoiceResult,canLockVoice} from '../src/filmBible/voices.ts';
const profile={cardId:'hero',model_id:'speech',voiceType:'voice',version:1,status:'draft',previewText:'旧试听',
 parameters:{speechRate:0,emotion:''},previewAssetId:'old',generationJobId:'old-job'};
const doc={shots:[],nodes:[],edges:[],filmBible:{voices:{profiles:{hero:profile}}}};
for(const [name,patch] of Object.entries({text:{previewText:'新试听'},rate:{parameters:{speechRate:10,emotion:''}},emotion:{parameters:{speechRate:0,emotion:'开心'}}})){
 test(`voice identity ${name} change clears stale preview and advances version`,()=>{
  const saved=saveVoiceProfile(doc,'hero',{...profile,...patch}).filmBible.voices.profiles.hero;
  assert.equal(saved.version,2);assert.equal(saved.previewAssetId,undefined);assert.equal(saved.generationJobId,undefined);
 });
}
test('locked voice cannot be changed by a late client preview result',()=>{
 const locked={...doc,filmBible:{voices:{profiles:{hero:{...profile,status:'locked'}}}}};
 const result=acceptVoiceResult(locked,{id:'late',input:{voice_profile:{cardId:'hero',version:1}},result:{assets:[{id:'new',kind:'audio'}]}});
 assert.deepEqual(result,locked);
});
test('unsaved audition settings disable lock; whitespace-only edits preserve preview',()=>{
 assert.equal(canLockVoice(profile,{...profile,previewText:'other'}),false);
 assert.equal(canLockVoice(profile,{...profile,previewText:' 旧试听 '}),true);
 const saved=saveVoiceProfile(doc,'hero',{...profile,previewText:' 旧试听 '}).filmBible.voices.profiles.hero;
 assert.equal(saved.version,1);assert.equal(saved.previewAssetId,'old');
});
