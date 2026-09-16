import type { ElementJSON, ProjectJSON, Size, TrackJSON } from "@twick/timeline";
import { attachAssetReferences, type EditorAsset } from "./editorDocument.ts";

type Value = Record<string, any>;

export type InitialTimelinePlan = {
  timeline: ProjectJSON;
  issues: string[];
  clipCount: number;
};

export function planInitialTimeline(
  {
    shots,
    nodes,
    assets,
    resolution,
    audioId,
    musicVolume = 0.3,
  }: {
    shots: Value[];
    nodes: Value[];
    assets: EditorAsset[];
    resolution: Size;
    audioId?: string;
    musicVolume?: number;
  },
  newId: () => string,
): InitialTimelinePlan {
  const issues: string[] = [];
  const elements: ElementJSON[] = [];
  const dialogueElements: ElementJSON[] = [];
  let cursor = 0;

  shots.forEach((shot, index) => {
    const label = `第 ${index + 1} 镜`;
    const videoNodeId = shot.videoNode || shot.pipeline?.videoNodeId;
    const node = nodes.find((candidate) => candidate.id === videoNodeId);
    const asset = assets.find(
      (candidate) => candidate.id === node?.data?.assetId && candidate.kind === "video",
    );
    if (!node || !asset) {
      issues.push(`${label}缺少已生成视频`);
      return;
    }
    if (node.data?.stale || shot.prompts_need_review) {
      issues.push(`${label}输入已变更，请核对并重新生成`);
      return;
    }
    const plannedDuration = Number(shot.duration);
    const mediaDuration = Number(asset.metadata?.duration);
    if (
      !Number.isFinite(plannedDuration) ||
      plannedDuration <= 0 ||
      !Number.isFinite(mediaDuration) ||
      mediaDuration <= 0
    ) {
      issues.push(`${label}时长无效`);
      return;
    }
    if (plannedDuration > mediaDuration + 0.08) {
      issues.push(`${label}需要 ${plannedDuration} 秒，素材仅 ${mediaDuration.toFixed(2)} 秒`);
      return;
    }

    const duration = Math.min(plannedDuration, mediaDuration);
    const elementId = `e-${newId()}`;
    const shotStart = cursor;
    const dialogueAssets: EditorAsset[] = (Array.isArray(shot.dialogues) ? shot.dialogues : []).flatMap((dialogue: Value) => {
      const selected = assets.find(candidate => candidate.kind === "audio" && candidate.id === dialogue.audioAssetId
        && Number(dialogue.audioVoiceVersion) >= 1
        && candidate.metadata?.input?.dialogue?.voiceVersion === dialogue.audioVoiceVersion
        && candidate.metadata?.input?.dialogue?.id === dialogue.id
        && candidate.metadata?.input?.dialogue?.text === dialogue.text
        && String(candidate.metadata?.input?.dialogue?.shotUid || "") === String(shot.uid || shot.id || ""));
      return selected ? [selected] : [];
    });
    elements.push({
      id: elementId,
      trackId: "t-v1",
      type: "video",
      name: shot.title || `${label} · ${asset.name}`,
      s: cursor,
      e: cursor + duration,
      props: {
        src: asset.url,
        srcAssetId: asset.id,
        time: 0,
        playbackRate: 1,
        volume: dialogueAssets.length ? 0 : 1,
        mediaFilter: "none",
      },
      metadata: {
        assetId: asset.id,
        assetSource: "my-video-creator",
        shotId: shot.id || shot.shot_id,
        nodeId: node.id,
        generatedInitialEdit: true,
      },
      frame: { x: 0, y: 0, size: [resolution.width, resolution.height] },
      objectFit: "cover",
      mediaDuration,
    });
    let dialogueCursor = shotStart;
    dialogueAssets.forEach((dialogueAsset) => {
      const dialogueDuration = Number(dialogueAsset.metadata?.duration);
      if (!Number.isFinite(dialogueDuration) || dialogueDuration <= 0) {
        issues.push(`${label}对白“${dialogueAsset.name}”时长无效`);
        return;
      }
      if (dialogueCursor + dialogueDuration > shotStart + duration + 0.08) {
        issues.push(`${label}对白总时长超过镜头时长`);
        return;
      }
      dialogueElements.push({
        id: `e-${newId()}`, trackId: "t-dialogue", type: "audio", name: dialogueAsset.name,
        s: dialogueCursor, e: dialogueCursor + dialogueDuration,
        props: { src: dialogueAsset.url, srcAssetId: dialogueAsset.id, time: 0, playbackRate: 1, volume: 1 },
        metadata: { assetId: dialogueAsset.id, assetSource: "my-video-creator", role: "dialogue", shotId: shot.id, generatedInitialEdit: true },
        mediaDuration: dialogueDuration,
      });
      dialogueCursor += dialogueDuration;
    });
    cursor += duration;
  });

  const tracks: TrackJSON[] = [
    { id: "t-v1", name: "V1 · AI 初剪", type: "video", elements },
  ];
  if (dialogueElements.length) tracks.push({ id: "t-dialogue", name: "A1 · 角色对白", type: "audio", elements: dialogueElements });

  const music = assets.find((asset) => asset.id === audioId && asset.kind === "audio");
  if (music && cursor > 0) {
    const mediaDuration = Number(music.metadata?.duration);
    tracks.push({
      id: "t-music",
      name: "A2 · 背景音乐",
      type: "audio",
      elements: [
        {
          id: `e-${newId()}`,
          trackId: "t-music",
          type: "audio",
          name: music.name,
          s: 0,
          e: cursor,
          props: {
            src: music.url,
            srcAssetId: music.id,
            time: 0,
            playbackRate: 1,
            volume: Math.max(0, Math.min(2, musicVolume)),
            loop: true,
          },
          metadata: {
            assetId: music.id,
            assetSource: "my-video-creator",
            role: "background-music",
            generatedInitialEdit: true,
          },
          mediaDuration:
            Number.isFinite(mediaDuration) && mediaDuration > 0 ? mediaDuration : cursor,
        },
      ],
    });
  }

  const timeline = attachAssetReferences(
    {
      tracks,
      version: 2,
      backgroundColor: "#000000",
      metadata: {
        custom: {
          host: "my-video-creator",
          schema: "mvc-editor-v1",
          source: "storyboard",
        },
      },
    },
    assets,
  );

  return { timeline, issues, clipCount: elements.length };
}
