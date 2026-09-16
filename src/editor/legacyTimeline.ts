/** Legacy Clip[] is an import/projection of the single Twick timeline source. */
import type {Clip} from '../timeline.ts';
import type {ProjectJSON, ElementJSON} from '@twick/timeline';
import {attachAssetReferences, editorResolution, type EditorAsset} from './editorDocument.ts';
import {equalContent} from '../objectDrafts.ts';

type Value=Record<string,any>;
const EXPORT_KEYS=['transition','export_resolution','music_volume'] as const;

export function importLegacyTimeline(clips: Clip[], assets: EditorAsset[], ratio='16:9', audioId?: string): ProjectJSON {
  const size = editorResolution(ratio);
  let cursor = 0;
  const elements: ElementJSON[] = clips.map(clip => {
    const asset = assets.find(item => item.id === clip.asset_id);
    if (!asset || !['video','image'].includes(asset.kind)) throw new Error('旧剪辑引用的画面素材不存在');
    const start = Number(clip.start), duration = Number(clip.duration);
    if (!Number.isFinite(start) || start < 0 || !Number.isFinite(duration) || duration <= 0) {
      throw new Error('旧剪辑时长或素材入点无效');
    }
    const mediaDuration = Number(asset.metadata?.duration);
    if (asset.kind === 'video' && (!Number.isFinite(mediaDuration) || start + duration > mediaDuration + 0.08)) {
      throw new Error('旧剪辑超出原视频时长');
    }
    const begin = cursor;
    cursor += duration;
    return {id:clip.id,trackId:'t-legacy-v1',type:asset.kind as 'video'|'image',name:asset.name,s:begin,e:cursor,
      props:{src:asset.url,srcAssetId:asset.id,time:start,playbackRate:1,volume:clip.volume ?? 1},
      metadata:{assetId:asset.id,assetSource:'my-video-creator',legacyClipId:clip.id},
      frame:{x:0,y:0,size:[size.width,size.height]},objectFit:'cover',
      ...(asset.kind === 'video' ? {mediaDuration} : {})};
  });
  const timeline: ProjectJSON = {version:2,backgroundColor:'#000000',
    tracks:[{id:'t-legacy-v1',name:'V1 · 导入旧剪辑',type:'video',elements}]};
  if (audioId && cursor > 0) {
    const audio = assets.find(item => item.id === audioId && item.kind === 'audio');
    if (!audio) throw new Error('旧剪辑背景音乐不存在');
    timeline.tracks.push({id:'t-legacy-music',name:'A1 · 背景音乐',type:'audio',elements:[{
      id:'legacy-background-music',trackId:'t-legacy-music',type:'audio',name:audio.name,s:0,e:cursor,
      props:{src:audio.url,srcAssetId:audio.id,time:0,playbackRate:1,volume:0.3,loop:true},
      metadata:{assetId:audio.id,assetSource:'my-video-creator',role:'background-music'},
      mediaDuration:Number(audio.metadata?.duration)||cursor,
    }]});
  }
  return attachAssetReferences(timeline, assets);
}

/** A read-only convenience view; it cannot represent overlays or mixed audio. */
export function legacyTimelineProjection(timeline: ProjectJSON): Clip[] {
  const track = timeline.tracks.find(item => item.type === 'video');
  return (track?.elements || []).filter(item => ['video','image'].includes(item.type)).map(item => ({
    id:item.id,asset_id:String(item.metadata?.assetId || item.props?.srcAssetId || ''),
    start:Number(item.props?.time || 0),duration:Math.max(0,Number(item.e)-Number(item.s)),
    volume:Number(item.props?.volume ?? 1),
  }));
}

export function timelineSettingsProjection(timeline:ProjectJSON):Value {
  const music=timeline.tracks.flatMap(track=>track.elements).find(item=>item.metadata?.role==='background-music');
  return {...((timeline as Value).ovcExport||{}),audio_id:music?.metadata?.assetId||music?.props?.srcAssetId||'',
    music_volume:music?.props?.volume??(timeline as Value).ovcExport?.music_volume??0.3};
}

/** Translate only explicit legacy edits into the one timeline. Other Twick
 * tracks, text, overlays, frame/effect props and unchanged gaps are retained. */
