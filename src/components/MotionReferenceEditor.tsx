import {useEffect,useRef,useState} from 'react';
import {ChevronDown,RefreshCw} from 'lucide-react';
import {motionCharacters,videoGenerationMode,videoModeLabels} from '../motionReference';
import {dialogueMode,dialogueModeLabels,voiceSampleRows} from '../dialogueMode';
import {motionAssetChoices,referencePreviewKey,uploadMotionAsset} from '../referencePresentation';
import {ReferencePrompt} from './ReferencePrompt';
import './motionReference.css';
type Value=Record<string,any>;
type Props={document:Value;shot:Value;node:Value;assets:Value[];models:Value[];projectId:string;busy?:boolean;
 request:(path:string,init?:RequestInit)=>Promise<any>;onPatch:(patch:Value)=>void;onUploaded:(asset:Value)=>void};

export function MotionReferenceEditor(props:Props){
 const {document,shot,node,assets,models,projectId,request,onPatch,onUploaded}=props;
 const [open,setOpen]=useState(false),[working,setWorking]=useState(false),[uploading,setUploading]=useState(false);
 const [result,setResult]=useState<{key:string;spec:Value}>(),[error,setError]=useState(''),[revision,setRevision]=useState(0);
 const [uploadError,setUploadError]=useState('');
 const mode=videoGenerationMode(document,shot),reference=shot.motionReference;
 const model=models.find(item=>item.id===node.data.model_id);
 const supported=model?.capabilities?.multimodal_reference===true;
 const previewKey=referencePreviewKey(projectId,document,shot,node,assets,models);
 const target=JSON.stringify([projectId,shot.uid||shot.id,node.id,reference]);
 const currentTarget=useRef(target);currentTarget.current=target;
 const mounted=useRef(true);useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;currentTarget.current=''}},[]);
 useEffect(()=>{setUploadError('')},[target]);
 const body=JSON.stringify({node_id:node.id,model_id:node.data.model_id,node_data:node.data,
  shot:{motionReference:reference??null,videoReferenceMode:shot.videoReferenceMode||'',dialogueMode:shot.dialogueMode||'',duration:shot.duration,
   video_prompt:shot.video_prompt??node.data.prompt,camera:shot.camera||''},videoReferenceMode:document.videoReferenceMode||'legacy',dialogueMode:document.dialogueMode||'full_dialogue'});
 useEffect(()=>{
  if(!open){setWorking(false);return;}
  let active=true;setWorking(true);setError('');setResult(undefined);
  const timer=window.setTimeout(()=>request(`/projects/${projectId}/video-spec`,{
   method:'POST',headers:{'Content-Type':'application/json'},body}).then(spec=>{if(active)setResult({key:previewKey,spec})})
   .catch(reason=>{if(active)setError(reason.message||String(reason))}).finally(()=>{if(active)setWorking(false)}),300);
  return()=>{active=false;window.clearTimeout(timer)};
 },[open,body,previewKey,projectId,request,revision]);
 const spec=result?.key===previewKey?result.spec:undefined;
 const bind=(assetId:string)=>onPatch({motionReference:assetId?{...reference,assetId,cameraMode:reference?.cameraMode||'use_shot_camera'}:null});
 const upload=async(file?:File)=>{
  if(!file)return;setUploading(true);setUploadError('');
  try{await uploadMotionAsset(file,projectId,target,()=>currentTarget.current,request,onUploaded,bind)}
  catch(reason:any){if(mounted.current)setUploadError(reason.message||String(reason))}
  finally{if(mounted.current)setUploading(false)}
 };
 return <section className="motion-reference-editor" aria-label="动作参考与视频模式">
  <label>对白方式<select value={shot.dialogueMode||''} onChange={event=>onPatch({dialogueMode:event.target.value})}>
   <option value="">跟随本集（{dialogueModeLabels[document.dialogueMode||'full_dialogue']}）</option>
   {Object.entries(dialogueModeLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
  {dialogueMode(document,shot)==='voice_sample'&&voiceSampleRows(document,shot,assets).filter((row:any)=>!row.ready).map((row:any)=><p className="warning" key={row.cardId}>{row.name} · {row.error||'缺少当前版本已确认样本'}</p>)}
  <label>视频生成模式<select value={shot.videoReferenceMode||''} onChange={event=>onPatch({videoReferenceMode:event.target.value})}>
   <option value="">跟随项目（{videoModeLabels[document.videoReferenceMode||'legacy']}）</option>
   {Object.entries(videoModeLabels).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label>
  <small>{mode==='multimodal'?'图片是构图与外观参考，不是严格首尾帧。':mode==='legacy'?'沿用历史提交规则；使用动作视频须明确切换为多模态参考。':'严格帧模式不能混入动作视频或固定对白音频；切换须由你明确选择。'}</small>
  {mode==='multimodal'&&!supported&&<p className="warning">所选平台模型未发布多模态能力；绑定保留，不自动换模型。</p>}
  <details><summary>动作参考视频{reference?' · 已绑定':''}</summary>
   <label>从作品素材选择动作参考（支持白模）<select aria-label="动作参考视频" disabled={uploading||props.busy} value={reference?.assetId||''} onChange={event=>bind(event.target.value)}>
    <option value="">不使用动作视频</option>{motionAssetChoices(assets,reference?.assetId).map(asset=><option key={asset.id} value={asset.id}>{asset.name}{asset.historical?'（历史绑定）':''}{asset.metadata?.duration?` · ${Number(asset.metadata.duration).toFixed(2)}秒`:''}</option>)}</select></label>
   <label>从电脑上传动作参考（MP4）<input aria-label="上传动作参考 MP4" type="file" accept="video/mp4,.mp4" disabled={uploading||props.busy} onChange={event=>{void upload(event.target.files?.[0]);event.target.value=''}}/></label>
   <small>此处只列动作参考分类；已有其他视频可先在素材库归类，历史绑定仍保留。</small>
   <small>最多一段完整视频；解绑不删除素材、不添加剪辑片段。提交时移除原声，不裁剪或变速。</small>
   {reference&&<><ReferencePrompt prompt="@视频1" manifest={[{kind:'video',index:1,assetId:reference.assetId}]} assets={assets}/>
    <label>动作角色<select value={reference.characterCardId||''} onChange={event=>onPatch({motionReference:{...reference,characterCardId:event.target.value}})}>
    <option value="">按本镜动作主体</option>{motionCharacters(document,shot).map(card=><option key={card.id} value={card.id}>{card.name}</option>)}</select></label>
    <label>摄像机<select value={reference.cameraMode} onChange={event=>onPatch({motionReference:{...reference,cameraMode:event.target.value}})}>
     <option value="use_shot_camera">只参考动作，使用本镜运镜</option><option value="follow_reference">同时参考视频运镜</option></select></label>
    <label>补充说明<textarea maxLength={4000} value={reference.description||''} onChange={event=>onPatch({motionReference:{...reference,description:event.target.value}})}/></label>
   </>}
  </details>
  {uploadError&&<p className="error" role="alert">{uploadError}</p>}
  <div className="motion-preview-actions"><button type="button" className="motion-preview-toggle" aria-expanded={open} onClick={()=>setOpen(!open)}><ChevronDown size={15} style={{transform:open?undefined:'rotate(-90deg)'}}/>最终提交与参考清单（不生成）</button>
   <button type="button" className="icon-button" title="刷新最终提交与参考清单" aria-label="刷新最终提交与参考清单" disabled={open&&working} onClick={()=>{setOpen(true);setRevision(value=>value+1)}}><RefreshCw size={15} className={open&&working?'spin':''}/></button></div>
  {open&&<div className="motion-preview" aria-live="polite">
   {working&&<p>正在本地检查参考素材…</p>}
   {spec&&<><p>计划 {spec.planned_shot_duration} 秒 · 提交 {spec.shot_duration} 秒{spec.motion_reference?` · 动作 ${Number(spec.motion_reference.media.duration).toFixed(2)} 秒`:''}</p>
    <p>提交模式：{videoModeLabels[spec.generation_mode?.actual]||spec.generation_mode?.actual||'兼容历史'}</p>
    {(spec.motion_warnings||[]).map((warning:string)=><p className="warning" key={warning}>{warning}</p>)}
    <ReferencePrompt prompt={String(spec.prompt||'')} manifest={spec.reference_manifest||[]} assets={assets}/>
    <details><summary>完整参考清单、原始提示词与参数</summary>
     <ul>{(spec.reference_manifest||[]).map((item:Value)=><li key={`${item.kind}:${item.index}`}>
      <ReferencePrompt prompt={`@${({image:'图片',video:'视频',audio:'音频'} as Value)[item.kind]}${item.index}`} manifest={spec.reference_manifest||[]} assets={assets}/>
      {item.name} · {item.purpose||item.audio||''}{!item.assetId?'（计划引用，尚无独立可播放文件）':''}</li>)}</ul>
     <pre>{spec.prompt}</pre><pre>{JSON.stringify(spec.parameters,null,2)}</pre></details>
    {(spec.voice_samples||[]).map((sample:Value)=><p key={sample.characterCardId}>{sample.characterName} · {sample.source==='uploaded'?'上传声音':'生成试听'} V{sample.voiceVersion} → 音频 {sample.index} · {Number(sample.media.duration).toFixed(2)}秒</p>)}
   </>}
  </div>}
  {open&&<small>本镜参数可预览未保存值；共享角色等依赖取服务端已保存版本，保存后可刷新。预览不生成。</small>}
  {open&&error&&<p className="error" role="alert">{error}</p>}
 </section>
}
