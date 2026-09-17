export const WORKFLOW_STAGES = [
  { id: "overview", label: "概览", description: "项目进度与下一步", group: "overview", step: null },
  { id: "source", label: "原著", description: "原始文本与素材", group: "planning", step: 1 },
  { id: "adaptation", label: "改编策划", description: "改编方向与结构", group: "planning", step: 2 },
  { id: "script", label: "剧本", description: "剧本生成与修订", group: "planning", step: 3 },
  { id: "storyboard", label: "分镜规划", description: "拆解镜头并绑定视觉资产", group: "episode", step: 4 },
  { id: "art", label: "塑角造景", description: "确认本集需要的角色、场景与道具", group: "episode", step: 5 },
  { id: "images", label: "分镜图", description: "生成和审核镜头首帧", group: "episode", step: 6 },
  { id: "video", label: "视频", description: "镜头视频生成", group: "episode", step: 7 },
  { id: "editor", label: "剪辑", description: "时间线与多轨剪辑", group: "episode", step: 8 },
  { id: "canvas", label: "高级画布", description: "完整节点工作流", group: "advanced", step: null },
] as const;

export type WorkflowStage = (typeof WORKFLOW_STAGES)[number]["id"];
export function primaryWorkflowStages(directCreation=false){
  return WORKFLOW_STAGES.filter(stage=>!directCreation || (stage.id!=='source'&&stage.id!=='adaptation'));
}
export type WorkflowScope = "production" | "episode";

const productionStages = new Set<WorkflowStage>(["overview", "source", "adaptation", "script"]);

export function workflowStageScope(stage: WorkflowStage): WorkflowScope {
  return productionStages.has(stage) ? "production" : "episode";
}

const stageIds = new Set<string>(WORKFLOW_STAGES.map((stage) => stage.id));

export function parseWorkflowStage(search: string): WorkflowStage {
  const candidate = new URLSearchParams(search).get("stage") || "overview";
  return stageIds.has(candidate) ? (candidate as WorkflowStage) : "overview";
}

export function workflowStageUrl(href: string, stage: WorkflowStage) {
  const url = new URL(href);
  url.searchParams.set("stage", stage);
  return `${url.pathname}${url.search}${url.hash}`;
}

export function defaultViewForStage(stage: WorkflowStage) {
  if (stage === "storyboard") return "shots";
  if (stage === "images") return "grid";
  if (stage === "editor") return "editor";
  if (["overview", "source", "adaptation", "script", "art", "video"].includes(stage)) return "stage";
  return "canvas";
}