export function reconcileTimelineEdit(before:Value,after:Value,assets:EditorAsset[]):Value {
  const clipsChanged=!equalContent(before.timeline,after.timeline);
  const musicChanged=before.audio_id!==after.audio_id||before.music_volume!==after.music_volume;
  const settingsChanged=EXPORT_KEYS.some(key=>before[key]!==after[key]);
  const editorChanged=!equalContent(before.editor?.timeline,after.editor?.timeline);
  if(!clipsChanged&&!musicChanged&&!settingsChanged&&!editorChanged)return after;
  if(editorChanged){
    if(clipsChanged||musicChanged)throw new Error('同一操作不能同时写简剪和高级剪辑，请分别编辑');
    const timeline=structuredClone(after.editor.timeline);
    // The embedded editor may omit app-specific export settings.
    (timeline as Value).ovcExport={...((before.editor?.timeline as Value)?.ovcExport||{}),...((timeline as Value).ovcExport||{})};
    return {...after,...timelineSettingsProjection(timeline),timeline:legacyTimelineProjection(timeline),
      editor:{...after.editor,timeline}};
  }
  const timeline:ProjectJSON=structuredClone(before.editor?.timeline||importLegacyTimeline(before.timeline||[],assets,before.ratio,before.audio_id));
  if(clipsChanged){
    const imported=importLegacyTimeline(after.timeline||[],assets,after.ratio);
    let track=timeline.tracks.find(item=>item.type==='video');
    if(!track){track=imported.tracks[0];timeline.tracks.unshift(track);}
    else{
      const old=track.elements.filter(item=>['video','image'].includes(item.type)),byId=new Map(old.map(item=>[item.id,item]));
      const next=imported.tracks[0].elements;
      // Keep gaps when old order is retained. Reordering explicitly concatenates
      // this primary visual track only; subtitles/audio remain where authored.
      const oldOrder=old.map(item=>item.id),retained=next.filter(item=>byId.has(item.id)).map(item=>item.id);
      const sameOrder=equalContent(oldOrder.filter(id=>retained.includes(id)),retained);
      let end=0,previousOldEnd=0;
      const updated=next.map(item=>{
        const previous=byId.get(item.id),duration=item.e-item.s;
        const gap=sameOrder&&previous?Math.max(0,previous.s-previousOldEnd):0;
        const start=end+gap;end=start+duration;
        if(previous)previousOldEnd=previous.e;
        return {...(previous||item),type:item.type,s:start,e:end,trackId:track!.id,
          props:{...previous?.props,...item.props},metadata:{...previous?.metadata,...item.metadata},
          ...(item.mediaDuration!==undefined?{mediaDuration:item.mediaDuration}:{})};
      });
      track.elements=[...updated,...track.elements.filter(item=>!['video','image'].includes(item.type))];
    }
  }
  if(musicChanged||clipsChanged){
    const currentMusic=timeline.tracks.flatMap(track=>track.elements).find(item=>item.metadata?.role==='background-music');
    const audioId=after.audio_id??currentMusic?.metadata?.assetId??currentMusic?.props?.srcAssetId;
    for(const track of timeline.tracks)track.elements=track.elements.filter(item=>item.metadata?.role!=='background-music');
    if(audioId){
      const asset=assets.find(item=>item.id===audioId&&item.kind==='audio');
      if(!asset)throw new Error('背景音乐不存在');
      const end=Math.max(0,...timeline.tracks.flatMap(track=>track.elements.map(item=>item.e)));
      let track=timeline.tracks.find(item=>item.id==='t-legacy-music');
      if(!track){track={id:'t-legacy-music',name:'A1 · 背景音乐',type:'audio',elements:[]};timeline.tracks.push(track);}
      track.elements.push({...(currentMusic||{}),id:currentMusic?.id||'legacy-background-music',trackId:track.id,
        type:'audio',name:asset.name,s:0,e:end,mediaDuration:Number(asset.metadata?.duration)||end,
        props:{...currentMusic?.props,src:asset.url,srcAssetId:asset.id,time:0,playbackRate:1,loop:true,volume:after.music_volume??0.3},
        metadata:{...currentMusic?.metadata,assetId:asset.id,assetSource:'my-video-creator',role:'background-music'}});
    }
  }
  const settings={...((timeline as Value).ovcExport||{})};
  for(const key of EXPORT_KEYS)if(after[key]!==undefined)settings[key]=after[key];
  (timeline as Value).ovcExport=settings;
  return {...after,...timelineSettingsProjection(timeline),timeline:legacyTimelineProjection(timeline),
    editor:{version:1,...after.editor,timeline:attachAssetReferences(timeline,assets)}};
}
