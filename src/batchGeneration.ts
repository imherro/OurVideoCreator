import { requiresInitialStateReview } from "./graph.ts";
import {
  isStateCard,
  primaryReference,
  resolveVisualGenerationTarget,
} from "./filmBible/references.ts";
import { visualBibleOf } from "./filmBible/types.ts";
import type { GenerationPolicy } from "./generationPolicy.ts";

type Value = Record<string, any>;

export type BatchGenerationKind = "assets" | "shot_images" | "shot_videos";

export type BatchGenerationPlan = {
  kind: BatchGenerationKind;
  readyIds: string[];
  blocked: Array<{ id: string; label: string; reason: string }>;
  skipped: Array<{ id: string; label: string; reason: string }>;
  cloudCount: number;
};

function providerFor(data: Value, providers: Value[]) {
  return providers.find((provider) => provider.id === data.model_id);
}

function isCloud(provider: Value | undefined) {
  return Boolean(provider && !provider.local);
}

function currentJob(jobs: Value[], nodeId: string) {
  return (
    jobs.find(
      (job) =>
        job.node_id === nodeId &&
        ["queued", "running", "interrupted"].includes(job.status),
    ) || jobs.find((job) => job.node_id === nodeId)
  );
}

function planVisualAssets(
  document: Value,
  jobs: Value[],
  providers: Value[],
  localModels: Value[],
): BatchGenerationPlan {
  const result: BatchGenerationPlan = {
    kind: "assets",
    readyIds: [],
    blocked: [],
    skipped: [],
    cloudCount: 0,
  };
  const visual = visualBibleOf(document as any);
  for (const card of Object.values(visual.cards)) {
    if (card.status === "deprecated") continue;
    const version = visual.versions[card.currentVersionId];
    if (!version) {
      result.blocked.push({ id: card.id, label: card.name, reason: "当前版本不存在" });
      continue;
    }
    const nodeId = `visual-version:${version.id}`;
    const job = currentJob(jobs, nodeId);
    if (["queued", "running", "interrupted"].includes(job?.status)) {
      result.skipped.push({ id: version.id, label: card.name, reason: "任务已在队列中" });
      continue;
    }
    if (job?.status === "succeeded" && job.result?.assets?.length) {
      result.skipped.push({ id: version.id, label: card.name, reason: "结果正在同步" });
      continue;
    }
    if (primaryReference(version)) {
      result.skipped.push({
        id: version.id,
        label: card.name,
        reason: version.status === "locked" ? "参考图已确认" : "参考图等待人工确认",
      });
      continue;
    }
    if (version.status === "locked" || version.status === "deprecated") {
      result.blocked.push({ id: version.id, label: card.name, reason: "当前版本不可生成" });
      continue;
    }
    if (isStateCard(card)) {
      const parent = version.parentVersionId
        ? visual.versions[version.parentVersionId]
        : undefined;
      if (!parent || parent.status !== "locked" || !primaryReference(parent)) {
        result.blocked.push({
          id: version.id,
          label: card.name,
          reason: "需要先确认并锁定父版本参考图",
        });
        continue;
      }
    }
    try {
      const target = resolveVisualGenerationTarget(
        card,
        document.generationPolicy as GenerationPolicy | undefined,
        providers,
        localModels,
      );
      const provider = providers.find((item) => item.id === target.model_id);
      if (!provider) throw new Error("图片生成服务不存在");
      result.readyIds.push(version.id);
      if (isCloud(provider)) result.cloudCount += 1;
    } catch (reason: any) {
      result.blocked.push({
        id: version.id,
        label: card.name,
        reason: reason?.message || String(reason),
      });
    }
  }
  return result;
}

function planShotNodes(
  document: Value,
  jobs: Value[],
  providers: Value[],
  kind: "shot_images" | "shot_videos",
): BatchGenerationPlan {
  const result: BatchGenerationPlan = {
    kind,
    readyIds: [],
    blocked: [],
    skipped: [],
    cloudCount: 0,
  };
  const nodes = new Map<string, Value>(
    (document.nodes || []).map((node: Value) => [node.id, node]),
  );
  const visual = visualBibleOf(document as any);
  const hasVisualCards = Object.values(visual.cards).some((card) => !card.deletedAt && card.status !== "deprecated");
  for (const [index, shot] of (document.shots || []).entries()) {
    const nodeId =
      kind === "shot_images"
        ? shot.imageNode || shot.pipeline?.imageNodeId
        : shot.videoNode || shot.pipeline?.videoNodeId;
    const label = `${shot.id || `镜头 ${index + 1}`} · ${kind === "shot_images" ? "分镜图" : "视频"}`;
    const node = nodeId ? nodes.get(nodeId) : undefined;
    if (!node) {
      result.blocked.push({ id: String(nodeId || shot.id || index), label, reason: "生成节点不存在" });
      continue;
    }
    const job = currentJob(jobs, node.id);
    if (["queued", "running", "interrupted"].includes(job?.status)) {
      result.skipped.push({ id: node.id, label, reason: "任务已在队列中" });
      continue;
    }
    if (node.data.assetId && !node.data.stale) {
      result.skipped.push({ id: node.id, label, reason: "已有有效结果" });
      continue;
    }
    if (!String(node.data.prompt || "").trim()) {
      result.blocked.push({ id: node.id, label, reason: "生成描述为空" });
      continue;
    }
    if (kind === "shot_images") {
      const bindings = shot.assetBindings || {};
      const versionIds = [
        ...(bindings.characters || []).map((item: Value) => item.versionId),
        ...(bindings.props || []).map((item: Value) => item.versionId),
        bindings.scene?.versionId,
      ].filter(Boolean);
      if (hasVisualCards && !versionIds.length) {
        result.blocked.push({ id: node.id, label, reason: "尚未绑定本镜头需要的视觉版本" });
        continue;
      }
      const invalid = versionIds.find((versionId) => {
        const version = visual.versions[versionId];
        return !version || version.status !== "locked" || !primaryReference(version);
      });
      if (invalid) {
        result.blocked.push({ id: node.id, label, reason: "绑定的视觉版本尚未锁定或缺少主参考图" });
        continue;
      }
    }
    const provider = providerFor(node.data, providers);
    if (!provider || node.data.model_id === "local") {
      result.blocked.push({ id: node.id, label, reason: "尚未选择可用的媒体生成服务" });
      continue;
    }
    if (kind === "shot_videos") {
      const imageId = shot.imageNode || shot.pipeline?.imageNodeId;
      const image = imageId ? nodes.get(imageId) : undefined;
      if (!image?.data.assetId || image.data.stale) {
        result.blocked.push({ id: node.id, label, reason: "对应分镜图尚未生成或已经过期" });
        continue;
      }
      if (
        requiresInitialStateReview(image.data.prompt) &&
        !image.data.state_reviewed
      ) {
        result.blocked.push({ id: node.id, label, reason: "对应分镜图尚未核验首帧状态" });
        continue;
      }
    }
    result.readyIds.push(node.id);
    if (isCloud(provider)) result.cloudCount += 1;
  }
  return result;
}

export function planBatchGeneration(
  document: Value,
  jobs: Value[],
  providers: Value[],
  localModels: Value[],
  kind: BatchGenerationKind,
): BatchGenerationPlan {
  return kind === "assets"
    ? planVisualAssets(document, jobs, providers, localModels)
    : planShotNodes(document, jobs, providers, kind);
}
