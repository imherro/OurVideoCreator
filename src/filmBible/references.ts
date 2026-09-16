import type { GenerationPolicy, GenerationTarget } from "../generationPolicy.ts";
import { resolveGenerationTarget } from "../generationPolicy.ts";
import type {
  FilmBibleDocument,
  VisualBible,
  VisualCard,
  VisualGenerationOverride,
  VisualReference,
  VisualVersion,
} from "./types.ts";
import { visualBibleOf } from "./types.ts";

type Provider = Record<string, any>;

export type ResolvedVisualGenerationTarget = GenerationTarget & {
  source: "override" | "project" | "system";
};

export type VisualReferencePlan = {
  versionId: string;
  prompt: string;
  model_id: string;
  targetSource: "override" | "project" | "system";
  assetIds: string[];
  assetCategory: "character" | "scene" | "prop";
  parentVersionId?: string;
  parentReferenceAssetId?: string;
};

function requireVisual(visual: VisualBible, versionId: string) {
  const version = visual.versions[versionId];
  const card = version ? visual.cards[version.cardId] : undefined;
  if (!version || !card) throw new Error("视觉版本不存在或所属卡片已丢失");
  return { version, card };
}

function replaceVersion<T extends FilmBibleDocument>(
  document: T,
  version: VisualVersion,
): T {
  const visual = visualBibleOf(document);
  return {
    ...document,
    filmBible: {
      ...(document.filmBible || {}),
      visual: {
        ...visual,
        versions: { ...visual.versions, [version.id]: version },
      },
    },
  } as T;
}

export function primaryReference(version: VisualVersion | undefined) {
  return version?.references?.find((item) => item?.role === "primary");
}

export function isStateCard(card: VisualCard) {
  return card.kind === "character_state" || card.kind === "scene_state";
}

export function visualAssetCategory(card: VisualCard) {
  if (card.kind === "character" || card.kind === "character_state")
    return "character" as const;
  if (card.kind === "scene" || card.kind === "scene_state")
    return "scene" as const;
  return "prop" as const;
}

export function resolveVisualGenerationTarget(
  card: VisualCard,
  policy: GenerationPolicy | undefined,
  providers: Provider[],
  localModels: Provider[] = [],
): ResolvedVisualGenerationTarget {
  return resolveGenerationTarget(
    "image",
    card.generation?.image,
    policy,
    providers,
    localModels,
  );
}

export function setVisualCardImageOverride<T extends FilmBibleDocument>(
  document: T,
  cardId: string,
  override: VisualGenerationOverride,
): T {
  const visual = visualBibleOf(document);
  const card = visual.cards[cardId];
  if (!card) throw new Error("视觉卡不存在");
  if (card.status === "deprecated") throw new Error("已弃用视觉卡不能修改生成策略");
  const currentVersion = visual.versions[card.currentVersionId];
  if (currentVersion && !['draft', 'pending_reference'].includes(currentVersion.status))
    throw new Error("已锁定或已弃用视觉版本的生成策略不可修改");
  // An explicit empty override is a draft, never a silent fallback choice.
  const generation = {
    ...(card.generation || {}),
    image: override,
  };
  return {
    ...document,
    filmBible: {
      ...(document.filmBible || {}),
      visual: {
        ...visual,
        cards: { ...visual.cards, [cardId]: { ...card, generation } },
      },
    },
  } as T;
}

function promptFor(
  visual: VisualBible,
  version: VisualVersion,
  card: VisualCard,
  parent?: { version: VisualVersion; card: VisualCard },
) {
  const attributes = version.spec.attributes
    .map((item) => `${item.name}：${item.value}`)
    .join("；");
  const invariants = version.invariants.join("；");
  const lines = [
    "生成一张影视视觉圣经主参考图。画面只用于固定后续镜头的一致性，不要添加文字、水印、分镜框或拼贴。",
    `资产类型：${card.kind}`,
    `资产名称：${card.name}`,
    `可见外观：${version.spec.description}`,
    attributes ? `结构化属性：${attributes}` : "",
    invariants ? `不可改变项：${invariants}` : "",
  ].filter(Boolean);
  if (parent) {
    lines.push(
      `这是“${parent.card.name}”的状态版本。必须以输入参考图中的身份、脸型、服装主体、材质与场景结构为准，只表现本状态的可见变化。`,
      `父版本外观：${parent.version.spec.description}`,
    );
  }
  return lines.join("\n");
}

