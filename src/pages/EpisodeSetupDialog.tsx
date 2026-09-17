import {useEffect,useRef,useState} from 'react';
import './episodeSetup.css';

export function EpisodeSetupDialog({name,next,defaultMode,onClose,onCreate}:{
  name:string;next:number;defaultMode:string;onClose:()=>void;
  onCreate:(title:string,mode:'direct'|'adaptation')=>Promise<void>;
}){
  const dialog=useRef<HTMLDialogElement>(null);
  const [title,setTitle]=useState(`第 ${String(next).padStart(2,'0')} 集`);
  const [mode,setMode]=useState<'direct'|'adaptation'>(defaultMode==='adaptation'?'adaptation':'direct');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const submitting=useRef(false);
  useEffect(()=>{const element=dialog.current!;element.showModal();return()=>element.close();},[]);
  return <dialog ref={dialog} className="episode-setup-dialog" aria-labelledby="episode-setup-title"
    onCancel={event=>{event.preventDefault();if(!submitting.current)onClose();}}>
    <form onSubmit={async event=>{event.preventDefault();if(submitting.current)return;
      if(!title.trim()){setError('请填写本集名称');return;}
      submitting.current=true;setBusy(true);setError('');
      try{await onCreate(title.trim(),mode);}catch(error){setError(error instanceof Error?error.message:String(error));}
      finally{submitting.current=false;setBusy(false);}}}>
      <h2 id="episode-setup-title">新增 EP{String(next).padStart(2,'0')}</h2><p>{name}</p>
      <fieldset disabled={busy}>
        <label>本集名称<input autoFocus value={title} maxLength={100} onChange={event=>setTitle(event.target.value)}/></label>
        <label>创作起点<select value={mode} onChange={event=>setMode(event.target.value as typeof mode)}>
          <option value="direct">直接写剧本</option><option value="adaptation">从原著改编</option>
        </select></label>
      </fieldset>
      <p>继承作品模型、Bible 和最近一集的制作规格。新集正文仍需审核批准；此操作不调用 AI。</p>
      {error&&<p role="alert">{error}</p>}
      <div className="settings-actions"><button type="button" disabled={busy} onClick={onClose}>取消</button>
        <button type="submit" className="primary" disabled={busy}>{busy?'创建中…':'创建并开始'}</button></div>
    </form>
  </dialog>;
}
