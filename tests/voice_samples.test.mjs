import test from 'node:test';
import assert from 'node:assert/strict';
import {dialogueMode,voiceSampleRows} from '../src/dialogueMode.ts';
import {setVoiceLocked} from '../src/filmBible/voices.ts';
import {defaultProjectSetupDraft,projectSetupPayload} from '../src/projectSetup.ts';
import {deriveVideoProductionRows} from '../src/videoProduction.ts';
const profile={cardId:'hero',model_id:'speech',voiceType:'voice',version:1,status:'draft',previewText:'preview',previewAssetId:'sample',generationJobId:'adopted'};
const asset={id:'sample',kind:'audio',metadata:{duration:12}};
function document(){return {shots:[{id:'shot',videoNode:'video',duration:4,dialogueMode:'voice_sample',videoReferenceMode:'multimodal',
 dialogues:[{id:'line1',characterCardId:'hero',text:'actual words'},{id:'line2',characterCardId:'hero',text:'more words'}]}],
 nodes:[{id:'video',data:{kind:'video',model_id:'video-model',prompt:'walk'}}],edges:[],filmBible:{voices:{profiles:{hero:{...profile}}}}};}
test('old projects retain full dialogue; new web projects explicitly choose samples; shot override wins',()=>{
 assert.equal(dialogueMode({},{}),'full_dialogue');
 assert.equal(dialogueMode({dialogueMode:'voice_sample'},{dialogueMode:'full_dialogue'}),'full_dialogue');
 assert.equal(projectSetupPayload(defaultProjectSetupDraft([])).dialogue_mode,'voice_sample');
});
test('confirmation pins adopted preview version; deriving clears both references and preview',()=>{
 const locked=setVoiceLocked(document(),'hero',true);
 const voice=locked.filmBible.voices.profiles.hero;
 assert.equal(voice.referenceAssetId,'sample');assert.equal(voice.referenceVersion,1);
 assert.equal(voiceSampleRows(locked,locked.shots[0],[asset]).length,1);
 assert.equal(voiceSampleRows(locked,locked.shots[0],[asset])[0].ready,true);
 const next=setVoiceLocked(locked,'hero',false).filmBible.voices.profiles.hero;
 assert.equal(next.version,2);assert.equal(next.referenceAssetId,undefined);assert.equal(next.previewAssetId,undefined);
});
test('sample readiness checks confirmation, catalog and explicit mode but never extends shot to sample duration',()=>{
 const doc=setVoiceLocked(document(),'hero',true);
 const model={id:'video-model',type:'hc_atom',capabilities:{multimodal_reference:true,voice_sample_reference:true,audio_reference:true,audio_only_reference:true}};
 const row=()=>deriveVideoProductionRows(doc,[asset],[],[model])[0];
 assert.equal(row().readinessReason,'');assert.equal(row().effectiveDuration,4);assert.deepEqual(row().dialogueAudioAssets,[]);
 doc.filmBible.voices.profiles.hero.referenceVersion=0;assert.match(row().readinessReason,/已确认/);
 doc.filmBible.voices.profiles.hero.referenceVersion=1;model.capabilities.voice_sample_reference=false;assert.match(row().readinessReason,/未发布/);
 model.capabilities.voice_sample_reference=true;doc.shots[0].videoReferenceMode='strict_first_frame';assert.notEqual(row().readinessReason,'');
});
