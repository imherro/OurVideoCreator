import {imageSizeForRatio} from './mediaSpecs.ts';
type Value=Record<string,any>;

/** Derived controls use published rules, never hidden upstream model names. */
export function shotParameters(kind:string,model:Value,parameters:Value,shot:Value={},ratio?:string,fixedDuration?:number){
 const result={...parameters},rules=model.rules||{},caps=model.capabilities||{};
 const duration=Number.isInteger(fixedDuration)&&Number(fixedDuration)>=4&&Number(fixedDuration)<=30?Number(fixedDuration):Number(shot.duration);
 if(kind==='video'&&rules.frames&&caps.fps&&caps.min_frames&&caps.frame_step&&caps.max_frames&&duration>0){
  const min=caps.min_frames,step=caps.frame_step,max=caps.max_frames;
  result.frames=Math.min(min+Math.floor((max-min)/step)*step,Math.max(min,min+Math.round((duration*caps.fps-min)/step)*step));
 }
 if(kind==='image'&&ratio){
  const name=rules.resolution?'resolution':rules.size?'size':null;
  if(name&&rules[name].type==='string'){
   const size=ratio==='2:1'?'1024x512':imageSizeForRatio(ratio);
   if(!rules[name].enum||rules[name].enum.includes(size))result[name]=size;
  }
 }
 return result;
}
