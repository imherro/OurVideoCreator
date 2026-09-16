import test from 'node:test';
import assert from 'node:assert/strict';
import {importLegacyTimeline,legacyTimelineProjection,reconcileTimelineEdit,timelineSettingsProjection} from '../src/editor/legacyTimeline.ts';

const assets=[
  {id:'v',name:'video',kind:'video',url:'/api/assets/v/file',metadata:{duration:10}},
  {id:'i',name:'still',kind:'image',url:'/api/assets/i/file',metadata:{}},
  {id:'a',name:'music',kind:'audio',url:'/api/assets/a/file',metadata:{duration:20}},
];
test('legacy clips become one canonical Twick timeline with trim, volume and music',()=>{
  const clips=[{id:'c1',asset_id:'v',start:2,duration:4,volume:0.5},
    {id:'c2',asset_id:'i',start:0,duration:3,volume:1}];
  const timeline=importLegacyTimeline(clips,assets,'9:16','a');
  assert.equal(timeline.tracks[0].elements[0].s,0);
  assert.equal(timeline.tracks[0].elements[1].s,4);
  assert.equal(timeline.tracks[0].elements[1].e,7);
  assert.deepEqual(timeline.tracks[0].elements[0].frame.size,[720,1280]);
  assert.equal(timeline.tracks[1].elements[0].metadata.assetId,'a');
  assert.equal(timeline.tracks[1].elements[0].props.loop,true);
  assert.deepEqual(legacyTimelineProjection(timeline),clips);
  assert.deepEqual(Object.keys(timeline.assets).sort(),['a','i','v']);
});
test('legacy import rejects foreign/missing media and invalid trim instead of dropping clips',()=>{
  assert.throws(()=>importLegacyTimeline([{id:'c',asset_id:'missing',start:0,duration:1}],assets),/素材不存在/);
  assert.throws(()=>importLegacyTimeline([{id:'c',asset_id:'v',start:9,duration:4}],assets),/超出/);
  assert.throws(()=>importLegacyTimeline([{id:'c',asset_id:'v',start:-1,duration:4}],assets),/入点/);
  assert.throws(()=>importLegacyTimeline([{id:'c',asset_id:'v',start:0,duration:4}],assets,'16:9','foreign'),/音乐不存在/);
});

function editorDocument(){
  const clips=[{id:'c1',asset_id:'v',start:2,duration:4,volume:0.5},
    {id:'c2',asset_id:'i',start:0,duration:3,volume:1}];
  const timeline=importLegacyTimeline(clips,assets,'16:9','a');
  timeline.tracks[0].elements[1].s+=2;timeline.tracks[0].elements[1].e+=2;
  timeline.tracks[0].elements[0].props.opacity=0.75;
  timeline.tracks.push({id:'text',type:'text',elements:[{id:'title',type:'text',s:1,e:2,props:{text:'保留字幕'}}]});
  timeline.tracks.push({id:'dialogue',type:'audio',elements:[{id:'speech',type:'audio',s:0,e:2,props:{src:'/api/assets/a/file',srcAssetId:'a'},metadata:{assetId:'a',assetSource:'my-video-creator'}}]});
  return {ratio:'16:9',timeline:clips,editor:{version:1,timeline},audio_id:'a',music_volume:0.3};
}

test('legacy trim and volume edit really updates Twick but preserves subtitles, other audio and gaps',()=>{
  const before=editorDocument(),edited=structuredClone(before);
  edited.timeline[0].duration=3;edited.timeline[0].volume=0.7;
  const next=reconcileTimelineEdit(before,edited,assets),track=next.editor.timeline.tracks[0];
  assert.equal(track.elements[0].e,3);assert.equal(track.elements[0].props.volume,0.7);
  assert.equal(track.elements[0].props.opacity,0.75);
  assert.equal(track.elements[1].s,5); // unchanged two-second gap
  assert.deepEqual(next.editor.timeline.tracks.slice(2),before.editor.timeline.tracks.slice(2));
  assert.deepEqual(next.timeline,legacyTimelineProjection(next.editor.timeline));
});

test('music selection, volume and export settings are persisted only inside the timeline',()=>{
  const before=editorDocument(),next=reconcileTimelineEdit(before,{...before,music_volume:0.8,transition:'fade',export_resolution:'1920x1080'},assets);
  assert.deepEqual(timelineSettingsProjection(next.editor.timeline),{
    audio_id:'a',music_volume:0.8,transition:'fade',export_resolution:'1920x1080'});
  const removed=reconcileTimelineEdit(next,{...next,audio_id:''},assets);
  assert.equal(removed.editor.timeline.tracks.flatMap(track=>track.elements).some(item=>item.metadata?.role==='background-music'),false);
  assert.equal(removed.editor.timeline.tracks.find(track=>track.id==='dialogue').elements.length,1);
});

test('Twick edits refresh the read-only legacy view and preserve export settings',()=>{
  const before=editorDocument();before.editor.timeline.ovcExport={transition:'fade'};
  const edited=structuredClone(before);delete edited.editor.timeline.ovcExport;
  edited.editor.timeline.tracks[0].elements[0].props.volume=0.9;
  const next=reconcileTimelineEdit(before,edited,assets);
  assert.equal(next.timeline[0].volume,0.9);assert.equal(next.transition,'fade');
  assert.throws(()=>reconcileTimelineEdit(before,{...edited,timeline:[]},assets),/同时写/);
});
