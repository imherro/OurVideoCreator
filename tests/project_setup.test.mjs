import test from 'node:test';
import assert from 'node:assert/strict';
import {
  applyRatioChange,
  applyTargetDuration,
  applyVideoOutputSetting,
  bibleFields,
  defaultProjectSetupDraft,
  mergeBibleFields,
  projectSetupPayload,
  validateProjectSetupDraft,
} from '../src/projectSetup.ts';

test('project setup validates required fields and creates the reviewed API payload',()=>{
  const draft=defaultProjectSetupDraft(['text','image','video'].map(kind=>({id:kind,kind,is_default:true})));
  assert.deepEqual(validateProjectSetupDraft(draft),['请输入作品名称']);
  draft.name=' 花信未迟 ';draft.ratio='9:16';draft.duration=60;draft.episodeCount=12;draft.platform='抖音';draft.bible.worldEra='江南';draft.bible.avoidItems='高饱和\n\n磨皮';
  draft.videoResolution='1080p';draft.videoRatio='21:9';draft.videoDuration=8;draft.videoFormat='mov';
  const payload=projectSetupPayload(draft);
  assert.equal(payload.name,'花信未迟');
  assert.equal(payload.episode_title,'第 01 集');
  assert.equal(payload.episode_count,12);
  assert.equal(payload.platform,'抖音');
  assert.equal(payload.video_resolution,'1080p');
  assert.equal(payload.video_ratio,'21:9');
  assert.equal(payload.video_duration,8);
  assert.equal(payload.video_format,'mov');
  assert.deepEqual(payload.generation_policy.text,{model_id:'text'});
  assert.deepEqual(payload.film_bible.story,{worldEra:'江南'});
  assert.deepEqual(payload.film_bible.style.avoidItems,['高饱和','磨皮']);
});

test('Bible settings merge preserves visual versions, style version, and unknown keys',()=>{
  const document={filmBible:{visual:{cards:{hero:{id:'hero'}},versions:{v1:{id:'v1',status:'locked'}}},styleVersion:7,custom:{keep:true},story:{old:'keep'},style:{old:'keep'},continuity:{old:'keep'}}};
  const fields={...bibleFields(document),worldEra:'当代',visualTone:'克制'};
  const next=mergeBibleFields(document,fields);
  assert.equal(next.filmBible.visual,document.filmBible.visual);
  assert.equal(next.filmBible.styleVersion,7);
  assert.deepEqual(next.filmBible.custom,{keep:true});
  assert.equal(next.filmBible.story.old,'keep');
  assert.equal(next.filmBible.style.old,'keep');
});

test('ratio change invalidates top-level and pipeline-only shot nodes without deleting results',()=>{
  const document={ratio:'16:9',shots:[{imageNode:'image-a',videoNode:'video-a'},{pipeline:{imageNodeId:'image-b',videoNodeId:'video-b'}}],nodes:['image-a','video-a','image-b','video-b'].map(id=>({id,data:{assetId:'asset-'+id,resultJob:'job-'+id}})),edges:[],timeline:[{asset_id:'asset-video-a'}],editor:{timeline:{tracks:[]}}};
  const next=applyRatioChange(document,'9:16');
  assert.equal(next.ratio,'9:16');
  assert.deepEqual(next.nodes.map(node=>[node.id,node.data.stale,node.data.assetId]),document.nodes.map(node=>[node.id,true,node.data.assetId]));
  assert.deepEqual(next.timeline,document.timeline);
  assert.equal(next.editor,document.editor);
});

test('target duration changes only the episode planning target',()=>{
  const document={duration:15,shots:[{duration:4,videoNode:'video'}],nodes:[{id:'video',data:{assetId:'asset',stale:false}}],edges:[],timeline:[{duration:4}],editor:{timeline:{tracks:[{elements:[{s:0,e:4}]}]}}};
  const next=applyTargetDuration(document,60);
  assert.equal(next.duration,60);
  assert.equal(next.shots,document.shots);
  assert.equal(next.nodes,document.nodes);
  assert.equal(next.timeline,document.timeline);
  assert.equal(next.editor,document.editor);
});

test('video output setting invalidates video results while preserving assets',()=>{
  const document={videoRatio:'16:9',nodes:[{id:'image',data:{kind:'image',assetId:'frame'}},{id:'video',data:{kind:'video',assetId:'clip'}}],edges:[],shots:[{imageNode:'image',videoNode:'video'}]};
  const next=applyVideoOutputSetting(document,{videoRatio:'21:9',videoFormat:'mov'});
  assert.equal(next.videoRatio,'21:9');
  assert.equal(next.videoFormat,'mov');
  assert.equal(next.nodes[0].data.stale,undefined);
  assert.equal(next.nodes[1].data.stale,true);
  assert.equal(next.nodes[1].data.assetId,'clip');
});
