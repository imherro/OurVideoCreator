import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {stripTypeScriptTypes} from 'node:module';
import {planBatchGeneration,assetBatchFeedback} from '../src/batchGeneration.ts';

const providers=[
  {id:'ark',name:'Ark',kind:'image',local:false,models:{image:'seedream'}},
  {id:'video-local',name:'Video',kind:'video',local:true,model:'wan'},
];

function stateFixture(){
  return {generationPolicy:{image:{model_id:'ark'}},filmBible:{visual:{
    cards:{hero:{id:'hero',kind:'character',name:'主角',currentVersionId:'hero-v1',status:'active'},
      wet:{id:'wet',kind:'character_state',name:'淋雨状态',parentCardId:'hero',currentVersionId:'wet-v1',status:'active'}},
    versions:{'hero-v1':{id:'hero-v1',cardId:'hero',version:1,status:'draft',references:[]},
      'wet-v1':{id:'wet-v1',cardId:'wet',status:'draft',parentVersionId:'hero-v1',references:[]}}
  }}};
}

test('parent lifecycle remains waiting until explicit adoption and locking; planning never writes',()=>{
  for(const [status,pattern] of [['queued',/正在生成/],['running',/正在生成/],['succeeded',/明确采纳/],['interrupted',/中断/],['failed',/失败/]]){
    const document=stateFixture();
    const jobs=[{node_id:'visual-version:hero-v1',status,result:{assets:[{id:'candidate'}]}}];
    const before=structuredClone({document,jobs});
    const plan=planBatchGeneration(document,jobs,providers,[],'assets');
    assert.equal(plan.waiting.length,1);
    assert.match(plan.waiting[0].reason,pattern);
    assert.equal(plan.readyIds.includes('wet-v1'),false);
    assert.deepEqual(plan.blocked,[]);
    assert.deepEqual({document,jobs},before);
    const feedback=assetBatchFeedback(plan,0);
    assert.equal(feedback.error,'');
    assert.match(feedback.notice,/再次点击.*不会自动续跑/);
  }
  const document=stateFixture();
  const parent=document.filmBible.visual.versions['hero-v1'];
  parent.references=[{role:'primary',assetId:'adopted'}];
  parent.status='pending_reference';
  assert.equal(planBatchGeneration(document,[],providers,[],'assets').waiting.length,1);
  parent.status='locked';
  const ready=planBatchGeneration(document,[],providers,[],'assets');
  assert.deepEqual(ready.readyIds,['wet-v1']);
  assert.deepEqual(ready.waiting,[]);
  assert.equal(ready.cloudCount,1);
});

test('invalid parent relations stay blocked, deleted state cards never queue',()=>{
  const corruptions=[
    v=>delete v.versions['hero-v1'],
    v=>delete v.cards.hero,
    v=>v.cards.hero.deletedAt=1,
    v=>v.cards.hero.status='deprecated',
    v=>v.versions['hero-v1'].status='deprecated',
    v=>v.cards.wet.parentCardId='other',
    v=>v.versions['hero-v1'].status='locked',
  ];
  for(const corrupt of corruptions){
    const document=stateFixture();corrupt(document.filmBible.visual);
    const plan=planBatchGeneration(document,[],providers,[],'assets');
    assert.equal(plan.waiting.length,0);
    assert.ok(plan.blocked.some(item=>item.id==='wet-v1'));
    assert.equal(plan.readyIds.includes('wet-v1'),false);
    assert.match(assetBatchFeedback(plan,0).error,/未提交/);
  }
  const document=stateFixture();document.filmBible.visual.cards.wet.deletedAt=1;
  const plan=planBatchGeneration(document,[],providers,[],'assets');
  assert.deepEqual(plan.readyIds,['hero-v1']);
  assert.deepEqual(plan.waiting,[]);
  assert.deepEqual(plan.blocked,[]);
});

test('waiting does not hide actual submission failures and repeated planning is deterministic',()=>{
  const document=stateFixture();
  const plan=planBatchGeneration(document,[],providers,[],'assets');
  assert.deepEqual(planBatchGeneration(document,[],providers,[],'assets'),plan);
  const feedback=assetBatchFeedback(plan,0,['服务端拒绝：无对象写权限']);
  assert.match(feedback.notice,/等待基础图/);
  assert.match(feedback.error,/无对象写权限/);
});

