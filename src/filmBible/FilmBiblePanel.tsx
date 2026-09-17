import React, { useEffect, useMemo, useState } from "react";
import {
  ArrowUpRight,
  ImagePlus,
  Link2,
  LoaderCircle,
  LockKeyhole,
  Sparkles,
  Trash2,
  Unlink,
  Volume2,
} from "lucide-react";
import { ModelSelector } from "../ModelSelector.tsx";
import type { GenerationPolicy } from "../generationPolicy.ts";
import type {
  VisualAttribute,
  VisualBible,
  VisualGenerationOverride,
  VisualVersionStatus,
  VoiceProfile,
} from "./types.ts";
import { defaultVoiceProfile, canLockVoice } from "./voices.ts";
import {lockedVoiceVersions,resolvedVoice} from './voiceResolution.ts';
import {UploadedVoiceFields} from './UploadedVoiceFields';
import { catalogVoice, CUSTOM_VOICE_ID, DOUBAO_TTS2_VOICES } from "./voiceCatalog.ts";
import { projectCharacterDialogueRows } from "./dialogueAssets.ts";
import { visualKindLabels, visualStatusLabels } from "./types.ts";
import {
  isVersionBound,
  isVisualBindingActionDisabled,
} from "./commands.ts";
import {
  primaryReference,
  resolveVisualGenerationTarget,
} from "./references.ts";
import { discoverImpactedShots } from "./versioning.ts";

type VersionDraft = {
  description: string;
  attributes: VisualAttribute[];
  invariants: string[];
};

