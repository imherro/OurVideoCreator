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
  for(const name of ['ratio','aspect_ratio']){
   const rule=rules[name];if(!rule)continue;
   if(rule.type!=='string'||(rule.enum&&!rule.enum.includes(ratio))||(rule.max_length&&ratio.length>rule.max_length))
    throw new Error('平台模型不支持当前项目画幅，请调整模型或项目规格');
   result[name]=ratio;
  }
  for(const name of ['size','resolution']){
   const rule=rules[name];if(!rule||rule.type!=='string')continue;
   if(name==='resolution'&&(/^\d+(k|p)$/i.test(String(result[name]||''))
     ||(rule.enum&&!rule.enum.some((value:any)=>/^\d+x\d+$/.test(String(value))))))continue;
   const size=ratio==='2:1'?'1024x512':imageSizeForRatio(ratio);
   if((!rule.enum||rule.enum.includes(size))&&(!rule.max_length||size.length<=rule.max_length)){result[name]=size;continue;}
   const match=String(result[name]||'').match(/^(\d+)x(\d+)$/),[a,b]=ratio.split(':').map(Number);
   if(match&&(!rule.enum||rule.enum.includes(result[name]))&&(!rule.max_length||String(result[name]).length<=rule.max_length)
     &&Number(match[2])>0&&Math.abs(Number(match[1])/Number(match[2])/(a/b)-1)<=.02)continue;
   throw new Error('平台允许的图像尺寸与项目画幅不一致，请调整模型尺寸规则或项目规格');
  }
 }
 return result;
}
