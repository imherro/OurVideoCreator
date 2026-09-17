import type { EditorAsset } from "./editorDocument";

export type EditorAssetPresentation = {
  asset: EditorAsset;
  title: string;
  subtitle: string;
  details: string;
  searchText: string;
};

const kindLabels: Record<string, string> = {
  video: "视频",
  image: "图片",
  audio: "音频",
};

const categoryLabels: Record<string, string> = {
  character: "角色",
  scene: "场景",
  prop: "道具",
  shot: "镜头",
  music: "音乐",
  sfx: "音效",
  voice: "对白",
  reference: "参考图", motion_reference: "动作参考",
};

function humanizeLabel(value: unknown) {
  return String(value || "")
    .replace(/\bshot[-_ ]?(\d+)\b/gi, (_, number) => `镜头 ${String(Number(number)).padStart(2, "0")}`)
    .trim();
}

function genericGeneratedName(value: string) {
  return /^(生成结果|Seedream 生成图|幻场 AI 生成图)(?:\s*·[^.]*)?\.[^.]+$/i.test(value.trim());
}

function nodeIdOf(asset: EditorAsset) {
  return String(asset.metadata?.node_id || "");
}

export function editorAssetProjectId(asset: EditorAsset) {
  return asset.project_id || asset.origin_project_id || "";
}

export function filterEditorAssetsByEpisode(assets: EditorAsset[], scope: string) {
  return scope === "all" ? assets : assets.filter((asset) => editorAssetProjectId(asset) === scope);
}

function versionGroup(asset: EditorAsset) {
  return JSON.stringify([editorAssetProjectId(asset), nodeIdOf(asset), asset.kind]);
}

function shotNodeIds(shot: Record<string, any>) {
  return new Set([
    shot.imageNode,
    shot.videoNode,
    shot.pipeline?.imageNodeId,
    shot.pipeline?.videoNodeId,
  ].filter(Boolean).map(String));
}

export function presentEditorAssets(
  assets: EditorAsset[],
  shots: Record<string, any>[],
  currentProjectId?: string,
): EditorAssetPresentation[] {
  const versions = new Map<string, Map<string, number>>();
  const grouped = new Map<string, EditorAsset[]>();
  for (const asset of assets) {
    const nodeId = nodeIdOf(asset);
    if (!nodeId) continue;
    const key = versionGroup(asset);
    grouped.set(key, [...(grouped.get(key) || []), asset]);
  }
  for (const [key, items] of grouped) {
    const ranks = new Map<string, number>();
    [...items]
      .sort((left, right) => Number(left.created || 0) - Number(right.created || 0) || left.id.localeCompare(right.id))
      .forEach((asset, index) => ranks.set(asset.id, index + 1));
    versions.set(key, ranks);
  }

  return assets.map((asset) => {
    const input = asset.metadata?.input || {};
    const nodeId = nodeIdOf(asset);
    const belongsToCurrent = !currentProjectId || editorAssetProjectId(asset) === currentProjectId;
    const shotIndex = nodeId && belongsToCurrent ? shots.findIndex((shot) => shotNodeIds(shot).has(nodeId)) : -1;
    const shot = shotIndex >= 0 ? shots[shotIndex] : undefined;
    const shotNumber = shot
      ? Number(String(shot.id || "").match(/^(?:shot[-_ ]?)?(\d+)$/i)?.[1] || shotIndex + 1)
      : 0;
    const kindLabel = kindLabels[asset.kind] || asset.kind;
    const sourceLabel = humanizeLabel(input.output_name || input.asset_label || input.label);
    const fallback = genericGeneratedName(asset.name) && sourceLabel ? sourceLabel : asset.name;
    const title = shot ? `镜头 ${String(shotNumber).padStart(2, "0")} · ${kindLabel}` : fallback;
    const subtitle = shot
      ? String(shot.title || shot.action || shot.description || sourceLabel || "生成素材")
      : String(input.character_name || input.dialogue?.text || sourceLabel || categoryLabels[(asset as any).category] || "项目素材");
    const duration = Number(asset.metadata?.duration);
    const plannedDuration = Number(
      shot?.duration ?? input.shot_duration ?? input.parameters?.duration,
    );
    const rank = nodeId ? versions.get(versionGroup(asset))?.get(asset.id) : undefined;
    const versionCount = nodeId ? grouped.get(versionGroup(asset))?.length || 0 : 0;
    const details = [
      asset.origin_episode_no ? `EP${String(asset.origin_episode_no).padStart(2, "0")}` : undefined,
      Number.isFinite(duration) && duration > 0 ? `素材 ${duration.toFixed(1)} 秒` : undefined,
      asset.kind === "video" && Number.isFinite(plannedDuration) && plannedDuration > 0 && Math.abs(plannedDuration - duration) > 0.05
        ? `镜头 ${plannedDuration.toFixed(1)} 秒`
        : undefined,
      versionCount > 1 && rank ? `V${rank}` : undefined,
      (asset as any).category ? categoryLabels[(asset as any).category] || (asset as any).category : undefined,
      input.model_name || input.model_id ? String(input.model_name || input.model_id) : undefined,
    ].filter(Boolean).join(" · ") || kindLabel;
    return {
      asset,
      title,
      subtitle,
      details,
      searchText: [title, subtitle, details, asset.name, nodeId].join(" ").toLowerCase(),
    };
  });
}
