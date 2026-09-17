import type { WorkflowStage } from "./workflow";

export type WorkflowStageState =
  | "unstarted"
  | "ready"
  | "running"
  | "review"
  | "complete"
  | "skipped"
  | "stale"
  | "blocked";

export type WorkflowStageGuide = {
  stage: WorkflowStage;
  state: WorkflowStageState;
  headline: string;
  reasons: string[];
  action?: { label: string; stage: WorkflowStage };
};

export type WorkflowGuide = {
  stages: Partial<Record<WorkflowStage, WorkflowStageGuide>>;
  recommendedStage: WorkflowStage;
};

type Value = Record<string, any>;
const activeStatuses = new Set(["queued", "running"]);

function activeJob(jobs: Value[], predicate: (job: Value) => boolean) {
  return jobs.some((job) => activeStatuses.has(job.status) && predicate(job));
}

function bindingIds(shots: Value[]) {
  const ids = new Set<string>();
  for (const shot of shots) {
    const bindings = shot.assetBindings || {};
    for (const item of bindings.characters || []) if (item?.versionId) ids.add(item.versionId);
    for (const item of bindings.props || []) if (item?.versionId) ids.add(item.versionId);
    if (bindings.scene?.versionId) ids.add(bindings.scene.versionId);
  }
  return [...ids];
}

function generatedState(document: Value, shots: Value[], kind: "image" | "video") {
  const key = kind === "image" ? "imageNode" : "videoNode";
  const pipelineKey = kind === "image" ? "imageNodeId" : "videoNodeId";
  const nodes = shots.map((shot) => document.nodes?.find((node: Value) => node.id === (shot[key] || shot.pipeline?.[pipelineKey])));
  const complete = nodes.filter((node) => node?.data?.assetId && !node.data.stale).length;
  const stale = nodes.some((node) => node?.data?.stale);
  return { complete, stale, total: shots.length };
}

