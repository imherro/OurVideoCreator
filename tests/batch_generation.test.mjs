import test from 'node:test';
import assert from 'node:assert/strict';
import {planBatchGeneration} from '../src/batchGeneration.ts';

const providers=[
  {id:'ark',name:'Ark',kind:'image',local:false,models:{image:'seedream'}},
  {id:'video-local',name:'Video',kind:'video',local:true,model:'wan'},
];

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
  assert.match(plan.blocked[0].reason,/锁定父版本/);
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
