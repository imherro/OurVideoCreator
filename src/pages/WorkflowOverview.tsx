import {
  BookOpenText,
  Clapperboard,
  Film,
  Images,
  ListChecks,
  Workflow,
} from "lucide-react";
import type { WorkflowStage } from "../app/workflow";
import type { WorkflowGuide } from "../app/workflowGuide";
import type { ReactNode } from 'react';

type OverviewProps = {
  businessInbox?: ReactNode;
  projectName: string;
  duration: number;
  ratio: string;
  style: string;
  scriptCount: number;
  visualCount: number;
  shotCount: number;
  videoCount: number;
  activeJobs: number;
  guide: WorkflowGuide;
  onOpenStage: (stage: WorkflowStage) => void;
};

export function WorkflowOverview(props: OverviewProps) {
  const cards = [
    { label: "剧本", value: props.scriptCount, suffix: "份", icon: BookOpenText, stage: "script" },
    { label: "视觉资产", value: props.visualCount, suffix: "项", icon: Images, stage: "art" },
    { label: "分镜", value: props.shotCount, suffix: "镜", icon: Clapperboard, stage: "storyboard" },
    { label: "视频", value: props.videoCount, suffix: "条", icon: Film, stage: "video" },
  ] as const;
  const nextStage = props.guide.recommendedStage;
  const next = props.guide.stages[nextStage];

  return (
    <section className="workflow-overview">
      <div className="workflow-hero">
        <div>
          <span className="eyebrow">PRODUCTION WORKFLOW</span>
          <h1>{props.projectName}</h1>
          <p>{props.ratio} · {props.style} · 目标 {props.duration} 秒</p>
        </div>
        {!props.businessInbox&&<button className="primary" onClick={() => props.onOpenStage(nextStage)}>
          <ListChecks size={17} />继续制作
        </button>}
      </div>
      <div className="workflow-metrics">
        {cards.map(({ label, value, suffix, icon: Icon, stage }) => (
          <button key={stage} onClick={() => props.onOpenStage(stage)}>
            <Icon />
            <span>{label}</span>
            <strong>{value}<small>{suffix}</small></strong>
          </button>
        ))}
      </div>
      {props.businessInbox}
      <div className="workflow-overview-grid">
        {!props.businessInbox&&<article>
          <span className="eyebrow">NEXT STEP</span>
          <h2>{next?.headline || "继续制作"}</h2>
          <p>{next?.reasons[0] || "系统根据正式数据、任务状态和过期标记判断下一步。"}</p>
          <button onClick={() => props.onOpenStage(nextStage)}>打开下一阶段</button>
        </article>}
        <article>
          <span className="eyebrow">RUNNING</span>
          <h2>{props.activeJobs ? `${props.activeJobs} 个任务执行中` : "当前没有执行中的任务"}</h2>
          <p>生成任务继续在主机运行，关闭当前页面不会中断。</p>
          {!props.businessInbox&&<button onClick={() => props.onOpenStage("canvas")}><Workflow size={15} />基于画布创作</button>}
        </article>
      </div>
    </section>
  );
}
