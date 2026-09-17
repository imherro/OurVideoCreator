import type { GenerationPolicy } from "./generationPolicy.ts";
import {defaultProjectModelPool,type ProjectModelPool} from './modelAccess.ts';
import { invalidate } from "./graph.ts";
import { setProjectVisualStyle } from "./filmBible/versioning.ts";

type Value = Record<string, any>;

export type ProjectBibleFields = {
  worldEra: string;
  visualTone: string;
  colorLighting: string;
  cameraLanguage: string;
  characterSceneConsistency: string;
  avoidItems: string;
};

export type ProjectSetupDraft = {
  creationMode: 'direct'|'adaptation';
  name: string;
  episodeTitle: string;
  style: string;
  ratio: "16:9" | "9:16" | "1:1";
  duration: number;
  videoResolution: "480p" | "720p" | "1080p";
  videoRatio: "21:9" | "16:9" | "4:3" | "1:1" | "3:4" | "9:16" | "adaptive";
  videoDuration: number;
  videoFormat: "mp4" | "mov";
  videoReferenceMode: 'multimodal' | 'first_frame' | 'first_last_frame' | 'legacy';
  dialogueMode: 'voice_sample'|'full_dialogue';
  episodeCount: number;
  platform: string;
  brief: string;
  generationPolicy: GenerationPolicy;
  modelPool: ProjectModelPool;
  bible: ProjectBibleFields;
};

export function defaultGenerationPolicy(providers: Value[]): GenerationPolicy {
  return Object.fromEntries(
    (["text", "image", "video"] as const).map((kind) => {
      const model = providers.find(item => item.kind === kind && item.is_default);
      return [kind, model ? {model_id:model.id} : null];
    }),
  ) as GenerationPolicy;
}

export function defaultProjectSetupDraft(providers: Value[]): ProjectSetupDraft {
  return {
    creationMode:'direct',
    name: "",
    episodeTitle: "第 01 集",
    style: "电影写实",
    ratio: "16:9",
    duration: 120,
    videoResolution: "720p",
    videoRatio: "16:9",
    videoDuration: -1,
    videoFormat: "mp4",
    videoReferenceMode: 'multimodal',
    dialogueMode:'voice_sample',
    episodeCount: 1,
    platform: "通用短视频",
    brief: "",
    generationPolicy: defaultGenerationPolicy(providers),
    modelPool: defaultProjectModelPool(providers),
    bible: {
      worldEra: "",
      visualTone: "",
      colorLighting: "",
      cameraLanguage: "",
      characterSceneConsistency: "",
      avoidItems: "",
    },
  };
}

export function validateProjectSetupDraft(draft: ProjectSetupDraft): string[] {
  const errors: string[] = [];
  if(!['direct','adaptation'].includes(draft.creationMode))errors.push('请选择有效创作起点');
  if (!draft.name.trim()) errors.push("请输入作品名称");
  if (draft.name.trim().length > 100) errors.push("作品名称最多 100 个字符");
  if (draft.episodeTitle.trim().length > 100) errors.push("EP01 标题最多 100 个字符");
  if (!draft.style.trim()) errors.push("请输入视觉风格");
  if (!(["16:9", "9:16", "1:1"] as string[]).includes(draft.ratio)) errors.push("请选择有效画幅");
  if (!Number.isFinite(draft.duration) || draft.duration < 5 || draft.duration > 3000)
    errors.push("目标时长应为 5–3000 秒");
  if (!(["480p", "720p", "1080p"] as string[]).includes(draft.videoResolution))
    errors.push("请选择有效的视频分辨率");
  if (!(draft.videoDuration === -1 || (Number.isInteger(draft.videoDuration) && draft.videoDuration >= 4 && draft.videoDuration <= 30)))
    errors.push("视频输出时长应为 4–30 秒或 -1（按镜头自动）");
  if (!Number.isInteger(draft.episodeCount) || draft.episodeCount < 1 || draft.episodeCount > 500)
    errors.push("总集数应为 1–500 的整数");
  if (!draft.platform.trim()) errors.push("请选择发布平台");
  return errors;
}

function compactObject(value: Value): Value {
  return Object.fromEntries(Object.entries(value).filter(([, item]) =>
    Array.isArray(item) ? item.length > 0 : String(item ?? "").trim() !== "",
  ));
}

