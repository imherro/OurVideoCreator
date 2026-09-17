import {useEffect,useRef,useState} from 'react';
type Value=Record<string,any>;
export function UploadedVoiceFields({assets,disabled,onAdmit,onSelect}:{assets:Value[];disabled:boolean;
 onAdmit:(value:File|string)=>Promise<Value>;onSelect:(asset:Value)=>void}){
 const [authorized,setAuthorized]=useState(false),[selected,setSelected]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const mounted=useRef(true);useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 async function prepare(value:File|string){
  if(!authorized||!value||busy)return;setBusy(true);setError('');
  try{const asset=await onAdmit(value);if(mounted.current)onSelect(asset)}
  catch(reason:any){if(mounted.current)setError(reason.message||String(reason))}
  finally{if(mounted.current)setBusy(false)}
 }
 return <fieldset disabled={disabled||busy} style={{minWidth:0,border:'1px solid var(--border, #394247)',borderRadius:8,padding:12}}><legend>上传声音样本</legend>
  <p className="muted">MP3/WAV，最多30 MB、120秒；视频模型另有限制，不自动裁剪。上传声音无需语音模型，不会注册为TTS音色。</p>
  <label style={{display:'flex',flexDirection:'row',alignItems:'flex-start',gap:8}}><input style={{width:'auto',flex:'0 0 auto',marginTop:3}} type="checkbox" checked={authorized} onChange={event=>setAuthorized(event.target.checked)}/>我拥有该声音的使用权或已获授权（用户声明，非平台核验）</label>
  <label>上传文件<input type="file" accept=".mp3,.wav,audio/mpeg,audio/wav" disabled={!authorized} onChange={event=>{
   const file=event.target.files?.[0];event.target.value='';if(file)void prepare(file);
  }}/></label>
  <label>或选择本作品已有音频<select value={selected} onChange={event=>setSelected(event.target.value)}>
   <option value="">请选择音频</option>{assets.filter(asset=>asset.kind==='audio').map(asset=><option key={asset.id} value={asset.id}>{asset.name}</option>)}
  </select></label>
  <button disabled={!authorized||!selected} onClick={()=>void prepare(selected)}>校验并选择已有样本</button>
  {busy&&<p>正在校验声音，尚未保存或锁定角色音色…</p>}{error&&<p className="error">{error}</p>}
 </fieldset>;
}
