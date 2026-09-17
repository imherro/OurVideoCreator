import {useEffect,useState} from 'react';
import {motionCharacters,videoGenerationMode,videoModeLabels} from '../motionReference';
import {dialogueMode,dialogueModeLabels,voiceSampleRows} from '../dialogueMode';
import './motionReference.css';
type Value=Record<string,any>;
type Props={document:Value;shot:Value;node:Value;assets:Value[];models:Value[];projectId:string;
 request:(path:string,init?:RequestInit)=>Promise<any>;onPatch:(patch:Value)=>void;onUploaded:(asset:Value)=>void};

export function MotionReferenceEditor(props:Props){
 const {document,shot,node,assets,models,projectId,request,onPatch,onUploaded}=props;
 const [open,setOpen]=useState(false),[working,setWorking]=useState(false),[uploading,setUploading]=useState(false);
 const [result,setResult]=useState<{key:string;spec:Value}>(),[error,setError]=useState(''),[revision,setRevision]=useState(0);
 const mode=videoGenerationMode(document,shot),reference=shot.motionReference;
 const model=models.find(item=>item.id===node.data.model_id);
 const supported=model?.capabilities?.multimodal_reference===true;
 const body=JSON.stringify({node_id:node.id,model_id:node.data.model_id,node_data:node.data,
  shot:{motionReference:reference??null,videoReferenceMode:shot.videoReferenceMode||'',dialogueMode:shot.dialogueMode||'',duration:shot.duration,
   video_prompt:shot.video_prompt??node.data.prompt,camera:shot.camera||''},videoReferenceMode:document.videoReferenceMode||'legacy',dialogueMode:document.dialogueMode||'full_dialogue'});
 useEffect(()=>{
  if(!open)return;
  let active=true;setWorking(true);setError('');setResult(undefined);
  const timer=window.setTimeout(()=>request(`/projects/${projectId}/video-spec`,{
   method:'POST',headers:{'Content-Type':'application/json'},body}).then(spec=>{if(active)setResult({key:body,spec})})
   .catch(reason=>{if(active)setError(reason.message||String(reason))}).finally(()=>{if(active)setWorking(false)}),300);
  return()=>{active=false;window.clearTimeout(timer)};
 },[open,body,projectId,request,revision]);
 const spec=result?.key===body?result.spec:undefined;
 const bind=(assetId:string)=>onPatch({motionReference:assetId?{...reference,assetId,cameraMode:reference?.cameraMode||'use_shot_camera'}:null});
 const upload=async(file?:File)=>{
  if(!file)return;setUploading(true);setError('');
  try{const form=new FormData();form.append('file',file);
   const asset=await request(`/projects/${projectId}/assets?category=reference`,{method:'POST',body:form});
   onUploaded(asset);bind(asset.id);
  }catch(reason:any){setError(reason.message||String(reason))}finally{setUploading(false)}
 };
 return <section className="motion-reference-editor" aria-label="动作参考与视频模式">
  <label>对白方式<select value={shot.dialogueMode||''} onChange={event=>onPatch({dialogueMode:event.target.value})}>
   <option value="">跟随本集（{dialogueModeLabels[document.dialogueMode||'full_dialogue']}）</option>
   {Object.entries(dialogueModeLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
  {dialogueMode(document,shot)==='voice_sample'&&<div><small>仅参考音色，不复述样本；本镜台词和情绪保持。样本时长不延长镜头。</small>
   {voiceSampleRows(document,shot,assets).map((row:any)=><p key={row.cardId}>{row.name} · {row.error||(row.ready?`已确认 V${row.profile.version}`:'缺少当前版本已确认样本')}</p>)}</div>}
  <label>视频生成模式<select value={shot.videoReferenceMode||''} onChange={event=>onPatch({videoReferenceMode:event.target.value})}>
   <option value="">跟随项目（{videoModeLabels[document.videoReferenceMode||'legacy']}）</option>
   {Object.entries(videoModeLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
  <small>{mode==='multimodal'?'图片是构图与外观参考，不是严格首尾帧。':mode==='legacy'?'沿用历史提交规则；使用动作视频须明确切换为多模态参考。':'严格帧模式不能混入动作视频或固定对白音频；切换须由你明确选择。'}</small>
  {mode==='multimodal'&&!supported&&<p className="warning">所选平台模型未发布多模态能力；绑定保留，不自动换模型。</p>}
  <details><summary>动作参考视频{reference?' · 已绑定':''}</summary>
   <label>已有视频<select value={reference?.assetId||''} onChange={event=>bind(event.target.value)}>
    <option value="">不使用动作视频</option>{assets.filter(asset=>asset.kind==='video').map(asset=><option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></label>
   <label>上传 MP4<input type="file" accept="video/mp4,.mp4" disabled={uploading} onChange={event=>{void upload(event.target.files?.[0]);event.target.value=''}}/></label>
   <small>最多一段完整视频；解绑不删除素材、不添加剪辑片段。提交时移除原声，不裁剪或变速。</small>
   {reference&&<><label>动作角色<select value={reference.characterCardId||''} onChange={event=>onPatch({motionReference:{...reference,characterCardId:event.target.value}})}>
    <option value="">按本镜动作主体</option>{motionCharacters(document,shot).map(card=><option key={card.id} value={card.id}>{card.name}</option>)}</select></label>
    <label>摄像机<select value={reference.cameraMode} onChange={event=>onPatch({motionReference:{...reference,cameraMode:event.target.value}})}>
     <option value="use_shot_camera">只参考动作，使用本镜运镜</option><option value="follow_reference">同时参考视频运镜</option></select></label>
    <label>补充说明<textarea maxLength={4000} value={reference.description||''} onChange={event=>onPatch({motionReference:{...reference,description:event.target.value}})}/></label>
   </>}
  </details>
  <div className="motion-preview-actions"><button type="button" onClick={()=>setOpen(!open)}>{open?'收起':'预览'}最终提交与参考清单（不生成）</button>
   {open&&<button type="button" disabled={working} onClick={()=>setRevision(revision+1)}>刷新预览</button>}</div>
  {open&&<div className="motion-preview" aria-live="polite">
   {working&&<p>正在本地检查参考素材…</p>}
   {spec&&<><p>计划 {spec.planned_shot_duration} 秒 · 提交 {spec.shot_duration} 秒{spec.motion_reference?` · 动作 ${Number(spec.motion_reference.media.duration).toFixed(2)} 秒`:''}</p>
    <p>提交模式：{videoModeLabels[spec.generation_mode?.actual]||spec.generation_mode?.actual||'兼容历史'}</p>
    {(spec.motion_warnings||[]).map((warning:string)=><p className="warning" key={warning}>{warning}</p>)}
    <ul>{(spec.reference_manifest||[]).map((item:Value)=><li key={`${item.kind}:${item.index}`}>
     @{({image:'图片',video:'视频',audio:'音频'} as Value)[item.kind]}{item.index} · {item.name} · {item.purpose||item.audio||''}</li>)}</ul>
    <pre>{spec.prompt}</pre><details><summary>冻结参数预览</summary><pre>{JSON.stringify(spec.parameters,null,2)}</pre></details>
   </>}
  </div>}
  {error&&<p className="error" role="alert">{error}</p>}
 </section>
}
