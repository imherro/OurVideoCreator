import {useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {promptParts,referenceMedia} from '../referencePresentation';
type Value=Record<string,any>;
export function ReferencePrompt({prompt,manifest,assets}:{prompt:string;manifest:Value[];assets:Value[]}){
 return <div className="reference-prompt">{prompt.split(/\r?\n/).map((line,index)=>{
  if(!line.trim())return <div className="reference-prompt-gap" key={index}/>;
  if(/^\[\/[^\]]+\]$/.test(line.trim()))return null;
  if(/^\[[^\]]+\]$/.test(line.trim()))return <h5 key={index}>{line.trim().slice(1,-1)}</h5>;
  return <p key={index}>{promptParts(line).map((text,i)=>{
   const media=referenceMedia(text,manifest,assets);
   return media?<InlineReference key={`${i}:${media.id}`} label={text} media={media}/>:text;
  })}</p>;
 })}</div>;
}
function InlineReference({label,media}:{label:string;media:Value}){
 const [open,setOpen]=useState(false),[failed,setFailed]=useState(false);const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null);
 const close=()=>{dialog.current?.close();setOpen(false);trigger.current?.focus()};
 useEffect(()=>{if(open)dialog.current?.showModal()},[open]);
 return <span className="reference-inline">
  <button ref={trigger} type="button" disabled={failed} aria-label={`预览${label}：${media.name}`} onClick={()=>setOpen(true)}>
   {media.kind==='image'&&!failed?<img src={media.url} alt="" loading="lazy" onError={()=>setFailed(true)}/>:<span aria-hidden="true">▶</span>}{label}
  </button>{failed&&<small>素材不可访问</small>}
  {open&&createPortal(<dialog ref={dialog} className="reference-media-dialog" aria-label={`参考预览：${media.name}`} onCancel={close}
    onClick={event=>{if(event.target===dialog.current)close()}}>
   <header><strong>{label} · {media.name}</strong><button type="button" onClick={close}>关闭参考预览</button></header>
   {failed?<p>素材已失效或不可访问，请刷新参考清单。</p>:media.kind==='image'?<img src={media.url} alt={media.name} onError={()=>setFailed(true)}/>
    :media.kind==='video'?<video src={media.url} controls preload="metadata" onError={()=>setFailed(true)}/>:<audio src={media.url} controls preload="metadata" onError={()=>setFailed(true)}/>}
  </dialog>,document.body)}
 </span>;
}
