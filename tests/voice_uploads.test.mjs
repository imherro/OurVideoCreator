import test from 'node:test';
import assert from 'node:assert/strict';
import {saveVoiceProfile,setVoiceLocked,acceptVoiceResult,requireTtsVoice,canLockVoice} from '../src/filmBible/voices.ts';
import {resolvedVoice} from '../src/filmBible/voiceResolution.ts';
import {deriveVideoProductionRows} from '../src/videoProduction.ts';
const uploaded={cardId:'hero',version:1,status:'draft',name:'样本',model_id:'',voiceType:'',previewText:'',
 source:{type:'uploaded',originalAssetId:'audio',authorizedAt:'receipt'},parameters:{speechRate:0,emotion:''}};
function document(){return {filmBible:{visual:{cards:{hero:{id:'hero',kind:'character'}},versions:{}},voices:{profiles:{}}},shots:[],nodes:[],edges:[]}}
test('uploaded voice saves without model, preset or text and only locks on an explicit action',()=>{
 const draft=saveVoiceProfile(document(),'hero',uploaded);const voice=draft.filmBible.voices.profiles.hero;
 assert.equal(voice.previewAssetId,'audio');assert.equal(voice.status,'draft');assert.equal(voice.referenceAssetId,undefined);
 const locked=setVoiceLocked(draft,'hero',true),confirmed=locked.filmBible.voices.profiles.hero;
 assert.equal(confirmed.referenceAssetId,'audio');assert.equal(confirmed.referenceVersion,1);
 const next=setVoiceLocked(locked,'hero',false);assert.equal(next.filmBible.voices.profiles.hero.previewAssetId,undefined);
 assert.equal(resolvedVoice(next,{}, {characterCardId:'hero'}).profile.referenceAssetId,'audio');
 assert.throws(()=>saveVoiceProfile(document(),'hero',{...uploaded,source:{...uploaded.source,authorizedAt:''}}),/使用权/);
});
test('new uploaded file advances voice identity and preserves old default and history',()=>{
 const doc=setVoiceLocked(saveVoiceProfile(document(),'hero',uploaded),'hero',true);
 const next=saveVoiceProfile(doc,'hero',{...doc.filmBible.voices.profiles.hero,source:{...uploaded.source,originalAssetId:'new'}});
 const voice=next.filmBible.voices.profiles.hero;
 assert.equal(voice.version,2);assert.equal(voice.status,'draft');assert.equal(voice.previewAssetId,'new');assert.equal(voice.referenceAssetId,undefined);
 assert.equal(voice.defaultVersion,1);assert.equal(voice.lockedVersions['1'].referenceAssetId,'audio');
});
test('uploaded sample rejects late client TTS results and cannot request synthesis',()=>{
 const doc=saveVoiceProfile(document(),'hero',uploaded);
 const job={id:'late',input:{voice_profile:{cardId:'hero',version:1}},result:{assets:[{id:'late-audio',kind:'audio'}]}};
 assert.equal(acceptVoiceResult(doc,job),doc);assert.throws(()=>requireTtsVoice(uploaded),/不能自动逐句/);
 const stored=doc.filmBible.voices.profiles.hero;assert.equal(canLockVoice(stored,{...stored,description:'unsaved'}),false);
});
test('switching back to generated audition requires settings and clears uploaded preview',()=>{
 const doc=saveVoiceProfile(document(),'hero',uploaded);
 assert.throws(()=>saveVoiceProfile(doc,'hero',{...uploaded,source:{type:'doubao_tts'}}),/语音服务/);
 const next=saveVoiceProfile(doc,'hero',{...uploaded,source:{type:'doubao_tts'},model_id:'speech',voiceType:'speaker',previewText:'hello'});
 assert.equal(next.filmBible.voices.profiles.hero.version,2);assert.equal(next.filmBible.voices.profiles.hero.previewAssetId,undefined);
});
test('uploaded voice blocks full dialogue but sample mode needs no TTS settings',()=>{
 const doc=setVoiceLocked(saveVoiceProfile(document(),'hero',uploaded),'hero',true);
 doc.shots=[{id:'shot',videoNode:'video',imageNode:'image',duration:4,videoReferenceMode:'multimodal',dialogueMode:'full_dialogue',dialogues:[{id:'line',characterCardId:'hero',text:'new dialogue'}]}];
 doc.nodes=[{id:'video',data:{kind:'video',model_id:'m',prompt:'walk'}},{id:'image',data:{assetId:'frame'}}];
 const assets=[{id:'frame',kind:'image'},{id:'audio',kind:'audio'}];
 const models=[{id:'m',type:'volcengine_ark',capabilities:{multimodal_reference:true,voice_sample_reference:true}}];
 assert.match(deriveVideoProductionRows(doc,assets,[],models)[0].readinessReason,/上传声音/);
 doc.shots[0].dialogueMode='voice_sample';assert.equal(deriveVideoProductionRows(doc,assets,[],models)[0].readinessReason,'');
});
