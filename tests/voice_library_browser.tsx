import {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {FilmBiblePanel} from '../src/filmBible/FilmBiblePanel';
import {chooseVoiceVersion,setVoiceLocked,saveVoiceProfile} from '../src/filmBible/voices';
import {resolvedVoice} from '../src/filmBible/voiceResolution';
import '../src/style.css';
const v1={cardId:'hero',version:1,name:'常态男声',status:'locked',model_id:'speech',voiceType:'voice',previewText:'旧试听',referenceAssetId:'one',referenceVersion:1,previewAssetId:'one',parameters:{speechRate:0,emotion:''}};
const v2={...v1,version:2,name:'变身女声',referenceAssetId:'two',referenceVersion:2,previewAssetId:'two'};
const version=(id:string,cardId:string,parentVersionId:string|null)=>({id,cardId,version:1,parentVersionId,status:'draft',spec:{description:'隔离测试描述',attributes:[]},invariants:[],references:[]});
const initial:any={shots:[],nodes:[],edges:[],filmBible:{visual:{cards:{
 hero:{id:'hero',kind:'character',name:'测试宗主',parentCardId:null,currentVersionId:'hero-v',status:'active'},
 state:{id:'state',kind:'character_state',name:'黑袍状态',parentCardId:'hero',currentVersionId:'state-v',status:'active'}},
 versions:{'hero-v':version('hero-v','hero',null),'state-v':version('state-v','state','hero-v')}},
 voices:{profiles:{hero:{...v2,defaultVersion:1,lockedVersions:{'1':v1,'2':v2}}}}}};
const noop=()=>{};
const uploadMode=new URLSearchParams(location.search).has('upload');
const uploadedAssets=[{id:'upload-one',kind:'audio',name:'隔离合成样本.wav',metadata:{voice_reference:{authorized_at:'fixture-receipt'}}},
 {id:'bad-sample',kind:'audio',name:'模拟校验失败.wav',metadata:{}}];
function App(){const [doc,setDoc]=useState(uploadMode?{...initial,filmBible:{...initial.filmBible,voices:{profiles:{}}}}:initial),[focus,setFocus]=useState(uploadMode?'hero-v':'state-v'),[changes,setChanges]=useState(0);
 const [preview,setPreview]=useState(''),[admissions,setAdmissions]=useState(0);
 const update=(fn:any)=>{setDoc(fn);setChanges(n=>n+1)};
 const common:any={visual:doc.filmBible.visual,shots:[],assets:uploadMode?uploadedAssets:[],jobs:[],voiceProfiles:doc.filmBible.voices.profiles,
 providers:uploadMode?[]:[{id:'speech',name:'隔离语音模型',kind:'audio',type:'volcengine_speech',rules:{voice_type:{enum:['voice']}},defaults:{voice_type:'voice'}}],
 localModels:[],request:async()=>{throw new Error('隔离页禁止API请求')},focusVersionId:focus,onFocusVersion:setFocus,
 onChooseVoiceVersion:(id:string,v?:number)=>update((current:any)=>chooseVoiceVersion(current,id,v)),
 onSaveVoice:(id:string,p:any)=>update((current:any)=>saveVoiceProfile(current,id,p)),
 onAdmitVoice:async(value:File|string)=>{if(value!=='upload-one')throw new Error('隔离模拟：文件不能完整解码');setAdmissions(n=>n+1);return uploadedAssets[0]},
 onLockVoice:(id:string,locked:boolean)=>update((current:any)=>setVoiceLocked(current,id,locked)),
 onGenerateVoice:async()=>{throw new Error('隔离页不生成')},onGenerateCharacterDialogue:async()=>{throw new Error('隔离页不生成')},onRegenerateDialogue:async()=>{throw new Error('隔离页不生成')},
 onRenameCard:noop,onDeleteCard:noop,onSaveVersion:noop,onStatus:noop,onRestoreVersion:async()=>{},onSetImageOverride:noop,onUploadReference:noop,onGenerateReference:noop,onLock:noop,onFork:noop,onUpgrade:noop,onBind:noop,onUnbind:noop,onLocate:noop,onPreviewAsset:(asset:any)=>setPreview(asset.id)};
 return <main style={{padding:20,maxWidth:1050,margin:'auto'}}><h1>音色库隔离测试 · 无API／业务库</h1>
 <p>修改次数：{changes} · 基础默认：V{resolvedVoice(doc,{}, {characterCardId:'hero'}).profile.version} · 黑袍生效：V{resolvedVoice(doc,{}, {characterCardId:'state'}).profile.version}</p>
 {uploadMode&&<p>无语音模型 · 校验次数：{admissions} · 试听目标：{preview||'未选择'}</p>}
 <button onClick={()=>setFocus('hero-v')}>查看基础角色</button><button onClick={()=>setFocus('state-v')}>查看黑袍状态</button>
 <FilmBiblePanel {...common}/></main>;
}
createRoot(document.getElementById('root')!).render(<App/>);
