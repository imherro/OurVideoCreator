import type { FilmBibleDocument, VoiceProfile } from "./types";
import {lockedVoiceVersions,voiceSnapshot} from './voiceResolution.ts';

export function voiceProfilesOf(document: FilmBibleDocument) {
  return document.filmBible?.voices?.profiles || {};
}

export function defaultVoiceProfile(cardId: string, model_id = "", defaults:Record<string,any> = {}): VoiceProfile {
  return {
    cardId,
    model_id,
    voiceType: defaults.voice_type || "",
    version: 1,
    status: "draft",
    previewText: "你好，我是这个故事中的角色。",
    parameters: { speechRate: defaults.speech_rate ?? 0, emotion: defaults.emotion || "" },
  };
}

export function voiceParameters(models:Record<string,any>[],profile:VoiceProfile,performance?:{emotion:string;contextTexts:string[]}){
 const model=models.find(item=>item.id===profile.model_id&&item.kind==='audio');
 if(!model)throw new Error('所选平台语音模型已停用或未发布，请重新选择');
 const rules=model.rules||{},parameters={...model.defaults};
 if(!rules.voice_type?.enum?.includes(profile.voiceType))throw new Error('当前音色不在平台允许列表中');
 parameters.voice_type=profile.voiceType;
 if(rules.speech_rate)parameters.speech_rate=profile.parameters.speechRate;
 if(rules.emotion)parameters.emotion=performance?.emotion??profile.parameters.emotion;
 if(rules.context_texts&&performance)parameters.context_texts=performance.contextTexts;
 return parameters;
}

export function saveVoiceProfile<T extends FilmBibleDocument>(document: T, cardId: string, input: VoiceProfile): T {
  const current = voiceProfilesOf(document)[cardId];
  const voiceType = input.voiceType.trim();
  const previewText = input.previewText.trim();
  if (!input.model_id) throw new Error("请选择豆包语音服务");
  if (!voiceType) throw new Error("音色 ID 不能为空");
  if (!previewText) throw new Error("试听台词不能为空");
  const identityChanged = !!current && voiceIdentity(current) !== voiceIdentity(input);
  const next: VoiceProfile = {
    ...input,
    lockedVersions: lockedVoiceVersions(current) as Record<string,VoiceProfile>,
    defaultVersion: current?.defaultVersion ?? (current?.status==='locked'?current.version:undefined),
    cardId,
    model_id: input.model_id,
    voiceType,
    previewText,
    version: identityChanged ? current.version + 1 : Math.max(1, input.version || 1),
    status: identityChanged ? "draft" : input.status,
    previewAssetId: identityChanged ? undefined : input.previewAssetId,
    referenceAssetId: identityChanged ? undefined : input.referenceAssetId,
    referenceVersion: identityChanged ? undefined : input.referenceVersion,
    generationJobId: identityChanged ? undefined : input.generationJobId,
    parameters: {
      speechRate: Math.max(-50, Math.min(100, Number(input.parameters?.speechRate) || 0)),
      emotion: String(input.parameters?.emotion || "").trim(),
    },
  };
  return {
    ...document,
    filmBible: {
      ...(document.filmBible || {}),
      voices: { profiles: { ...voiceProfilesOf(document), [cardId]: next } },
    },
  } as T;
}

export function acceptVoiceResult<T extends FilmBibleDocument>(document: T, job: Record<string, any>): T {
  const descriptor = job.input?.voice_profile;
  const asset = job.result?.assets?.find((item: Record<string, any>) => item.kind === "audio");
  if (!descriptor?.cardId || !asset?.id) return document;
  const current = voiceProfilesOf(document)[descriptor.cardId];
  if (!current || current.status === 'locked' || current.version !== descriptor.version
      || (descriptor.identity && descriptor.identity !== voiceIdentity(current))
      || (current.generationJobId && current.generationJobId !== job.id)) return document;
  return {
    ...document,
    filmBible: {
      ...(document.filmBible || {}),
      voices: {
        profiles: {
          ...voiceProfilesOf(document),
          [descriptor.cardId]: { ...current, previewAssetId: asset.id, generationJobId: job.id },
        },
      },
    },
  } as T;
}

export function setVoiceLocked<T extends FilmBibleDocument>(document: T, cardId: string, locked: boolean): T {
  const current = voiceProfilesOf(document)[cardId];
  if (!current) throw new Error("请先保存并生成角色试听音频");
  if (locked && !current.previewAssetId) throw new Error("请先生成并试听角色音色");
  const next = locked
    ? { ...current, status: "locked" as const,referenceAssetId:current.previewAssetId,referenceVersion:current.version }
    : current.status === "locked"
      ? { ...current, version: current.version + 1, status: "draft" as const, previewAssetId: undefined, generationJobId: undefined,referenceAssetId:undefined,referenceVersion:undefined }
      : { ...current, status: "draft" as const };
  next.lockedVersions=lockedVoiceVersions(current) as Record<string,VoiceProfile>;
  next.defaultVersion=current.defaultVersion??(locked||current.status==='locked'?current.version:undefined);
  if(locked)next.lockedVersions[String(next.version)]=voiceSnapshot(next) as VoiceProfile;
  return {
    ...document,
    filmBible: {
      ...(document.filmBible || {}),
      voices: { profiles: { ...voiceProfilesOf(document), [cardId]: next } },
    },
  } as T;
}

/** Preview text and delivery settings are part of the audition, not just its preset ID. */
export function voiceIdentity(profile: VoiceProfile): string {
  return JSON.stringify([profile.model_id,String(profile.voiceType||'').trim(),String(profile.previewText||'').trim(),
    Math.max(-50,Math.min(100,Number(profile.parameters?.speechRate)||0)),String(profile.parameters?.emotion||'').trim()]);
}

export function canLockVoice(stored:VoiceProfile|undefined,draft:VoiceProfile):boolean {
  return Boolean(stored?.previewAssetId && voiceIdentity(stored)===voiceIdentity(draft)
    &&(stored.name||'')===(draft.name||''));
}

export function chooseVoiceVersion<T extends FilmBibleDocument>(document:T,cardId:string,version?:number):T{
 const card=document.filmBible?.visual?.cards[cardId];if(!card)throw new Error('角色不存在');
 const state=card.kind==='character_state',base=state?card.parentCardId!:cardId;
 const profile=voiceProfilesOf(document)[base];
 if(version!==undefined&&!lockedVoiceVersions(profile)[String(version)])throw new Error('请选择已锁定的声音版本');
 if(state)return {...document,filmBible:{...document.filmBible,visual:{...document.filmBible!.visual!,
  cards:{...document.filmBible!.visual!.cards,[cardId]:{...card,voiceVersion:version}}}}} as T;
 if(version===undefined)throw new Error('基础角色必须明确选择默认版本');
 return {...document,filmBible:{...document.filmBible,voices:{profiles:{...voiceProfilesOf(document),
  [cardId]:{...profile,defaultVersion:version,lockedVersions:lockedVoiceVersions(profile) as Record<string,VoiceProfile>}}}}} as T;
}
