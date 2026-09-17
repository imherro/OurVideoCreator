import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
  createStoryboardShot,
  moveStoryboardShot,
  projectShotReferences,
  selectedShotImageNodeIds,
  selectedShotVideoNodeIds,
  shotIdentity,
  updateStoryboardShot,
} from '../src/storyboard.ts';

const storyboardWorkspace=readFileSync(new URL('../src/pages/StoryboardWorkspace.tsx',import.meta.url),'utf8');
const storyboardStyles=readFileSync(new URL('../src/style.css',import.meta.url),'utf8');

function fixture(){
  const cards={
    hero:{id:'hero',kind:'character',name:'阿青',parentCardId:null,currentVersionId:'hero-v1',status:'active'},
    friend:{id:'friend',kind:'character',name:'小禾',parentCardId:null,currentVersionId:'friend-v1',status:'active'},
    alley:{id:'alley',kind:'scene',name:'雨巷',parentCardId:null,currentVersionId:'alley-v1',status:'active'},
    letter:{id:'letter',kind:'prop',name:'密信',parentCardId:null,currentVersionId:'letter-v1',status:'active'},
  };
  const versions=Object.fromEntries(Object.values(cards).map((card,index)=>[card.currentVersionId,{
    id:card.currentVersionId,cardId:card.id,version:1,parentVersionId:null,status:'locked',
    spec:{description:card.name,attributes:[]},invariants:[],createdAt:index+1,
    references:[{role:'primary',assetId:`asset-${index+1}`}],provenance:{},
  }]));
  return {
    filmBible:{visual:{cards,versions}},
    shots:[
      {id:'shot-a',uid:'stable-a',duration:3,action:'旧动作',camera:'中景',pipeline:{imageNodeId:'image-a',videoNodeId:'video-a'},assetBindings:{characters:[{role:'阿青',versionId:'hero-v1'},{role:'小禾',versionId:'friend-v1'}],scene:{versionId:'alley-v1'},props:[{role:'密信',versionId:'letter-v1'}]}},
      {id:'shot-b',uid:'stable-b',duration:4,action:'第二镜',camera:'近景',imageNode:'image-b',videoNode:'video-b',pipeline:{imageNodeId:'image-b',videoNodeId:'video-b'},assetBindings:{characters:[],scene:null,props:[]}},
    ],
    nodes:[
      {id:'image-a',data:{kind:'image',prompt:'旧提示',assetId:'frame-a'}},
      {id:'video-a',data:{kind:'video',prompt:'视频',assetId:'clip-a'}},
      {id:'image-b',data:{kind:'image',prompt:'第二镜'}},
      {id:'video-b',data:{kind:'video',prompt:'第二镜视频'}},
    ],
    edges:[{id:'a-video',source:'image-a',target:'video-a'}],
  };
}

test('table edits and reordering preserve canonical shot identity, bindings, and pipeline',()=>{
  const original=fixture();
  const edited=updateStoryboardShot(original,'stable-a',{duration:5,action:'新动作',camera:'俯拍'});
  assert.equal(edited.shots[0].uid,'stable-a');
  assert.equal(edited.shots[0].pipeline.imageNodeId,'image-a');
  assert.deepEqual(edited.shots[0].assetBindings,original.shots[0].assetBindings);
  assert.equal(edited.nodes.find(node=>node.id==='image-a').data.stale,true);
  assert.equal(edited.nodes.find(node=>node.id==='video-a').data.stale,true);
  const moved=moveStoryboardShot(edited,'stable-a',1);
  assert.deepEqual(moved.shots.map(shotIdentity),['stable-b','stable-a']);
  assert.equal(moved.shots[1].pipeline.videoNodeId,'video-a');
});

test('audio edits invalidate only the pipeline video branch',()=>{
  const edited=updateStoryboardShot(fixture(),'stable-a',{audio:'新的环境声'});
  assert.equal(edited.nodes.find(node=>node.id==='image-a').data.stale,undefined);
  assert.equal(edited.nodes.find(node=>node.id==='video-a').data.stale,true);
  assert.equal(edited.shots[0].prompts_need_review,true);
});

test('reference visibility projects canonical bindings in character scene prop order',()=>{
  const rows=projectShotReferences(fixture(),fixture().shots[0]);
  assert.deepEqual(rows.map(row=>row.group),['characters','characters','scene','props']);
  assert.deepEqual(rows.map(row=>row.versionId),['hero-v1','friend-v1','alley-v1','letter-v1']);
  assert.deepEqual(rows.map(row=>row.primaryAssetId),['asset-1','asset-2','asset-3','asset-4']);
});

test('selected generation targets only explicit shots and manual creation performs no generation',()=>{
  const document=fixture();
  assert.deepEqual(selectedShotImageNodeIds(document,['stable-b']),['image-b']);
  assert.deepEqual(selectedShotImageNodeIds(document,['stable-a','missing']),['image-a']);
  assert.deepEqual(selectedShotVideoNodeIds(document,['stable-b']),['video-b']);
  const created=createStoryboardShot(document,()=> 'new-uid');
  assert.equal(created.shots.length,3);
  assert.equal(created.shots[2].uid,'shot-new-uid');
  assert.equal(created.nodes.length,document.nodes.length);
  assert.deepEqual(created.shots[2].assetBindings,{characters:[],scene:null,props:[]});
});

test('image review cards collapse mounted editing controls while planning stays expanded',()=>{
  assert.match(storyboardWorkspace,/props\.purpose === "planning" \? shotFields : <div className="storyboard-image-summary">/);
  assert.match(storyboardWorkspace,/props\.purpose === "planning" \? <>\{bindingEditor\}\{promptEditor\}<\/> : <details className="storyboard-image-details">/);
  assert.match(storyboardWorkspace,/<summary>镜头详情与设置<\/summary>[\s\S]*\{node && props\.renderImageSettings\?\.\(node\)\}[\s\S]*\{promptEditor\}/);
  assert.doesNotMatch(storyboardWorkspace,/<details className="storyboard-image-details" open/);
  assert.match(storyboardWorkspace,/className="storyboard-grid-details"><summary>镜头详情与设置<\/summary>/);
  assert.equal((storyboardWorkspace.match(/props\.renderImageSettings\?\.\(node\)/g)||[]).length,2);
  assert.match(storyboardStyles,/\.storyboard-image-details>summary\{[^}]*cursor:pointer/);
  assert.match(storyboardStyles,/\.storyboard-action-summary\{[^}]*-webkit-line-clamp:2[^}]*overflow-wrap:anywhere/);
});

test('image batch actions float without changing explicit selection submission semantics',()=>{
  assert.match(storyboardWorkspace,/className="storyboard-selection-bar" role="group" aria-label="批量生成分镜图"/);
  assert.match(storyboardWorkspace,/setSelected\(event\.target\.checked \? identities : \[\]\)/);
  assert.match(storyboardWorkspace,/disabled=\{props\.busy \|\| !selected\.length\} onClick=\{\(\) => void generate\(selected\)\}/);
  assert.match(storyboardStyles,/\.storyboard-workspace \.storyboard-selection-bar\{position:fixed;top:auto;right:18px;bottom:28px;z-index:12;/);
  assert.match(storyboardStyles,/@media\(min-width:1200px\)\{\.storyboard-workspace:has\(\.storyboard-selection-bar\)\{padding-right:202px\}\}/);
  assert.match(storyboardStyles,/@media\(max-width:1199px\)\{\.storyboard-workspace:has\(\.storyboard-selection-bar\)\{padding-bottom:170px\}/);
});
