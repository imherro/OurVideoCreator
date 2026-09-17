type Value=Record<string,any>;
export function motionAssetChoices(assets:Value[],boundId?:string):Value[]{
 const choices=assets.filter(asset=>asset.kind==='video'&&asset.category==='motion_reference'&&!asset.metadata?.motionDerivedFrom);
 if(boundId&&!choices.some(asset=>asset.id===boundId)){
  const prior=assets.find(asset=>asset.id===boundId&&asset.kind==='video');
  choices.unshift(prior?{...prior,historical:true}:{id:boundId,name:'素材已丢失或不可访问',missing:true});
 }
 return choices;
}
export function referencePreviewKey(projectId:string,document:Value,shot:Value,node:Value,assets:Value[],models:Value[]){
 return JSON.stringify([projectId,shot,node,document.filmBible,document.videoDuration,document.videoResolution,
  document.aspectRatio,document.videoAspectRatio,document.generationPolicy,document.videoReferenceMode,document.dialogueMode,
  document.nodes?.map((item:Value)=>[item.id,item.data]),document.edges,models,
  assets.map(asset=>[asset.id,asset.kind,asset.name,asset.category,asset.url,asset.metadata?.duration,asset.metadata?.width,asset.metadata?.height,asset.metadata?.motionDerivedFrom])]);
}
export function promptParts(line:string){return line.split(/(@(?:图片|视频|音频)\d+)/g).filter(Boolean)}
export function referenceMedia(label:string,manifest:Value[],assets:Value[]):Value|undefined{
 const token=/^@(图片|视频|音频)(\d+)$/.exec(label);if(!token)return;
 const kind=({图片:'image',视频:'video',音频:'audio'} as Value)[token[1]];
 const entry=manifest.find(item=>item.kind===kind&&Number(item.index)===Number(token[2]));
 const asset=entry?.assetId&&assets.find(item=>item.id===entry.assetId&&item.kind===kind);
 // A planned job or a future mixed dialogue track is not a playable current asset.
 if(!asset)return;
 return {kind,id:asset.id,name:entry.name||asset.name,url:`/api/assets/${encodeURIComponent(asset.id)}/file`};
}
export async function uploadMotionAsset(file:File,projectId:string,target:string,current:()=>string,
 request:(path:string,init?:RequestInit)=>Promise<any>,onUploaded:(asset:Value)=>void,onBind:(id:string)=>void){
 const form=new FormData();form.append('file',file);
 const asset=await request(`/projects/${projectId}/assets?category=motion_reference`,{method:'POST',body:form});
 if(current()!==target)throw new Error('镜头、作品或绑定已变化；上传素材保留在原作品，未覆盖当前绑定');
 if(asset.kind!=='video')throw new Error('动作参考必须为视频素材');
 onUploaded(asset);onBind(asset.id);return asset;
}
