import test from 'node:test';
import assert from 'node:assert/strict';
import {
  acceptVisualReferenceResult,
  attachUploadedPrimaryReference,
  lockVisualVersion,
  planVisualReferenceGeneration,
  primaryReference,
  resolveVisualGenerationTarget,
  setVisualCardImageOverride,
} from '../src/filmBible/references.ts';
import {updateDraftVisualVersion} from '../src/filmBible/commands.ts';

const providers=[
  {id:'seedream-project',name:'Ark image',kind:'image'},
  {id:'flux-special',name:'Maestro image',kind:'image'},
];

function fixture(){
  return {
    generationPolicy:{text:null,image:{model_id:'seedream-project'},video:null},
    filmBible:{visual:{cards:{
      hero:{id:'hero',kind:'character',name:'林岚',parentCardId:null,currentVersionId:'hero-v1',status:'active',source:{type:'script_extraction'}},
      wet:{id:'wet',kind:'character_state',name:'雨中的林岚',parentCardId:'hero',currentVersionId:'wet-v1',status:'active',source:{type:'script_extraction'}},
    },versions:{
      'hero-v1':{id:'hero-v1',cardId:'hero',version:1,parentVersionId:null,status:'draft',spec:{description:'灰色风衣，短发',attributes:[{name:'外套',value:'灰色风衣'}]},invariants:['脸型不变'],references:[],createdAt:1,provenance:{}},
      'wet-v1':{id:'wet-v1',cardId:'wet',version:1,parentVersionId:'hero-v1',status:'draft',spec:{description:'衣服被雨淋湿',attributes:[]},invariants:['仍是灰色风衣'],references:[],createdAt:2,provenance:{}},
    }},continuity:{},style:{},story:{}},shots:[],nodes:[],edges:[],timeline:[],characters:[],brief:'',style:'电影写实',ratio:'16:9',duration:15,
  };
}

test('visual card override wins over the project image policy and inherit restores it',()=>{
  let doc=fixture();
  let card=doc.filmBible.visual.cards.hero;
  assert.deepEqual(resolveVisualGenerationTarget(card,doc.generationPolicy,providers),{
    model_id:'seedream-project',source:'project',
  });
  doc=setVisualCardImageOverride(doc,'hero',{mode:'override',model_id:'flux-special'});
  card=doc.filmBible.visual.cards.hero;
  assert.deepEqual(resolveVisualGenerationTarget(card,doc.generationPolicy,providers),{
    model_id:'flux-special',source:'override',
  });
  doc=setVisualCardImageOverride(doc,'hero',{mode:'inherit'});
  assert.equal(resolveVisualGenerationTarget(doc.filmBible.visual.cards.hero,doc.generationPolicy,providers).source,'project');
});

test('uploaded primary reference requires human locking and locked versions are immutable',()=>{
  let doc=fixture();
  assert.throws(()=>lockVisualVersion(doc,'hero-v1'),/只有待确认参考图/);
  doc=setVisualCardImageOverride(doc,'hero',{mode:'override',model_id:'seedream-manual'});
  doc=attachUploadedPrimaryReference(doc,'hero-v1',{id:'asset-uploaded',name:'hero.png'},10);
  assert.equal(doc.filmBible.visual.versions['hero-v1'].status,'pending_reference');
  assert.deepEqual(primaryReference(doc.filmBible.visual.versions['hero-v1']),{
    role:'primary',assetId:'asset-uploaded',source:'uploaded',createdAt:10,provenance:{filename:'hero.png'},
  });
  doc=lockVisualVersion(doc,'hero-v1',11);
  assert.equal(doc.filmBible.visual.versions['hero-v1'].status,'locked');
  assert.equal(doc.filmBible.visual.versions['hero-v1'].provenance.lockedAt,11);
  assert.throws(()=>attachUploadedPrimaryReference(doc,'hero-v1',{id:'replacement'}),/不能替换/);
  assert.throws(()=>updateDraftVisualVersion(doc,'hero-v1',{spec:{description:'改写',attributes:[]},invariants:[]}),/不可修改/);
  assert.throws(
    ()=>setVisualCardImageOverride(doc,'hero',{mode:'override',model_id:'another-model'}),
    /生成策略不可修改/,
  );
  assert.throws(()=>setVisualCardImageOverride(doc,'hero',{mode:'inherit'}),/生成策略不可修改/);
});