test('actual asset batch handler reports waiting without submitting state tasks or swallowing server errors',async()=>{
  const main=fs.readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8');
  const handler=stripTypeScriptTypes(main.slice(main.indexOf('  async function runSmartBatch('),main.indexOf('  async function changeAssetCategory(')));
  for(const mode of ['ready','waiting-only','server-reject']){
    const document=stateFixture();
    const jobs=mode==='waiting-only'?[{node_id:'visual-version:hero-v1',status:'succeeded',result:{assets:[{id:'candidate'}]}}]:[];
    const submitted=[];const state={notice:'',error:'old error',busy:false};
    const env={current:{current:{project:{id:'p1'},doc:document}},busy:false,jobs,config:{models:providers},system:{models:[]},
      planBatchGeneration,assetBatchFeedback,setNotice:v=>state.notice=v,setError:v=>state.error=v,setBusy:v=>state.busy=v,
      generateVisualReference:async id=>{submitted.push(id);if(mode==='server-reject')throw new Error('无对象写权限');},
      report:e=>{throw e;}};
    await new Function(...Object.keys(env),`${handler}; return runSmartBatch;`)(...Object.values(env))('assets');
    assert.deepEqual(submitted,mode==='waiting-only'?[]:['hero-v1']);
    assert.match(state.notice,/再次点击.*不会自动续跑/);
    assert.equal(state.busy,false);
    if(mode==='server-reject')assert.match(state.error,/无对象写权限/);
    else assert.equal(state.error,'');
  }
});

test('asset batch queues missing roots and waits for parent approval before states',()=>{
  const document={
    nodes:[],shots:[],
    generationPolicy:{text:null,image:{model_id:'ark'},video:null},
    filmBible:{visual:{
      cards:{
        hero:{id:'hero',kind:'character',name:'主角',parentCardId:null,currentVersionId:'hero-v1',status:'active'},
        wet:{id:'wet',kind:'character_state',name:'淋雨状态',parentCardId:'hero',currentVersionId:'wet-v1',status:'active'},
      },
      versions:{
        'hero-v1':{id:'hero-v1',cardId:'hero',status:'draft',references:[]},
        'wet-v1':{id:'wet-v1',cardId:'wet',status:'draft',parentVersionId:'hero-v1',references:[]},
      },
    }},
  };
  const plan=planBatchGeneration(document,[],providers,[],'assets');
  assert.deepEqual(plan.readyIds,['hero-v1']);
  assert.equal(plan.cloudCount,1);
  assert.deepEqual(plan.blocked,[]);
  assert.equal(plan.waiting[0].parentVersionId,'hero-v1');
  assert.match(plan.waiting[0].reason,/锁定/);
});

test('shot batches are incremental and video waits for a reviewed current frame',()=>{
  const document={
    filmBible:{visual:{cards:{},versions:{}}},generationPolicy:{text:null,image:null,video:null},
    shots:[
      {id:'S1',imageNode:'image-1',videoNode:'video-1'},
      {id:'S2',imageNode:'image-2',videoNode:'video-2'},
    ],
    nodes:[
      {id:'image-1',data:{kind:'image',prompt:'灯完全熄灭',model_id:'ark',assetId:'frame-1',stale:false,state_reviewed:false}},
      {id:'video-1',data:{kind:'video',prompt:'灯亮起',model_id:'video-local'}},
      {id:'image-2',data:{kind:'image',prompt:'街景',model_id:'ark',assetId:'old-frame',stale:true}},
      {id:'video-2',data:{kind:'video',prompt:'推进镜头',model_id:'video-local'}},
    ],
  };
  const images=planBatchGeneration(document,[],providers,[],'shot_images');
  assert.deepEqual(images.readyIds,['image-2']);
  assert.equal(images.skipped[0].id,'image-1');
  const videos=planBatchGeneration(document,[],providers,[],'shot_videos');
  assert.deepEqual(videos.readyIds,[]);
  assert.match(videos.blocked[0].reason,/核验首帧/);
  assert.match(videos.blocked[1].reason,/过期/);
});

test('running work is skipped to prevent duplicate batch submissions',()=>{
  const document={
    filmBible:{visual:{cards:{},versions:{}}},generationPolicy:{text:null,image:null,video:null},
    shots:[{id:'S1',imageNode:'image-1'}],
    nodes:[{id:'image-1',data:{kind:'image',prompt:'画面',model_id:'ark'}}],
  };
  const jobs=[{node_id:'image-1',status:'queued'}];
  const plan=planBatchGeneration(document,jobs,providers,[],'shot_images');
  assert.deepEqual(plan.readyIds,[]);
  assert.match(plan.skipped[0].reason,/队列/);
});

test('shot image batch blocks missing or unapproved film bible bindings',()=>{
  const document={filmBible:{visual:{cards:{hero:{id:'hero',status:'active'}},versions:{'hero-v1':{id:'hero-v1',cardId:'hero',status:'draft',references:[]}}}},shots:[{id:'S1',imageNode:'image-1',assetBindings:{characters:[],scene:null,props:[]}}],nodes:[{id:'image-1',data:{kind:'image',prompt:'主角入场',model_id:'ark'}}]};
  const missing=planBatchGeneration(document,[],providers,[],'shot_images');
  assert.match(missing.blocked[0].reason,/尚未绑定/);
  document.shots[0].assetBindings.characters=[{versionId:'hero-v1'}];
  const unlocked=planBatchGeneration(document,[],providers,[],'shot_images');
  assert.match(unlocked.blocked[0].reason,/尚未锁定/);
});
