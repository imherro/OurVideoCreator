import { Fragment, type ReactNode, useEffect, useRef } from "react";
import type { WorkflowStage } from "./workflow";
import { primaryWorkflowStages } from "./workflow";
import './workflowOptional.css';

export function WorkflowStageNav({
  active,
  onChange,
  states = {},
  episodeControl,
  directCreation=false,
}: {
  active: WorkflowStage;
  onChange: (stage: WorkflowStage) => void;
  states?: Partial<Record<WorkflowStage, string>>;
  episodeControl?: ReactNode;
  directCreation?: boolean;
}) {
  const activeButtonRef = useRef<HTMLButtonElement>(null);
  const optionalRef=useRef<HTMLSelectElement>(null);

  useEffect(() => {
    const target=directCreation&&(active==='source'||active==='adaptation')?optionalRef.current:activeButtonRef.current;
    target?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [active,directCreation]);

  return (
    <nav className="workflow-stage-nav" aria-label="制作流程">
      {directCreation&&<label className="workflow-optional-source"><small>可选</small>
        <select ref={optionalRef} aria-label="原著改编（可选）" value={active==='source'||active==='adaptation'?active:''}
          onChange={event=>{const value=event.target.value;if(value==='source'||value==='adaptation')onChange(value);}}>
          <option value="" disabled>原著改编</option><option value="source">原著资料</option><option value="adaptation">改编策划</option>
        </select></label>}
      {primaryWorkflowStages(directCreation).map((stage) => <Fragment key={stage.id}>
        {stage.id === "storyboard" && episodeControl && <div className="workflow-episode-boundary">{episodeControl}</div>}
        <button
          ref={active === stage.id ? activeButtonRef : undefined}
          className={`${active === stage.id ? "active" : ""} workflow-nav-${stage.group}`}
          aria-current={active === stage.id ? "page" : undefined}
          title={stage.description}
          onClick={() => onChange(stage.id)}
        >
          <small>{stage.step ? String(stage.step).padStart(2, "0") : stage.id === "canvas" ? "ADV" : ""}</small>
          <span>{stage.label}</span>
          {states[stage.id] && <i className={`workflow-nav-state ${states[stage.id]}`} aria-label={states[stage.id]} />}
        </button>
      </Fragment>)}
    </nav>
  );
}
