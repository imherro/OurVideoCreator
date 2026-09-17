import test from 'node:test';
import assert from 'node:assert/strict';
import {setVoiceLocked,chooseVoiceVersion,saveVoiceProfile,canLockVoice} from '../src/filmBible/voices.ts';
import {lockedVoiceVersions,resolvedVoice,voiceCardId} from '../src/filmBible/voiceResolution.ts';
import {voiceSampleRows} from '../src/dialogueMode.ts';
import {deriveVideoProductionRows} from '../src/videoProduction.ts';
const voice={cardId:'hero',model_id:'speech',voiceType:'voice',name:'常态',version:1,status:'draft',previewText:'hello',previewAssetId:'a1',parameters:{speechRate:0,emotion:''}};
function fixture(){return {shots:[],nodes:[],edges:[],filmBible:{visual:{cards:{hero:{id:'hero',kind:'character'},
 state:{id:'state',kind:'character_state',parentCardId:'hero'},other:{id:'other',kind:'character_state',parentCardId:'hero'}},
 versions:{sv:{cardId:'state'},ov:{cardId:'other'}}},voices:{profiles:{hero:structuredClone(voice)}}}};}
function library(){let doc=setVoiceLocked(fixture(),'hero',true);doc=setVoiceLocked(doc,'hero',false);
 doc.filmBible.voices.profiles.hero.previewAssetId='a2';doc.filmBible.voices.profiles.hero.name='变身';return setVoiceLocked(doc,'hero',true);}
test('named locked history survives new audition; old default stays effective until explicitly selected',()=>{
 const doc=library(),profile=doc.filmBible.voices.profiles.hero;
 assert.equal(profile.version,2);assert.equal(profile.defaultVersion,1);
 assert.deepEqual(Object.values(lockedVoiceVersions(profile)).map(v=>v.name),['常态','变身']);
 assert.equal(resolvedVoice(doc,{}, {characterCardId:'hero'}).profile.referenceAssetId,'a1');
 const next=chooseVoiceVersion(doc,'hero',2);assert.equal(resolvedVoice(next,{}, {characterCardId:'hero'}).profile.referenceAssetId,'a2');
 const draft=setVoiceLocked(next,'hero',false);assert.equal(resolvedVoice(draft,{}, {characterCardId:'hero'}).profile.referenceAssetId,'a2');
});
test('unsaved version name must be saved before locking, without regenerating an unchanged audition',()=>{
 const doc=fixture(),renamed={...voice,name:'新名称'};assert.equal(canLockVoice(voice,renamed),false);
 const saved=saveVoiceProfile(doc,'hero',renamed).filmBible.voices.profiles.hero;
 assert.equal(saved.previewAssetId,'a1');assert.equal(saved.version,1);assert.equal(canLockVoice(saved,renamed),true);
});
test('legacy null default resolves the current profile like the server',()=>{
 const doc=fixture();doc.filmBible.voices.profiles.hero.defaultVersion=null;
 assert.equal(resolvedVoice(doc,{}, {characterCardId:'hero'}).profile,doc.filmBible.voices.profiles.hero);
});
test('state inherits by default, pins immutable parent version without copying profile, and can inherit again',()=>{
 let doc=library();assert.equal(resolvedVoice(doc,{}, {characterCardId:'state'}).cardId,'hero');
 doc=chooseVoiceVersion(doc,'state',1);doc=chooseVoiceVersion(doc,'hero',2);
 assert.equal(resolvedVoice(doc,{}, {characterCardId:'state'}).profile.referenceAssetId,'a1');
 assert.equal(doc.filmBible.voices.profiles.state,undefined);
 doc=chooseVoiceVersion(doc,'state',undefined);assert.equal(resolvedVoice(doc,{}, {characterCardId:'state'}).profile.referenceAssetId,'a2');
 assert.throws(()=>chooseVoiceVersion(doc,'state',999),/已锁定/);
});
test('implicit state is selected from shot bindings; ambiguous states block readiness without crashing',()=>{
 let doc=chooseVoiceVersion(chooseVoiceVersion(library(),'state',1),'other',2);
 const shot={id:'shot',videoNode:'video',duration:4,videoReferenceMode:'multimodal',dialogueMode:'voice_sample',
 dialogues:[{id:'line',characterCardId:'hero',text:'hello'}],assetBindings:{characters:[{versionId:'sv'}]}};
 assert.equal(voiceCardId(doc,shot,shot.dialogues[0]),'state');
 shot.assetBindings.characters.push({versionId:'ov'});
 assert.throws(()=>voiceCardId(doc,shot,shot.dialogues[0]),/多个/);
 assert.equal(voiceCardId(doc,shot,{characterCardId:'state'}),'state');
 assert.match(voiceSampleRows(doc,shot,[])[0].error,/多个/);
 doc.shots=[shot];doc.nodes=[{id:'video',data:{model_id:'video-model',kind:'video',prompt:'walk'}}];
 const row=deriveVideoProductionRows(doc,[],[],[{id:'video-model',capabilities:{multimodal_reference:true,voice_sample_reference:true}}])[0];
 assert.notEqual(row.readinessReason,'');
});
test('full dialogue uses selected state voice identity, not a same-number take from the base role',()=>{
 const doc=chooseVoiceVersion(library(),'state',1);doc.shots=[{id:'shot',videoNode:'video',imageNode:'image',duration:4,
 dialogues:[{id:'line',characterCardId:'state',text:'hello',audioAssetId:'take',audioVoiceVersion:1}]}];
 doc.nodes=[{id:'video',data:{kind:'video',model_id:'m',prompt:'walk'}},{id:'image',data:{assetId:'frame'}}];
 const audio={id:'take',kind:'audio',metadata:{duration:2,input:{dialogue:{id:'line',text:'hello',voiceVersion:1,voiceCardId:'hero'}}}};
 const models=[{id:'m',type:'volcengine_ark'}];const row=()=>deriveVideoProductionRows(doc,[{id:'frame',kind:'image'},audio],[],models)[0];
 assert.match(row().readinessReason,/尚未/);audio.metadata.input.dialogue.voiceCardId='state';assert.equal(row().readinessReason,'');
});