export function FilmBiblePanel({
  visual,
  shots,
  focusVersionId,
  onFocusVersion,
  onRenameCard,
  onDeleteCard,
  onSaveVersion,
  onStatus,
  onSetImageOverride,
  onUploadReference,
  onGenerateReference,
  onLock,
  onFork,
  onUpgrade,
  onBind,
  onUnbind,
  onLocate,
  onPreviewAsset,
  assets,
  jobs,
  generationPolicy,
  providers,
  localModels,
  request,
  voiceProfiles,
  onSaveVoice,
  onAdmitVoice,
  onChooseVoiceVersion,
  onGenerateVoice,
  onLockVoice,
  onGenerateCharacterDialogue,
  onRegenerateDialogue,
}: {
  visual: VisualBible;
  shots: Array<Record<string, any>>;
  focusVersionId?: string;
  onFocusVersion: (versionId: string) => void;
  onRenameCard: (cardId: string, name: string) => void;
  onDeleteCard: (cardId: string) => void;
  onSaveVersion: (versionId: string, draft: VersionDraft) => void;
  onStatus: (versionId: string, status: VisualVersionStatus) => void;
  onSetImageOverride: (
    cardId: string,
    override: VisualGenerationOverride,
  ) => void;
  onUploadReference: (versionId: string, file: File) => Promise<void>;
  onGenerateReference: (versionId: string) => Promise<void>;
  onLock: (versionId: string) => void;
  onFork: (versionId: string, draft: VersionDraft) => void;
  onUpgrade: (
    cardId: string,
    targetVersionId: string,
    scope: { shotUids: string[] } | { scene: string } | { sequence: string },
  ) => void;
  onBind: (shotUid: string, versionId: string) => void;
  onUnbind: (shotUid: string, versionId: string) => void;
  onLocate: (versionId: string) => void;
  onPreviewAsset: (asset: Record<string, any>) => void;
  assets: Array<Record<string, any>>;
  jobs: Array<Record<string, any>>;
  generationPolicy: GenerationPolicy | undefined;
  providers: Array<Record<string, any>>;
  localModels: Array<Record<string, any>>;
  request: (path: string) => Promise<any>;
  voiceProfiles: Record<string, VoiceProfile>;
  onSaveVoice: (cardId: string, profile: VoiceProfile) => void;
  onAdmitVoice?: (value:File|string)=>Promise<Record<string,any>>;
  onChooseVoiceVersion: (cardId:string,version?:number)=>void;
  onGenerateVoice: (cardId: string, profile: VoiceProfile) => Promise<void>;
  onLockVoice: (cardId: string, locked: boolean) => void;
  onGenerateCharacterDialogue: (cardId: string) => Promise<number>;
  onRegenerateDialogue: (cardId: string, dialogueId: string) => Promise<void>;
}) {
  const versions = useMemo(
    () =>
      Object.values(visual.versions).filter(
        (version) => !visual.cards[version.cardId]?.deletedAt,
      ).sort((left, right) => {
        const leftCard = visual.cards[left.cardId];
        const rightCard = visual.cards[right.cardId];
        return `${leftCard?.kind}:${leftCard?.name}:${left.version}`.localeCompare(
          `${rightCard?.kind}:${rightCard?.name}:${right.version}`,
        );
      }),
    [visual],
  );
  const [selectedId, setSelectedId] = useState(
    focusVersionId || versions[0]?.id || "",
  );
  const [shotUid, setShotUid] = useState(
    String(shots[0]?.uid || shots[0]?.id || ""),
  );
  const selected = versions.find((version) => version.id === selectedId) || versions[0];
  const card = selected ? visual.cards[selected.cardId] : undefined;
  const shot = shots.find(
    (item) => String(item.uid || item.id || "") === shotUid,
  );
  const [name, setName] = useState(card?.name || "");
  const [draft, setDraft] = useState<VersionDraft>({
    description: selected?.spec.description || "",
    attributes: selected?.spec.attributes || [],
    invariants: selected?.invariants || [],
  });
  const [referenceBusy, setReferenceBusy] = useState(false);
  const [referenceError, setReferenceError] = useState("");
  const speechProviders = providers.filter((item) => item.type === "volcengine_speech" && item.kind === "audio");
  const defaultSpeech = speechProviders.find(item=>item.is_default);
  const storedVoice = card ? voiceProfiles[card.id] : undefined;
  const voiceDocument={filmBible:{visual,voices:{profiles:voiceProfiles}}};
  const voiceLibrary=lockedVoiceVersions(card?.kind==='character_state'?voiceProfiles[card.parentCardId!]:storedVoice);
  let activeVoice:Record<string,any>|undefined,voiceProblem='';
  try{activeVoice=card?resolvedVoice(voiceDocument,{}, {characterCardId:card.id}).profile:undefined}catch(error:any){voiceProblem=error.message}
  const [voiceDraft, setVoiceDraft] = useState<VoiceProfile>(() =>
    defaultVoiceProfile("", defaultSpeech?.id || "",defaultSpeech?.defaults),
  );
  const [voiceBusy, setVoiceBusy] = useState(false);
  const [voiceError, setVoiceError] = useState("");
  const dialogueRows = useMemo(
    () => projectCharacterDialogueRows({
      shots,
      document:voiceDocument,
      assets,
      jobs,
      cardId: card?.id || "",
      voiceVersion: activeVoice?.version,
    }),
    [shots, assets, jobs, card?.id, activeVoice?.version,visual,voiceProfiles],
  );
  useEffect(() => {
    if (focusVersionId && visual.versions[focusVersionId])
      setSelectedId(focusVersionId);
  }, [focusVersionId, visual.versions]);
  useEffect(() => {
    if (!selected || !card) return;
    setName(card.name);
    setDraft({
      description: selected.spec.description,
      attributes: selected.spec.attributes.map((item) => ({ ...item })),
      invariants: [...selected.invariants],
    });
  }, [selected?.id, selected?.spec, selected?.invariants, card?.name]);
  useEffect(() => {
    if (!shotUid && shots[0]) setShotUid(String(shots[0].uid || shots[0].id));
  }, [shotUid, shots]);
  useEffect(() => {
    setReferenceError("");
  }, [selected?.id]);
  useEffect(() => {
    if (!card) return;
    setVoiceDraft(storedVoice || defaultVoiceProfile(card.id, defaultSpeech?.id || "",defaultSpeech?.defaults));
    setVoiceError("");
  }, [card?.id, storedVoice, speechProviders.find(item=>item.is_default)?.id]);
  if (!versions.length)
    return (
      <div className="empty-state film-bible-empty">
        <LockKeyhole />
        <h3>还没有视觉圣经</h3>
        <p>从分镜规划节点生成并导入分镜后，角色、场景和道具会显示在这里。</p>
      </div>
    );
  if (!selected || !card) return null;
  const editable = ["draft", "pending_reference"].includes(selected.status);
  const bound = isVersionBound(shot, selected.id);
  const bindingActionDisabled = isVisualBindingActionDisabled(
    selected.status,
    card.status,
    bound,
  );
  const reference = primaryReference(selected);
  const currentVersion = visual.versions[card.currentVersionId];
  const impacted = discoverImpactedShots(
    { filmBible: { visual }, shots, nodes: [], edges: [] },
    card.id,
  );
  const referenceAsset = assets.find((item) => item.id === reference?.assetId);
  const generationRecord = selected.provenance?.referenceGeneration as
    | Record<string, any>
    | undefined;
  const referenceJob = jobs.find(
    (item) => item.id === generationRecord?.jobId,
  );
  const generationRunning = ["queued", "running"].includes(
    referenceJob?.status || "",
  );
  const parentVersion = selected.parentVersionId ? visual.versions[selected.parentVersionId] : undefined;
  const stateReferenceBlocked = ["character_state", "scene_state"].includes(card.kind) && (
    parentVersion?.status !== "locked" || !primaryReference(parentVersion)
  );
  let resolvedTarget: ReturnType<typeof resolveVisualGenerationTarget> | undefined;
  let targetError = "";
  try {
    resolvedTarget = resolveVisualGenerationTarget(
      card,
      generationPolicy,
      providers,
      localModels,
    );
  } catch (reason: any) {
    targetError = reason?.message || String(reason);
  }
  const targetProvider = providers.find(
    (item) => item.id === resolvedTarget?.model_id,
  );
  const override = card.generation?.image;
  const perform = async (action: () => Promise<void>) => {
    setReferenceBusy(true);
    setReferenceError("");
    try {
      await action();
    } catch (reason: any) {
      setReferenceError(reason?.message || String(reason));
    } finally {
      setReferenceBusy(false);
    }
  };
  const selectVersion = (versionId: string) => {
    setSelectedId(versionId);
    onFocusVersion(versionId);
  };
  return (
    <div className="film-bible-panel">
      <div className="film-bible-list" role="list" aria-label="视觉版本">
        {versions.map((version) => {
          const item = visual.cards[version.cardId];
          return (
            <button
              key={version.id}
              className={version.id === selected.id ? "active" : ""}
              onClick={() => selectVersion(version.id)}
            >
              <span>{visualKindLabels[item.kind]}</span>
              <b>{item.name}</b>
              <small>V{version.version} · {visualStatusLabels[version.status]}</small>
            </button>
          );
        })}
      </div>
      <div className="film-bible-editor">
        <div className="film-bible-toolbar">
          <span className={`visual-status ${selected.status}`}>
            {visualStatusLabels[selected.status]}
          </span>
          <button className="quiet" onClick={() => onLocate(selected.id)}>
            画布定位 <ArrowUpRight size={13} />
          </button>
          <button className="quiet danger" onClick={() => onDeleteCard(card.id)}>
            <Trash2 size={13} /> 移至回收站
          </button>
        </div>
        <label>
          资产卡名称
          <input
            value={name}
            disabled={!editable}
            onChange={(event) => setName(event.target.value)}
            onBlur={() => name.trim() && name.trim() !== card.name && onRenameCard(card.id, name)}
          />
        </label>
        <label>
          可见外观描述
          <textarea
            value={draft.description}
            disabled={!editable}
            onChange={(event) => setDraft({ ...draft, description: event.target.value })}
          />
        </label>
        <div className="film-bible-section-title">
          <b>结构化属性</b><small>只保存长期外观特征</small>
        </div>
        {draft.attributes.map((attribute, index) => (
          <div className="film-bible-attribute" key={index}>
            <input
              aria-label={`属性 ${index + 1} 名称`}
              value={attribute.name}
              disabled={!editable}
              onChange={(event) => setDraft({
                ...draft,
                attributes: draft.attributes.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, name: event.target.value } : item,
                ),
              })}
            />
            <input
              aria-label={`属性 ${index + 1} 内容`}
              value={attribute.value}
              disabled={!editable}
              onChange={(event) => setDraft({
                ...draft,
                attributes: draft.attributes.map((item, itemIndex) =>
                  itemIndex === index ? { ...item, value: event.target.value } : item,
                ),
              })}
            />
            {editable && (
              <button
                className="icon-button"
                aria-label={`删除属性 ${index + 1}`}
                onClick={() => setDraft({
                  ...draft,
                  attributes: draft.attributes.filter((_, itemIndex) => itemIndex !== index),
                })}
              >×</button>
            )}
          </div>
        ))}
        {editable && (
          <button
            className="quiet"
            onClick={() => setDraft({
              ...draft,
              attributes: [...draft.attributes, { name: "", value: "" }],
            })}
          >+ 添加属性</button>
        )}
        <label>
          不可改变项（每行一项）
          <textarea
            value={draft.invariants.join("\n")}
            disabled={!editable}
            onChange={(event) => setDraft({
              ...draft,
              invariants: event.target.value.split("\n"),
            })}
          />
        </label>
        {editable && (
          <div className="film-bible-actions">
            <button className="primary" onClick={() => onSaveVersion(selected.id, draft)}>
              保存版本文字
            </button>
            {selected.status === "pending_reference" && (
              <button onClick={() => onStatus(selected.id, "draft")}>
                恢复草稿
              </button>
            )}
            <button className="danger-button" onClick={() => onStatus(selected.id, "deprecated")}>弃用版本</button>
          </div>
        )}
        {!editable && (
          <>
            <p className="muted">
              {selected.status === "locked"
                ? "已锁定版本只读；修改会派生新版本，旧版本和旧分镜绑定继续保留。"
                : "已弃用版本保留历史，但不能编辑或建立新绑定。"}
            </p>
            {selected.status === "locked" && (
              <>
                <button className="secondary full" onClick={() => onFork(selected.id, draft)}>
                  创建新版本
                </button>
                <button className="danger-button full" onClick={() => onStatus(selected.id, "deprecated")}>
                  弃用此版本（保留分镜引用）
                </button>
              </>
            )}
          </>
        )}
        {(card.kind==='character'||card.kind==='character_state')&&<>
          <hr/><label>{card.kind==='character_state'?'状态音色':'默认音色'}<select
            disabled={card.kind==='character'&&!!storedVoice&&JSON.stringify(voiceDraft)!==JSON.stringify(storedVoice)}
            value={card.kind==='character_state'?card.voiceVersion??'':storedVoice?.defaultVersion??(storedVoice?.status==='locked'?storedVoice.version:'')}
            onChange={event=>onChooseVoiceVersion(card.id,event.target.value?Number(event.target.value):undefined)}>
            <option value="" disabled={card.kind!=='character_state'}>{card.kind==='character_state'?'继承基础角色默认音色':'请先保存并锁定声音'}</option>
            {Object.values(voiceLibrary).map(voice=><option key={voice.version} value={voice.version}>{voice.name||catalogVoice(voice.voiceType)?.name||'角色声音'} · V{voice.version}</option>)}
          </select></label>
          {card.kind==='character'&&storedVoice&&JSON.stringify(voiceDraft)!==JSON.stringify(storedVoice)&&<small>请先保存声音草稿，再切换默认版本。</small>}
          <p className="muted">状态默认继承，无需为换装单独生成。明确选择的状态版本不会随基础角色默认音色改变。</p>
          {voiceProblem&&<p className="error">{voiceProblem}</p>}
          {activeVoice?.referenceAssetId&&<button onClick={()=>{const asset=assets.find(item=>item.id===activeVoice.referenceAssetId);if(asset)onPreviewAsset(asset)}}>试听当前生效音色</button>}
          {card.kind==='character_state'&&<>
            {activeVoice?.source?.type==='uploaded'?<p className="muted">当前为上传声音，请使用音色样本参考；不能逐句合成对白。</p>:card.voiceVersion!==undefined&&<button disabled={voiceBusy} onClick={()=>{setVoiceBusy(true);setVoiceError('');void onGenerateCharacterDialogue(card.id).catch(error=>setVoiceError(error.message)).finally(()=>setVoiceBusy(false))}}>生成此状态的本集对白</button>}
            {dialogueRows.map(row=><p key={row.id}>第{row.shotOrder}镜 · {row.text} · {row.status==='ready'?'已采纳':'待生成或采纳'}</p>)}
            {voiceError&&<p className="error">{voiceError}</p>}
          </>}
        </>}
        {card.kind === "character" && <>
          <hr />
          <div className="film-bible-section-title"><b>角色固定音色</b><small>跨镜头统一对白声纹</small></div>
          <>
            <label>声音来源<select value={voiceDraft.source?.type||'doubao_tts'} disabled={voiceDraft.status==='locked'} onChange={event=>setVoiceDraft({...voiceDraft,
              source:event.target.value==='uploaded'?{type:'uploaded',originalAssetId:'',authorizedAt:''}:{type:'doubao_tts'},
              previewAssetId:undefined,referenceAssetId:undefined,referenceVersion:undefined,generationJobId:undefined})}>
              <option value="doubao_tts">豆包生成试听</option><option value="uploaded">上传声音</option>
            </select></label>
            <label>声音版本名称<input maxLength={100} value={voiceDraft.name||''} disabled={voiceDraft.status==='locked'} placeholder="例如：常态男声、变身女声" onChange={event=>setVoiceDraft({...voiceDraft,name:event.target.value})}/></label>
            <label>声音说明<textarea maxLength={500} value={voiceDraft.description||''} disabled={voiceDraft.status==='locked'} placeholder="可选：声音特征、适用状态" onChange={event=>setVoiceDraft({...voiceDraft,description:event.target.value})}/></label>
            {voiceDraft.source?.type==='uploaded'?<UploadedVoiceFields key={card.id} assets={assets} disabled={voiceDraft.status==='locked'}
              onAdmit={onAdmitVoice||(()=>Promise.reject(new Error('当前页面未接通声音上传')))}
              onSelect={asset=>setVoiceDraft(current=>({...current,source:{type:'uploaded',originalAssetId:asset.id,authorizedAt:asset.metadata.voice_reference.authorized_at},
                previewAssetId:asset.id,generationJobId:undefined,referenceAssetId:undefined,referenceVersion:undefined}))}/>:<>
            {!speechProviders.length&&<p className="warning-text">暂无已发布的语音模型；可使用上传声音，或联系平台管理员配置模型和允许音色。</p>}
            <label>平台语音模型<select value={voiceDraft.model_id} disabled={voiceDraft.status === "locked"}
              onChange={event=>{const model=speechProviders.find(item=>item.id===event.target.value);
                setVoiceDraft({...voiceDraft,model_id:event.target.value,voiceType:model?.defaults?.voice_type||"",parameters:{speechRate:model?.defaults?.speech_rate??0,emotion:model?.defaults?.emotion||""}});}}>
              <option value="">请选择平台语音模型</option>{speechProviders.map(item=><option key={item.id} value={item.id}>{item.name}</option>)}
            </select></label>
            <label>平台允许音色<select value={voiceDraft.voiceType} disabled={voiceDraft.status === "locked"}
              onChange={event=>setVoiceDraft({...voiceDraft,voiceType:event.target.value})}>
              <option value="">请选择允许的音色</option>
              {(speechProviders.find(item=>item.id===voiceDraft.model_id)?.rules?.voice_type?.enum||[]).map((voice:string)=>
                <option key={voice} value={voice}>{catalogVoice(voice)?.name||voice}</option>)}
            </select></label>
            <label>试听台词<textarea value={voiceDraft.previewText} disabled={voiceDraft.status === "locked"} onChange={(event)=>setVoiceDraft({...voiceDraft,previewText:event.target.value})}/></label>
            <div className="two-fields">
              {speechProviders.find(item=>item.id===voiceDraft.model_id)?.rules?.speech_rate&&<label>语速<select value={voiceDraft.parameters.speechRate} disabled={voiceDraft.status === "locked"} onChange={(event)=>setVoiceDraft({...voiceDraft,parameters:{...voiceDraft.parameters,speechRate:Number(event.target.value)}})}><option value={-25}>较慢</option><option value={0}>正常</option><option value={25}>较快</option></select></label>}
              {speechProviders.find(item=>item.id===voiceDraft.model_id)?.rules?.emotion&&<label>情绪<input value={voiceDraft.parameters.emotion} disabled={voiceDraft.status === "locked"} placeholder="留空自动演绎" onChange={(event)=>setVoiceDraft({...voiceDraft,parameters:{...voiceDraft.parameters,emotion:event.target.value}})}/></label>}
            </div>
            </>}
            <div className="film-bible-actions">
              {voiceDraft.status !== "locked" && <button onClick={()=>onSaveVoice(card.id,voiceDraft)}>保存声音设定</button>}
              {voiceDraft.status !== "locked" && voiceDraft.source?.type!=='uploaded' && <button className="primary" disabled={voiceBusy||!speechProviders.length} onClick={()=>{setVoiceBusy(true);setVoiceError("");void onGenerateVoice(card.id,voiceDraft).catch((reason)=>setVoiceError(reason?.message||String(reason))).finally(()=>setVoiceBusy(false));}}>{voiceBusy?<LoaderCircle className="spin" size={14}/>:<Volume2 size={14}/>}生成试听</button>}
              {voiceDraft.source?.type==='uploaded'&&voiceDraft.previewAssetId&&voiceDraft.previewAssetId!==storedVoice?.previewAssetId&&<button onClick={()=>{const asset=assets.find(item=>item.id===voiceDraft.previewAssetId);if(asset)onPreviewAsset(asset)}}>试听所选样本（未锁定）</button>}
              {storedVoice?.previewAssetId && <button className="secondary" onClick={()=>{const asset=assets.find((item)=>item.id===storedVoice.previewAssetId);if(asset)onPreviewAsset(asset);}}>试听声音</button>}
                {storedVoice?.status === "locked" ? <button onClick={()=>onLockVoice(card.id,false)}>创建新声音版本</button> : storedVoice?.previewAssetId ? <button disabled={!canLockVoice(storedVoice,voiceDraft)} title={!canLockVoice(storedVoice,voiceDraft)?'请先保存声音设置；试听参数改变时需重新生成试听':''} onClick={()=>onLockVoice(card.id,true)}>锁定主音色 V{storedVoice.version}</button> : null}
                {storedVoice?.status==='locked'&&storedVoice.previewAssetId&&!storedVoice.referenceAssetId&&<button onClick={()=>onLockVoice(card.id,true)}>将已采纳试听确认为声音参考</button>}
                {storedVoice?.referenceAssetId&&<small>已确认声音参考 V{storedVoice.referenceVersion}；仅音色参考，不复述样本。</small>}
              {activeVoice?.status === "locked" && activeVoice.source?.type!=='uploaded' && <button className="primary" disabled={voiceBusy} onClick={()=>{setVoiceBusy(true);setVoiceError("");void onGenerateCharacterDialogue(card.id).catch((reason)=>setVoiceError(reason?.message||String(reason))).finally(()=>setVoiceBusy(false));}}><Volume2 size={14}/>使用默认 V{activeVoice.version} 生成本集对白</button>}
            </div>
            {voiceDraft.source?.type==='uploaded'&&voiceDraft.source.originalAssetId&&<p>已选样本：{assets.find(item=>item.id===(voiceDraft.source?.type==='uploaded'?voiceDraft.source.originalAssetId:''))?.name||'请查看素材库'}</p>}
            {activeVoice?.source?.type==='uploaded'&&<p className="muted">{activeVoice.status==='locked'?'当前默认为上传声音':'上传声音草稿需先试听并锁定'}，仅用于视频音色样本参考；不能自动逐句合成，不会回退到其他音色。</p>}
            <p className="muted">{storedVoice ? `声音 V${storedVoice.version} · ${storedVoice.status === "locked" ? "已锁定" : "草稿"}` : "保存并试听后可锁定为角色主音色。"}</p>
            <div className="voice-dialogue-heading">
              <b>本集对白</b>
              <small>{dialogueRows.length ? `${dialogueRows.filter((item)=>item.status==="ready").length}/${dialogueRows.length} 已生成` : "分镜中暂无该角色对白"}</small>
            </div>
            {dialogueRows.length > 0 && <div className="voice-dialogue-list">{dialogueRows.map((row)=>{
              const statusLabel = {missing:"未生成",queued:"排队中",running:"生成中",failed:"生成失败",interrupted:"待恢复",syncing:"候选待采纳（任务中心）",ready:"已采纳"}[row.status];
              return <div className="voice-dialogue-row" key={row.id}>
                <div className="voice-dialogue-copy">
                  <div><b>第 {row.shotOrder} 镜</b>{row.emotion && <small>{row.emotion}</small>}</div>
                  <p title={row.text}>{row.text}</p>
                  {row.status === "failed" && row.job?.error && <small className="error" title={row.job.error}>{row.job.error}</small>}
                </div>
                <div className="voice-dialogue-state">
                  <span className={`voice-state ${row.status}`}>{statusLabel}</span>
                  {row.asset && <button className="secondary" onClick={()=>onPreviewAsset(row.asset!)}><Volume2 size={13}/>试听</button>}
                  {activeVoice?.source?.type!=='uploaded'&&!(["queued","running","syncing"] as string[]).includes(row.status) && <button disabled={voiceBusy} onClick={()=>{setVoiceBusy(true);setVoiceError("");void onRegenerateDialogue(card.id,row.id).catch((reason)=>setVoiceError(reason?.message||String(reason))).finally(()=>setVoiceBusy(false));}}>{row.status === "ready" ? "重新生成" : "生成"}</button>}
                </div>
              </div>;
            })}</div>}
            {voiceError && <p className="error">{voiceError}</p>}
          </>
        </>}
        <hr />
        <h3>主参考图</h3>
        <div className="reference-policy">
          <label>
            图片模型策略
            <select
              value={override?.mode === "override" ? "override" : "inherit"}
              disabled={!editable}
              onChange={(event) => {
                if (event.target.value === "inherit") {
                  onSetImageOverride(card.id, { mode: "inherit" });
                  return;
                }
                const fallback = resolvedTarget || {model_id:""};
                onSetImageOverride(card.id, {
                  mode: "override",
                  model_id: fallback.model_id,
                });
              }}
            >
              <option value="inherit">继承项目默认</option>
              <option value="override">此资产自定义</option>
            </select>
          </label>
          {override?.mode === "override" && editable && (
            <ModelSelector
              data={{
                kind: "image",
                model_id: override.model_id,
              }}
              providers={providers}
              localModels={localModels}
              request={request}
              onChange={(patch) =>
                onSetImageOverride(card.id, {
                  mode: "override",
                  model_id: String(patch.model_id ?? override.model_id),
                })
              }
            />
          )}
          {override?.mode === "override" && !editable && (
            <p className="muted">
              已锁定自定义：{targetProvider?.name || override.model_id} · {override.model_id || "服务默认模型"}
            </p>
          )}
          {override?.mode !== "override" && resolvedTarget && (
            <p className="muted">
              当前继承：{targetProvider?.name || resolvedTarget.model_id} · {resolvedTarget.model_id || "服务默认模型"}
            </p>
          )}
          {targetError && <p className="error">{targetError}</p>}
        </div>
        {reference ? (
          <div className="primary-reference">
            {referenceAsset ? (
              <button
                type="button"
                className="primary-reference-preview"
                onClick={() => onPreviewAsset(referenceAsset)}
                aria-label={`放大预览${card.name}主参考图`}
                title="点击放大预览"
              >
                <img src={referenceAsset.url} alt={`${card.name} 主参考图`} />
                <span>点击放大</span>
              </button>
            ) : (
              <div className="missing-reference">参考素材暂未加载：{reference.assetId}</div>
            )}
            <div>
              <b>{reference.source === "generated" ? "模型生成" : "本地上传"}</b>
              <small>{referenceAsset?.name || reference.assetId}</small>
              {reference.provenance.model_id && (
                <small>
                  {reference.provenance.model_id} · {reference.provenance.model_id}
                </small>
              )}
            </div>
          </div>
        ) : (
          <p className="muted">尚未设置主参考图。提取剧本和分镜不会自动调用图片模型。</p>
        )}
        {editable && (
          <div className="reference-actions">
            <label className="upload-reference-button">
              <ImagePlus size={15} /> 上传主参考图
              <input
                type="file"
                accept="image/png,image/jpeg"
                disabled={referenceBusy || generationRunning}
                onChange={(event) => {
                  const file = event.target.files?.[0];
                  event.target.value = "";
                  if (file)
                    void perform(() => onUploadReference(selected.id, file));
                }}
              />
            </label>
            <button
              className="primary"
              disabled={
                referenceBusy ||
                generationRunning ||
                stateReferenceBlocked ||
                Boolean(targetError) ||
                !resolvedTarget?.model_id
              }
              onClick={() =>
                void perform(() =>
                  onGenerateReference(selected.id),
                )
              }
            >
              {referenceBusy || generationRunning ? (
                <LoaderCircle className="spin" size={15} />
              ) : (
                <Sparkles size={15} />
              )}
              {reference ? "重新生成参考图" : "生成主参考图"}
            </button>
            {stateReferenceBlocked && <small>请先生成并锁定基础角色或场景的主参考图。</small>}
          </div>
        )}
        {referenceJob?.status === "failed" && (
          <p className="error">参考图生成失败：{referenceJob.error}</p>
        )}
        {referenceError && <p className="error">{referenceError}</p>}
        {selected.status === "pending_reference" && reference && (
          <button
            className="primary full lock-reference"
            onClick={() => onLock(selected.id)}
          >
            <LockKeyhole size={15} /> 确认此图并锁定版本
          </button>
        )}
        {selected.status === "locked" && (
          <p className="locked-reference-note">
            <LockKeyhole size={14} /> 此参考图已确认锁定，可安全用于后续分镜一致性约束。
          </p>
        )}
        <hr />
        <h3>分镜绑定</h3>
        {selected.id === card.currentVersionId && currentVersion?.status === "locked" && impacted.length > 0 && (
          <div className="version-impact">
            <b>{impacted.length} 个分镜仍使用旧版本</b>
            <small>升级只改变明确选择的分镜；旧画面会保留并标记为待更新。</small>
            {impacted.slice(0, 8).map((item) => (
              <div className="version-impact-row" key={`${item.shotUid}:${item.fromVersionId}`}>
                <span>{item.shotId} · {item.scene || "未命名场景"} · V{visual.versions[item.fromVersionId]?.version}</span>
                <button onClick={() => onUpgrade(card.id, selected.id, { shotUids: [item.shotUid] })}>
                  升级此镜头
                </button>
              </div>
            ))}
            {shot?.scene && impacted.some((item) => item.scene === String(shot.scene)) && (
              <button className="quiet full" onClick={() => onUpgrade(card.id, selected.id, { scene: String(shot.scene) })}>
                升级场景“{String(shot.scene)}”内受影响镜头
              </button>
            )}
            {(shot?.sequence || shot?.sequenceId) && (
              <button className="quiet full" onClick={() => onUpgrade(card.id, selected.id, { sequence: String(shot.sequence || shot.sequenceId) })}>
                升级当前段落内受影响镜头
              </button>
            )}
          </div>
        )}
        {!shots.length ? (
          <p className="muted">导入分镜后可以建立视觉绑定。</p>
        ) : (
          <>
            <label>
              目标分镜
              <select value={shotUid} onChange={(event) => setShotUid(event.target.value)}>
                {shots.map((item, index) => (
                  <option key={String(item.uid || item.id)} value={String(item.uid || item.id)}>
                    {String(index + 1).padStart(2, "0")} · {item.scene || item.id}
                  </option>
                ))}
              </select>
            </label>
            <button
              className={bound ? "secondary full" : "primary full"}
              disabled={bindingActionDisabled}
              onClick={() => bound ? onUnbind(shotUid, selected.id) : onBind(shotUid, selected.id)}
            >
              {bound ? <Unlink size={15} /> : <Link2 size={15} />}
              {bound ? "解除当前绑定" : "绑定到这个分镜"}
            </button>
            <small>绑定会自动投影为视觉资产到分镜图的受管连线。</small>
          </>
        )}
      </div>
    </div>
  );
}