test('state generation requires and sends the locked parent reference',()=>{
  const target={model_id:'seedream',source:'project'};
  let doc=fixture();
  assert.throws(()=>planVisualReferenceGeneration(doc,'wet-v1',target,{image_reference:true}),/先确认并锁定父版本/);
  doc=lockVisualVersion(attachUploadedPrimaryReference(doc,'hero-v1',{id:'asset-parent'}),'hero-v1');
  assert.throws(()=>planVisualReferenceGeneration(doc,'wet-v1',target,{image_reference:false}),/纯文生图生成会破坏身份一致性/);
  assert.throws(()=>planVisualReferenceGeneration(doc,'wet-v1',target,undefined),/未明确支持参考图/);
  const plan=planVisualReferenceGeneration(doc,'wet-v1',target,{image_reference:true});
  assert.deepEqual(plan.assetIds,['asset-parent']);
  assert.equal(plan.parentVersionId,'hero-v1');
  assert.equal(plan.parentReferenceAssetId,'asset-parent');
  assert.match(plan.prompt,/必须以输入参考图中的身份/);
});

test('generated primary reference preserves immutable job and parent provenance',()=>{
  let doc=fixture();
  doc=lockVisualVersion(attachUploadedPrimaryReference(doc,'hero-v1',{id:'asset-parent'}),'hero-v1');
  const plan=planVisualReferenceGeneration(doc,'wet-v1',{model_id:'seedream',source:'override'},{image_reference:true});
  doc.filmBible.visual.versions['wet-v1'].status='pending_reference';
  doc.filmBible.visual.versions['wet-v1'].provenance.referenceGeneration={
    submissionId:'submission-reference-1',jobId:'job-reference-1',createdAt:20,
    model_id:plan.model_id,targetSource:plan.targetSource,
    prompt:plan.prompt,parentVersionId:plan.parentVersionId,
    parentReferenceAssetId:plan.parentReferenceAssetId,
  };
  assert.equal(doc.filmBible.visual.versions['wet-v1'].status,'pending_reference');
  doc=acceptVisualReferenceResult(doc,{
    id:'job-reference-1',submission_id:'submission-reference-1',node_id:'visual-version:wet-v1',result:{assets:[{id:'asset-generated'}]},
  },21);
  const reference=primaryReference(doc.filmBible.visual.versions['wet-v1']);
  assert.equal(reference.assetId,'asset-generated');
  assert.equal(reference.source,'generated');
  assert.equal(reference.provenance.jobId,'job-reference-1');
  assert.equal(reference.provenance.submissionId,'submission-reference-1');
  assert.equal(reference.provenance.providerId,undefined);
  assert.equal(reference.provenance.model_id,'seedream');
  assert.equal(reference.provenance.targetSource,'override');
  assert.equal(reference.provenance.parentVersionId,'hero-v1');
  assert.equal(reference.provenance.parentReferenceAssetId,'asset-parent');
  assert.equal(reference.provenance.prompt,plan.prompt);
});

test('persisted submission ownership recovers after reload and applies idempotently',()=>{
  let doc=fixture();
  doc.filmBible.visual.versions['hero-v1'].status='pending_reference';
  doc.filmBible.visual.versions['hero-v1'].provenance.referenceGeneration={
    submissionId:'submission-reload-1',createdAt:20,model_id:'seedream',
    targetSource:'project',prompt:'角色定妆',
  };
  doc=structuredClone(doc);
  const job={
    id:'job-reload-1',submission_id:'submission-reload-1',node_id:'visual-version:hero-v1',
    result:{assets:[{id:'asset-reloaded'}]},
  };
  const applied=acceptVisualReferenceResult(doc,job,30);
  assert.equal(primaryReference(applied.filmBible.visual.versions['hero-v1']).assetId,'asset-reloaded');
  assert.deepEqual(acceptVisualReferenceResult(applied,job,31),applied);
});

test('late result from an older submission cannot replace the current generation',()=>{
  let doc=fixture();
  doc.filmBible.visual.versions['hero-v1'].status='pending_reference';
  doc.filmBible.visual.versions['hero-v1'].provenance.referenceGeneration={
    submissionId:'submission-B',jobId:'job-B',createdAt:20,model_id:'seedream',
    targetSource:'project',prompt:'第二次生成',
  };
  const lateA={id:'job-A',submission_id:'submission-A',node_id:'visual-version:hero-v1',result:{assets:[{id:'asset-A'}]}};
  assert.deepEqual(acceptVisualReferenceResult(doc,lateA,30),doc);
  const currentB={id:'job-B',submission_id:'submission-B',node_id:'visual-version:hero-v1',result:{assets:[{id:'asset-B'}]}};
  doc=acceptVisualReferenceResult(doc,currentB,31);
  assert.equal(primaryReference(doc.filmBible.visual.versions['hero-v1']).assetId,'asset-B');
});
