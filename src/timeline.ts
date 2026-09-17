export type Clip={id:string;asset_id:string;start:number;duration:number;volume?:number;playbackRate?:number};
export function clipSourceTime(clip:Clip, offset:number){return Number(clip.start||0)+offset*Number(clip.playbackRate??1)}
export function timelinePosition(clips:Clip[],time:number){
  let begin=0;
  for(let index=0;index<clips.length;index++){
    const duration=Math.max(.1,Number(clips[index].duration)||.1);
    if(time<begin+duration||index===clips.length-1){
      return {index,clip:clips[index],offset:Math.max(0,Math.min(duration,time-begin)),begin,duration};
    }
    begin+=duration;
  }
  return null;
}
export function timelineDuration(clips:Clip[]){return clips.reduce((sum,c)=>sum+Math.max(.1,Number(c.duration)||.1),0)}