export function planVisualReferenceGeneration(
  document: FilmBibleDocument,
  versionId: string,
  target: ResolvedVisualGenerationTarget,
  capabilities?: Record<string, any>,
): VisualReferencePlan {
  const visual = visualBibleOf(document);
  const { version, card } = requireVisual(visual, versionId);
  if (!['draft', 'pending_reference'].includes(version.status))
    throw new Error("已锁定或已弃用的视觉版本不能重新生成参考图");
  if (!target.model_id)
    throw new Error("图片生成服务或模型尚未配置");
  let parent: { version: VisualVersion; card: VisualCard } | undefined;
  let parentReferenceAssetId: string | undefined;
  if (isStateCard(card)) {
    const parentVersion = version.parentVersionId
      ? visual.versions[version.parentVersionId]
      : undefined;
    const parentCard = parentVersion
      ? visual.cards[parentVersion.cardId]
      : undefined;
    if (!parentVersion || !parentCard)
      throw new Error("状态资产缺少创建时冻结的父版本");
    if (parentVersion.status !== "locked")
      throw new Error("请先确认并锁定父版本参考图，再生成状态资产");
    parentReferenceAssetId = primaryReference(parentVersion)?.assetId;
    if (!parentReferenceAssetId)
      throw new Error("父版本缺少已锁定的主参考图");
    if (capabilities?.image_reference !== true)
      throw new Error(
        "所选模型未明确支持参考图；状态资产若按纯文生图生成会破坏身份一致性，请改用支持参考图的模型或上传参考图",
      );
    parent = { version: parentVersion, card: parentCard };
  }
  return {
    versionId,
    prompt: promptFor(visual, version, card, parent),
    model_id: target.model_id,
    targetSource: target.source,
    assetIds: parentReferenceAssetId ? [parentReferenceAssetId] : [],
    assetCategory: visualAssetCategory(card),
    ...(parent
      ? {
          parentVersionId: parent.version.id,
          parentReferenceAssetId,
        }
      : {}),
  };
}

export function attachUploadedPrimaryReference<T extends FilmBibleDocument>(
  document: T,
  versionId: string,
  asset: { id: string; name?: string },
  createdAt = Date.now(),
): T {
  const visual = visualBibleOf(document);
  const { version } = requireVisual(visual, versionId);
  if (!['draft', 'pending_reference'].includes(version.status))
    throw new Error("已锁定或已弃用的视觉版本不能替换参考图");
  const reference: VisualReference = {
    role: "primary",
    assetId: asset.id,
    source: "uploaded",
    createdAt,
    provenance: { filename: asset.name },
  };
  return replaceVersion(document, {
    ...version,
    status: "pending_reference",
    references: [
      ...(version.references || []).filter((item) => item.role !== "primary"),
      reference,
    ],
    provenance: {
      ...(version.provenance || {}),
      primaryReference: reference.provenance,
    },
  });
}

export function acceptVisualReferenceResult<T extends FilmBibleDocument>(
  document: T,
  job: {
    id: string;
    submission_id?: string;
    node_id: string;
    input?: Record<string, any>;
    result?: Record<string, any>;
  },
  createdAt = Date.now(),
): T {
  if (!job.node_id.startsWith("visual-version:")) return document;
  const versionId = job.node_id.slice("visual-version:".length);
  const visual = visualBibleOf(document);
  const { version } = requireVisual(visual, versionId);
  const generation = version.provenance?.referenceGeneration as
    | Record<string, any>
    | undefined;
  if (
    !generation ||
    (generation.jobId
      ? generation.jobId !== job.id
      : generation.submissionId !== job.submission_id)
  )
    return document;
  if (!['draft', 'pending_reference'].includes(version.status)) return document;
  if (primaryReference(version)?.provenance.jobId === job.id) return document;
  const asset = job.result?.assets?.[0];
  if (!asset?.id) throw new Error("参考图任务完成但没有返回图片素材");
  const reference: VisualReference = {
    role: "primary",
    assetId: asset.id,
    source: "generated",
    createdAt,
    provenance: {
      jobId: job.id,
      submissionId: job.submission_id || generation.submissionId,
      model_id: generation.model_id,
      targetSource: generation.targetSource,
      prompt: generation.prompt,
      parentVersionId: generation.parentVersionId,
      parentReferenceAssetId: generation.parentReferenceAssetId,
    },
  };
  return replaceVersion(document, {
    ...version,
    status: "pending_reference",
    references: [
      ...(version.references || []).filter((item) => item.role !== "primary"),
      reference,
    ],
    provenance: {
      ...(version.provenance || {}),
      primaryReference: reference.provenance,
      referenceGeneration: { ...generation, status: "succeeded" },
    },
  });
}

export function lockVisualVersion<T extends FilmBibleDocument>(
  document: T,
  versionId: string,
  lockedAt = Date.now(),
): T {
  const visual = visualBibleOf(document);
  const { version } = requireVisual(visual, versionId);
  if (version.status !== "pending_reference")
    throw new Error("只有待确认参考图的版本可以锁定");
  if (!primaryReference(version)) throw new Error("请先上传或生成主参考图");
  return replaceVersion(document, {
    ...version,
    status: "locked",
    provenance: { ...(version.provenance || {}), lockedAt },
  });
}
