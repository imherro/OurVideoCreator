import { useEffect, useMemo, useState } from "react";
import { Check, Clock, Download, ExternalLink, LoaderCircle, RefreshCw, RotateCcw, Square, XCircle } from "lucide-react";
import { JobProgress } from "../JobProgress";
import { deriveTaskCenterRows, filterTaskCenterRows, taskShotLabel, type TaskEpisode } from "../taskCenter";
import { taskDetailHref } from "../jobDetail";
import { CandidateReview } from '../CandidateReview';

type Value = Record<string, any>;

const statusLabels: Record<string, string> = {
  queued: "排队中",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
  interrupted: "待恢复",
  cancelled: "已取消",
};

const kindLabels: Record<string, string> = {
  text: "文本",
  storyboard: "分镜规划",
  image: "图片",
  video: "视频",
  audio: "角色配音",
  export: "成片导出",
};

function StatusIcon({ status }: { status: string }) {
  if (status === "running") return <LoaderCircle className="spin" size={15} />;
  if (status === "succeeded") return <Check size={15} />;
  if (status === "failed") return <XCircle size={15} />;
  if (status === "interrupted") return <RotateCcw size={15} />;
  if (status === "cancelled") return <Square size={15} />;
  return <Clock size={15} />;
}

export function TaskCenter({
  productionName,
  episodes,
  currentProjectId,
  currentDocument,
  currentJobs,
  providers,
  request,
  onRefreshCurrent,
  onOpenNode,
  onAdoptShots,
  onAdoptCandidate,
}: {
  productionName: string;
  episodes: TaskEpisode[];
  currentProjectId: string;
  currentDocument: Value;
  currentJobs: Value[];
  providers: Value[];
  request: (path: string, init?: RequestInit) => Promise<any>;
  onRefreshCurrent: () => Promise<void>;
  onOpenNode: (projectId: string, nodeId: string) => Promise<void>;
  onAdoptShots: (job: Value) => void;
  onAdoptCandidate: (job: Value,body:Value) => Promise<void>;
}) {
  const [jobs, setJobs] = useState<Value[]>(currentJobs);
  const [documents, setDocuments] = useState<Record<string, Value>>({ [currentProjectId]: currentDocument });
  const [filters, setFilters] = useState({ episodeId: "", kind: "", status: "" });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const snapshots = await Promise.all(episodes.map(async (episode) => {
        const [episodeJobs, project] = await Promise.all([
          request(`/projects/${episode.id}/jobs`),
          request(`/projects/${episode.id}`),
        ]);
        return { episode, jobs: episodeJobs as Value[], document: project.document as Value };
      }));
      setJobs(snapshots.flatMap((snapshot) => snapshot.jobs));
      setDocuments(Object.fromEntries(snapshots.map((snapshot) => [snapshot.episode.id, snapshot.document])));
    } catch (reason: any) {
      setError(reason?.message || String(reason));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { void load(); }, [episodes.map((episode) => episode.id).join("|")]);
  useEffect(() => {
    setJobs((items) => [
      ...items.filter((job) => job.project_id !== currentProjectId),
      ...currentJobs,
    ]);
    setDocuments((items) => ({ ...items, [currentProjectId]: currentDocument }));
  }, [currentJobs, currentDocument, currentProjectId]);

  const rows = useMemo(
    () => deriveTaskCenterRows(jobs, episodes, documents, providers),
    [jobs, episodes, documents, providers],
  );
  const visible = useMemo(() => filterTaskCenterRows(rows, filters), [rows, filters]);
  const kinds = [...new Set(rows.map((row) => row.job.kind))].sort();
  const statuses = [...new Set(rows.map((row) => row.job.status))].sort();

  async function mutate(path: string) {
    try {
      setError("");
      await request(path, { method: "POST", headers: { "Content-Type": "application/json" } });
      await onRefreshCurrent();
      await load();
    } catch (reason: any) {
      setError(reason?.message || String(reason));
    }
  }

  async function resumeJob(job: Value) {
    if (!job.provider_job_id && !window.confirm("此任务没有上游任务编号，将使用已保存的提示词和模型参数重新排队，可能再次产生模型费用。是否继续？")) return;
    await mutate(`/jobs/${job.id}/resume`);
  }

  return <section className="task-center">
    <header className="task-center-header">
      <div><span className="eyebrow">TASK CENTER</span><h2>任务中心</h2><p>{productionName} · 直接读取现有生成任务，不会自动重试或产生费用。</p></div>
      <button className="quiet" disabled={loading} onClick={() => void load()}><RefreshCw className={loading ? "spin" : ""} size={15}/>刷新</button>
    </header>
    <div className="task-center-filters" aria-label="任务筛选">
      <label>任务范围<select value={filters.episodeId} onChange={(event) => setFilters((value) => ({ ...value, episodeId: event.target.value }))}><option value="">全部范围</option><option value="production">整部作品</option>{episodes.map((episode) => <option key={episode.id} value={episode.id}>EP{String(episode.episode_no).padStart(2,"0")} · {episode.episode_title || episode.name}</option>)}</select></label>
      <label>类型<select value={filters.kind} onChange={(event) => setFilters((value) => ({ ...value, kind: event.target.value }))}><option value="">全部类型</option>{kinds.map((kind) => <option key={kind} value={kind}>{kindLabels[kind] || kind}</option>)}</select></label>
      <label>状态<select value={filters.status} onChange={(event) => setFilters((value) => ({ ...value, status: event.target.value }))}><option value="">全部状态</option>{statuses.map((status) => <option key={status} value={status}>{statusLabels[status] || status}</option>)}</select></label>
      <span>{visible.length} / {rows.length} 个任务</span>
    </div>
    {error && <p className="error">刷新失败，保留上次任务列表：{error}</p>}
    <div className="task-center-list">{visible.map((row) => {
      const job = row.job;
      const canOpenNode = job.node_id && job.node_id !== "export";
      return <article className="job-card task-card" key={job.id}>
        <header>{job.status === "interrupted"
          ? <button className={`job-state ${job.status} task-resume-state`} title={job.provider_job_id ? "继续查询原上游任务" : "使用已保存的输入重新排队"} onClick={() => void resumeJob(job)}><StatusIcon status={job.status}/>{statusLabels[job.status]}</button>
          : <span className={`job-state ${job.status}`}><StatusIcon status={job.status}/>{statusLabels[job.status] || job.status}</span>}<small>{new Date(job.created * 1000).toLocaleString()}</small></header>
        <div className="task-card-title"><b>{kindLabels[job.kind] || job.kind} · {taskShotLabel(row)}</b><span>{row.scope === "production" ? `整部作品 · ${productionName}` : `EP${String(row.episode?.episode_no || 1).padStart(2,"0")} · ${row.episode?.episode_title || row.episode?.name || job.project_id}`}</span></div>
        <dl><div><dt>Provider</dt><dd>{row.providerName}</dd></div><div><dt>Model</dt><dd>{row.modelName}</dd></div><div><dt>Node</dt><dd>{job.node_id}</dd></div>{job.provider_job_id && <div><dt>上游任务</dt><dd>{job.provider_job_id}</dd></div>}</dl>
        {job.phase && <p>{job.phase}</p>}
        <JobProgress job={job}/>
        {job.error && <div className="error">{job.error}</div>}
        <CandidateReview job={job} request={request} onAdopt={async(job,body)=>{
          await onAdoptCandidate(job,body);await load();
        }}/>
        <div className="task-card-actions">
          <a className="task-detail-link" href={taskDetailHref(job.id)} target="_blank" rel="noopener noreferrer">任务详情 <ExternalLink size={13}/></a>
          {job.result?.assets?.map((asset: Value) => <a className="download-link" href={asset.url} download={asset.name} key={asset.id}><Download size={14}/>{asset.name}</a>)}
          {job.result?.shots && job.project_id === currentProjectId && <button onClick={() => onAdoptShots(job)}>导入分镜表</button>}
          {job.status === "interrupted" && <span className="muted">{job.provider_job_id ? "点击上方“待恢复”继续查询原任务。" : "点击上方“待恢复”可按原提示词重新排队。"}</span>}
          {["queued","running","interrupted"].includes(job.status) && <button onClick={() => void mutate(`/jobs/${job.id}/cancel`)}><Square size={14}/>取消任务</button>}
          {canOpenNode && <button className="quiet" onClick={() => void onOpenNode(job.project_id, job.node_id)}>查看节点</button>}
        </div>
      </article>;
    })}</div>
    {!loading && !visible.length && <div className="empty-state"><Clock/><h3>{rows.length ? "当前筛选没有任务" : "还没有生成任务"}</h3></div>}
  </section>;
}
