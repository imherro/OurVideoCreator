import {patchNode,invalidate} from './graph.ts';
import type {Node,Edge} from '@xyflow/react';
import {shotParameters} from './generationParameters.ts';
type Value=Record<string,any>;
export function framesForDuration(model:string,duration:number,caps:Value={}){
 const fps=caps.fps||(model==='minimax_h3'?24:model.startsWith('ltx2')?25:24);
 const min=caps.min_frames||(model==='minimax_h3'?124:17);
 const step=caps.frame_step||(model==='minimax_h3'?17:model.startsWith('ltx2')?8:1);
 const max=caps.max_frames||(model==='minimax_h3'?345:2001);
 return Math.min(min+Math.floor((max-min)/step)*step,Math.max(min,min+Math.round((duration*fps-min)/step)*step));
}
export function updateShot<T extends {shots:Value[];nodes:Node[];edges:Edge[]}>(document:T,id:string,patch:Value):T{
 const shot=document.shots.find(s=>s.id===id);if(!shot)return document;
 const imageNodeId=shot.imageNode||shot.pipeline?.imageNodeId;
 const videoNodeId=shot.videoNode||shot.pipeline?.videoNodeId;
 let next={...document,shots:document.shots.map(s=>s.id===id?{...s,...patch}:s)};
 if('image_prompt' in patch&&imageNodeId)next=patchNode(next,imageNodeId,{prompt:patch.image_prompt});
 if('video_prompt' in patch&&videoNodeId)next=patchNode(next,videoNodeId,{prompt:patch.video_prompt});
 if('duration' in patch&&videoNodeId){
  const data=document.nodes.find(node=>node.id===videoNodeId)?.data;
  if(data)next=patchNode(next,videoNodeId,{parameters:shotParameters('video',
   {rules:data.model_rules,capabilities:data.model_capabilities},data.parameters as Value||{}, {...shot,...patch},undefined,(document as Value).videoDuration)});
  // The server independently derives this from its frozen platform version.
  next=invalidate(next,[videoNodeId]);
 }
 const semanticChanged=['scene','characters','action','emotion','camera'].some(
  field=>field in patch&&JSON.stringify(patch[field])!==JSON.stringify(shot[field])
 );
 if(semanticChanged){
  next=invalidate(next,[imageNodeId,videoNodeId].filter(Boolean));
  next={...next,shots:next.shots.map(s=>s.id===id?{...s,prompts_need_review:true}:s)};
 }
 const audioChanged='audio' in patch&&patch.audio!==shot.audio;
 if(audioChanged){
  next=invalidate(next,[videoNodeId].filter(Boolean));
  next={...next,shots:next.shots.map(s=>s.id===id?{...s,prompts_need_review:true}:s)};
 }
 return next;
}

export function updateLinkedNodePrompt<T extends {shots:Value[];nodes:Node[];edges:Edge[]}>(document:T,nodeId:string,prompt:string):T{
 const shot=document.shots.find(s=>(s.imageNode||s.pipeline?.imageNodeId)===nodeId||(s.videoNode||s.pipeline?.videoNodeId)===nodeId);
 if(!shot)return patchNode(document,nodeId,{prompt});
 const field=(shot.imageNode||shot.pipeline?.imageNodeId)===nodeId?'image_prompt':'video_prompt';
 return updateShot(document,shot.id,{[field]:prompt});
}

/** Migrate prompt edits made in the legacy canvas inspector into canonical shots. */
export function migrateLinkedNodePrompts<T extends {shots:Value[];nodes:Node[];edges:Edge[]}>(document:T):T{
 const nodes=new Map(document.nodes.map(node=>[node.id,node]));
 let changed=false;
 const shots=document.shots.map(shot=>{
  const image=nodes.get(shot.imageNode||shot.pipeline?.imageNodeId);
  const video=nodes.get(shot.videoNode||shot.pipeline?.videoNodeId);
  const patch:Value={};
  if(image&&typeof image.data.prompt==='string'&&image.data.prompt!==shot.image_prompt)patch.image_prompt=image.data.prompt;
  if(video&&typeof video.data.prompt==='string'&&video.data.prompt!==shot.video_prompt)patch.video_prompt=video.data.prompt;
  if(!Object.keys(patch).length)return shot;
  changed=true;return {...shot,...patch};
 });
 return changed?{...document,shots}:document;
}