export function deriveWorkflowGuide(input: {
  adaptation?: Value | null;
  scripts?: Value[];
  currentProject?: Value | null;
  document?: Value | null;
  jobs?: Value[];
}): WorkflowGuide {
  const adaptation = input.adaptation || {};
  const scripts = input.scripts || [];
  const project = input.currentProject || {};
  const document = input.document || {};
  const jobs = input.jobs || [];
  const shots: Value[] = document.shots || [];
  const sourceEventCount = Number(adaptation.sourceEventCount || 0);
  const adaptationStatus = adaptation.adaptationPlan?.status;
  const currentScript = scripts.find((item) => item.projectId === project.id || item.episodeNo === project.episode_no)?.script;
  const quickCanvasScript = currentScript?.metadata?.origin === "canvas" && Boolean(String(currentScript?.body || "").trim());
  const scriptApproved = currentScript?.status === "approved";
  const approvedScripts = scripts.filter((item) => item.script?.status === "approved").length;
  const requiredVersionIds = bindingIds(shots);
  const visual = document.filmBible?.visual || { cards: {}, versions: {} };
  const hasVisualCards = Object.values(visual.cards || {}).some((card: any) => !card.deletedAt);
  const missingReferences = requiredVersionIds.filter((id) => {
    const version = visual.versions?.[id];
    return !version || version.status !== "locked" || !version.references?.some((ref: Value) => ref.role === "primary" && ref.assetId);
  });
  const imageState = generatedState(document, shots, "image");
  const videoState = generatedState(document, shots, "video");
  const imageRunning = activeJob(jobs, (job) => job.kind === "image" && job.input?.stage !== "visual_reference" && !job.input?.visual_reference);
  const videoRunning = activeJob(jobs, (job) => job.kind === "video");
  const storyboardRunning = activeJob(jobs, (job) => job.kind === "storyboard");
  const artRunning = activeJob(jobs, (job) => job.kind === "image" && (job.input?.stage === "visual_reference" || job.input?.visual_reference));
  const timelineReady = Boolean(document.editor?.timeline?.tracks?.some((track: Value) => track.elements?.length) || document.timeline?.length);

  const stages: WorkflowGuide["stages"] = {
    source: quickCanvasScript && !sourceEventCount
      ? { stage: "source", state: "skipped", headline: "画布快速创作未使用原著", reasons: ["需要时仍可导入原著，现有正式剧本不会丢失。"] }
      : sourceEventCount
      ? { stage: "source", state: "complete", headline: `已提取 ${sourceEventCount} 条原著事件`, reasons: [], action: { label: "进入改编策划", stage: "adaptation" } }
      : { stage: "source", state: "ready", headline: "导入原著并提取事件", reasons: ["改编策划需要可追溯的原著事件。"] },
    adaptation: quickCanvasScript && adaptationStatus !== "approved"
      ? { stage: "adaptation", state: "skipped", headline: "画布快速创作已跳过改编策划", reasons: ["可以直接完善本集正式剧本，也可以稍后补充改编策划。"] }
      : adaptationStatus === "approved"
      ? { stage: "adaptation", state: "complete", headline: "改编策划已批准", reasons: [], action: { label: "进入剧本", stage: "script" } }
      : adaptationStatus === "review"
        ? { stage: "adaptation", state: "review", headline: "改编策划等待审核", reasons: ["批准后才可生成逐集剧本。"] }
        : adaptationStatus === "stale"
          ? { stage: "adaptation", state: "stale", headline: "原著已改变，请更新改编策划", reasons: ["旧策划仍保留，可检查差异后重新生成或修改。"] }
          : sourceEventCount
            ? { stage: "adaptation", state: "ready", headline: "可以建立改编策划", reasons: [] }
            : { stage: "adaptation", state: "blocked", headline: "先完成原著事件提取", reasons: ["当前没有可供改编引用的原著事件。"], action: { label: "前往原著", stage: "source" } },
    script: quickCanvasScript && currentScript?.status === "approved"
      ? { stage: "script", state: "complete", headline: "本集画布剧本已批准", reasons: [] }
      : quickCanvasScript && currentScript?.status === "review"
        ? { stage: "script", state: "review", headline: "本集画布剧本等待审核", reasons: ["批准后即可进入分镜规划。"] }
        : quickCanvasScript
          ? { stage: "script", state: "ready", headline: "画布剧本已进入剧本室", reasons: ["继续修订并提交审核，画布将同步同一份正式剧本。"] }
          : approvedScripts === scripts.length && scripts.length
      ? { stage: "script", state: "complete", headline: `${approvedScripts} 集剧本已批准`, reasons: [] }
      : scripts.some((item) => item.script?.status === "review")
        ? { stage: "script", state: "review", headline: "有剧本等待审核", reasons: ["逐集批准后即可进入该集制作。"] }
        : adaptationStatus === "approved"
          ? { stage: "script", state: "ready", headline: "生成、修订并批准逐集剧本", reasons: [] }
          : { stage: "script", state: "blocked", headline: "先批准改编策划", reasons: ["未批准的策划不能生成正式剧本。"], action: { label: "前往改编策划", stage: "adaptation" } },
    storyboard: storyboardRunning
      ? { stage: "storyboard", state: "running", headline: "分镜规划正在生成", reasons: ["可在任务中心查看提示词、阶段和返回结果。"] }
      : shots.length
        ? hasVisualCards && !requiredVersionIds.length
          ? { stage: "storyboard", state: "review", headline: `本集已有 ${shots.length} 个镜头，请确认资产绑定`, reasons: ["当前 Film Bible 已有视觉资产，但分镜尚未绑定任何版本。"] }
          : { stage: "storyboard", state: "complete", headline: `本集已有 ${shots.length} 个镜头`, reasons: [], action: { label: "确认视觉资产", stage: "art" } }
        : scriptApproved
          ? { stage: "storyboard", state: "ready", headline: "从已批准剧本建立分镜规划", reasons: [] }
          : { stage: "storyboard", state: "blocked", headline: "先批准本集剧本", reasons: ["分镜规划只能从本集已批准剧本开始。"], action: { label: "前往剧本", stage: "script" } },
    art: artRunning
      ? { stage: "art", state: "running", headline: "资产参考图正在生成", reasons: [] }
      : !shots.length
        ? { stage: "art", state: "blocked", headline: "先建立本集分镜", reasons: ["分镜中的资产绑定决定“本集需要”的清单。"], action: { label: "前往分镜规划", stage: "storyboard" } }
        : hasVisualCards && !requiredVersionIds.length
          ? { stage: "art", state: "blocked", headline: "先在分镜规划中绑定本集资产", reasons: ["“本集需要”清单来自镜头的 VisualVersion 绑定。"], action: { label: "前往分镜规划", stage: "storyboard" } }
          : missingReferences.length
          ? { stage: "art", state: "ready", headline: `${missingReferences.length} 个本集视觉版本待确认`, reasons: ["生成主参考图并锁定版本后，才能稳定生成分镜图。"] }
          : { stage: "art", state: "complete", headline: requiredVersionIds.length ? "本集视觉资产已就绪" : "本集没有待确认的共享视觉资产", reasons: [], action: { label: "生成分镜图", stage: "images" } },
    images: imageRunning
      ? { stage: "images", state: "running", headline: "分镜图正在生成", reasons: [`已完成 ${imageState.complete}/${imageState.total} 镜。`] }
      : imageState.stale
        ? { stage: "images", state: "stale", headline: "部分分镜图需要更新", reasons: ["镜头提示词或视觉绑定已经改变。"] }
        : imageState.total && imageState.complete === imageState.total
          ? { stage: "images", state: "complete", headline: `本集 ${imageState.total} 张分镜图已就绪`, reasons: [], action: { label: "生成镜头视频", stage: "video" } }
          : !shots.length || missingReferences.length
            ? { stage: "images", state: "blocked", headline: !shots.length ? "先建立本集分镜" : "先完成本集视觉资产", reasons: [!shots.length ? "当前没有可生成的镜头。" : `${missingReferences.length} 个镜头引用版本尚未锁定或缺少主参考图。`], action: { label: !shots.length ? "前往分镜规划" : "前往塑角造景", stage: !shots.length ? "storyboard" : "art" } }
            : { stage: "images", state: "ready", headline: `可生成 ${imageState.total - imageState.complete} 张分镜图`, reasons: [] },
    video: videoRunning
      ? { stage: "video", state: "running", headline: "镜头视频正在生成", reasons: [`已完成 ${videoState.complete}/${videoState.total} 镜。`] }
      : videoState.stale
        ? { stage: "video", state: "stale", headline: "部分视频需要更新", reasons: ["上游分镜图或生成参数已经改变。"] }
        : videoState.total && videoState.complete === videoState.total
          ? { stage: "video", state: "complete", headline: `本集 ${videoState.total} 条视频已就绪`, reasons: [], action: { label: "进入剪辑", stage: "editor" } }
          : imageState.complete < imageState.total
            ? { stage: "video", state: "blocked", headline: "先完成所需分镜图", reasons: [`当前分镜图完成 ${imageState.complete}/${imageState.total}。`], action: { label: "前往分镜图", stage: "images" } }
            : { stage: "video", state: "ready", headline: `可生成 ${videoState.total - videoState.complete} 条镜头视频`, reasons: [] },
    editor: timelineReady
      ? { stage: "editor", state: "ready", headline: "时间线已有内容，可以预览或导出", reasons: [] }
      : { stage: "editor", state: "unstarted", headline: "把生成的视频加入时间线", reasons: ["剪辑页始终可进入；导出前需要有效时间线。"] },
  };
  const directScript=currentScript?.metadata?.adaptationLinked===false ||
    (document.creationMode==='direct'&&currentScript?.metadata?.adaptationLinked!==true);
  if(directScript){
    if(!sourceEventCount)stages.source={stage:'source',state:'skipped',headline:'直接创作：原著资料可选',reasons:['需要改编时仍可使用原著资料库。']};
    if(adaptationStatus!=='approved')stages.adaptation={stage:'adaptation',state:'skipped',headline:'直接创作无需改编规划',reasons:['保留原著改编入口，不把未审核规划视为已批准。']};
    stages.script={stage:'script',state:currentScript?.status==='approved'?'complete':currentScript?.status==='review'?'review':currentScript?.status==='stale'?'stale':'ready',
      headline:currentScript?.status==='approved'?'本集剧本已批准':'编写、保存并审核本集剧本',reasons:['正式正文与画布共用一份；批准后进入分镜规划。']};
  }
  const order: WorkflowStage[] = ["source", "adaptation", "script", "storyboard", "art", "images", "video", "editor"];
  const recommendedStage = order.find((stage) => !["complete","skipped"].includes(stages[stage]?.state || "")) || "editor";
  return { stages, recommendedStage };
}