export function projectSetupPayload(draft: ProjectSetupDraft) {
  const avoidItems = draft.bible.avoidItems.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  return {
    creation_mode:draft.creationMode,
    name: draft.name.trim(),
    episode_title: draft.episodeTitle.trim() || "第 01 集",
    style: draft.style.trim(),
    ratio: draft.ratio,
    duration: draft.duration,
    video_resolution: draft.videoResolution,
    video_ratio: draft.videoRatio,
    video_duration: draft.videoDuration,
    video_format: draft.videoFormat,
    video_reference_mode: draft.videoReferenceMode,
    dialogue_mode:draft.dialogueMode,
    episode_count: draft.episodeCount,
    platform: draft.platform,
    brief: draft.brief,
    generation_policy: draft.generationPolicy,
    model_pool: draft.modelPool,
    film_bible: {
      story: compactObject({ worldEra: draft.bible.worldEra }),
      style: compactObject({
        visualTone: draft.bible.visualTone,
        colorLighting: draft.bible.colorLighting,
        cameraLanguage: draft.bible.cameraLanguage,
        avoidItems,
      }),
      continuity: compactObject({ characterSceneConsistency: draft.bible.characterSceneConsistency }),
    },
  };
}

export function bibleFields(document: Value): ProjectBibleFields {
  const bible = document.filmBible || {};
  return {
    worldEra: String(bible.story?.worldEra || ""),
    visualTone: String(bible.style?.visualTone || ""),
    colorLighting: String(bible.style?.colorLighting || ""),
    cameraLanguage: String(bible.style?.cameraLanguage || ""),
    characterSceneConsistency: String(bible.continuity?.characterSceneConsistency || ""),
    avoidItems: Array.isArray(bible.style?.avoidItems) ? bible.style.avoidItems.join("\n") : "",
  };
}

export function mergeBibleFields<T extends Value>(document: T, fields: ProjectBibleFields): T {
  const current = document.filmBible || {};
  const avoidItems = fields.avoidItems.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
  return {
    ...document,
    filmBible: {
      ...current,
      story: { ...(current.story || {}), worldEra: fields.worldEra },
      style: {
        ...(current.style || {}),
        visualTone: fields.visualTone,
        colorLighting: fields.colorLighting,
        cameraLanguage: fields.cameraLanguage,
        avoidItems,
      },
      continuity: {
        ...(current.continuity || {}),
        characterSceneConsistency: fields.characterSceneConsistency,
      },
    },
  };
}

export function applyRatioChange<T extends Value & { nodes: any[]; edges: any[]; shots: any[] }>(document: T, ratio: string): T {
  if (document.ratio === ratio) return document;
  const roots = new Set<string>();
  for (const shot of document.shots || []) {
    const image = shot.imageNode || shot.pipeline?.imageNodeId;
    const video = shot.videoNode || shot.pipeline?.videoNodeId;
    if (image) roots.add(image);
    if (video) roots.add(video);
  }
  return invalidate({ ...document, ratio }, [...roots]) as unknown as T;
}

export function applyStyleChange<T extends Value>(document: T, style: string): T {
  return setProjectVisualStyle(document as any, style) as T;
}

export function applyTargetDuration<T extends Value>(document: T, duration: number): T {
  return document.duration === duration ? document : { ...document, duration };
}

export function applyVideoResolution<T extends Value & { nodes: any[]; edges: any[]; shots: any[] }>(document: T, resolution: string): T {
  if (document.videoResolution === resolution) return document;
  const videoNodes = (document.nodes || []).filter((node) => node.data?.kind === "video").map((node) => node.id);
  return invalidate({ ...document, videoResolution: resolution }, videoNodes) as unknown as T;
}

export function applyVideoOutputSetting<T extends Value & { nodes: any[]; edges: any[]; shots: any[] }>(
  document: T,
  patch: { videoRatio?: string; videoDuration?: number; videoFormat?: string },
): T {
  if (Object.entries(patch).every(([key, value]) => document[key] === value)) return document;
  const videoNodes = (document.nodes || []).filter((node) => node.data?.kind === "video").map((node) => node.id);
  return invalidate({ ...document, ...patch }, videoNodes) as unknown as T;
}
