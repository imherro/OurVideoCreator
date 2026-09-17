import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Check, Clock, Download, LoaderCircle, RefreshCw, RotateCcw, XCircle } from "lucide-react";
import { JobProgress } from "../JobProgress";
import { jobDebugParameters, jobElapsedSeconds } from "../jobDetail";
import { filmBibleJobStages } from "../filmBibleJobProgress";

type Value = Record<string, any>;

const statusLabels: Record<string, string> = {
  queued: "排队中", running: "运行中", succeeded: "成功", failed: "失败",
  interrupted: "待恢复", cancelled: "已取消",
};
const kindLabels: Record<string, string> = {
  text: "文本", storyboard: "分镜规划", image: "图片", video: "视频", export: "成片导出",
};

function displayTime(value?: number) {
  return value ? new Date(value * 1000).toLocaleString() : "—";
}
function duration(value: number) {
  const seconds = Math.floor(Math.max(0, value));
  return seconds >= 60 ? `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒` : `${seconds} 秒`;
}

export function TaskDetailPage({ jobId, request }: { jobId: string; request: (path: string, init?: RequestInit) => Promise<any> }) {
  const [job, setJob] = useState<Value>();
  const [error, setError] = useState("");
  const [connected, setConnected] = useState(true);
  const [now, setNow] = useState(Date.now() / 1000);
  const [recovering, setRecovering] = useState(false);

  async function load() {
    try { setJob(await request(`/jobs/${jobId}`)); setError(""); }
    catch (reason: any) { setError(reason?.message || String(reason)); }
  }

  async function resume() {
    if (!job) return;
    if (!job.provider_job_id && !window.confirm("此任务没有上游任务编号，将使用已保存的提示词和模型参数重新排队，可能再次产生模型费用。是否继续？")) return;
    setRecovering(true);
    try {
      setJob(await request(`/jobs/${jobId}/resume`, { method: "POST", headers: { "Content-Type": "application/json" } }));
      setError("");
    } catch (reason: any) {
      setError(reason?.message || String(reason));
    } finally {
      setRecovering(false);
    }
  }

  useEffect(() => { void load(); }, [jobId]);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);
  useEffect(() => {
    const events = new EventSource("/api/events");
    events.onopen = () => setConnected(true);
    events.onerror = () => setConnected(false);
    events.onmessage = (event) => {
      try { const payload = JSON.parse(event.data); if (payload.type === "job" && payload.id === jobId) void load(); }
      catch { /* Ignore malformed debug events and keep the last snapshot. */ }
    };
    return () => events.close();
  }, [jobId]);
  useEffect(() => {
    if (job) document.title = `${kindLabels[job.kind] || job.kind}任务 · 安影`;
    return () => { document.title = "安影 · AI 视频工作室"; };
  }, [job?.kind]);

  const parameters = useMemo(() => jobDebugParameters(job?.input || {}), [job?.input]);
  const assets = job?.result?.assets || [];
  const text = typeof job?.result === "string" ? job.result : job?.result?.text;
  const promptStages = job?.input?.prompt_stages || [];
  const runtimePromptStages = job?.telemetry?.prompt_stages || [];
  const filmBibleStages = filmBibleJobStages(job || {});

  return <main className="task-detail-page">
    <header className="task-detail-header">
      <div><span className="eyebrow">TASK DEBUG VIEW</span><h1>任务详情</h1><p>{jobId}</p></div>
      <div><span className={`live-indicator ${connected ? "connected" : "disconnected"}`}>{connected ? "实时监控中" : "连接中断，正在重连"}</span><button className="quiet" onClick={() => void load()}><RefreshCw size={15}/>刷新</button><button onClick={() => window.close()}><ArrowLeft size={15}/>关闭窗口</button></div>
    </header>
    {error && <div className="error">读取失败，保留当前内容：{error}</div>}
    {!job ? <div className="loading task-detail-loading"><LoaderCircle className="spin"/>正在读取任务</div> : <>
      <section className="task-detail-summary">
        <div><small>状态</small>{job.status === "interrupted"
          ? <button className="job-state interrupted task-resume-state" disabled={recovering} title={job.provider_job_id ? "继续查询原上游任务" : "使用已保存的输入重新排队"} onClick={() => void resume()}><RotateCcw className={recovering ? "spin" : ""}/>{recovering ? "恢复中" : statusLabels[job.status]}</button>
          : <strong className={job.status}>{job.status === "succeeded" ? <Check/> : job.status === "failed" ? <XCircle/> : <Clock/>}{statusLabels[job.status] || job.status}</strong>}</div>
        <div><small>类型</small><strong>{kindLabels[job.kind] || job.kind}</strong></div>
        <div><small>当前阶段</small><strong>{job.phase || "等待处理"}</strong></div>
        <div><small>已用时间</small><strong>{duration(jobElapsedSeconds(job, now))}</strong></div>
      </section>
      <section className="task-detail-card">
        <h2>运行状态</h2><JobProgress job={job}/>
        {!!filmBibleStages.length && <div className="film-bible-task-progress">
          <div className="film-bible-task-heading"><b>Film Bible 分镜流程</b><span>最近更新于 {duration(now - Number(job.updated || now))}前</span></div>
          <div className="film-bible-task-stages">{filmBibleStages.map((stage) => <article className={stage.status} key={stage.id}>
            <span>{stage.status === "succeeded" ? "已完成" : stage.status === "running" ? "进行中" : stage.status === "failed" ? "失败" : "等待中"}</span>
            <b>{stage.label}</b><p>{stage.detail}</p>{stage.validationError && <p className="stage-validation-error">校验原因：{stage.validationError}</p>}<small>尝试 {stage.attempts} 次</small>
          </article>)}</div>
          {job.status === "running" && <p className="film-bible-live-note">{now - Number(job.updated || 0) < 15 ? "任务仍在持续更新，没有失联。" : "超过 15 秒没有状态更新，可能正在等待模型首个输出；可继续观察。"}</p>}
        </div>}
        <dl className="task-detail-times"><div><dt>创建</dt><dd>{displayTime(job.created)}</dd></div><div><dt>开始</dt><dd>{displayTime(job.started)}</dd></div><div><dt>更新</dt><dd>{displayTime(job.updated)}</dd></div><div><dt>完成</dt><dd>{displayTime(job.finished)}</dd></div><div><dt>任务范围</dt><dd>{job.scope === "production" ? "整部作品" : "单集制作"}</dd></div><div><dt>节点</dt><dd>{job.node_id}</dd></div><div><dt>远程任务 ID</dt><dd>{job.provider_job_id || "—"}</dd></div></dl>
        {job.error && <div className="error"><b>错误信息</b><pre>{job.error}</pre></div>}
      </section>
      <section className="task-detail-card">
        <h2>模型请求契约</h2>
        <p className="muted">{job.input?.prompt_contract_origin === "migration" ? "旧任务按当前兼容版本补齐的提示词契约。" : "任务创建时冻结的完整提示词契约；Worker 执行时读取同一份快照。"}</p>
        {["image", "video"].includes(job.kind) && <p className="muted">图片和视频服务通常只有一个 Prompt 通道；这里的 System Prompt 记录安影的生成规则，User Prompt 是实际镜头描述，参考图与其他参数在下方单独列出。</p>}
        {promptStages.length ? promptStages.map((stage: Value) => {
          const runtime = [...runtimePromptStages].reverse().find((item: Value) => item.id === stage.id || item.id === `${stage.id}_repair`);
          return <article className="prompt-stage" key={stage.id}>
            <h3>{stage.label} · {stage.schema_version}</h3>
            <h4>System Prompt</h4><pre className="debug-block">{runtime?.system_prompt || stage.system_prompt}</pre>
            <h4>{runtime?.user_prompt || stage.user_prompt ? "User Prompt" : "User Prompt Template"}</h4><pre className="debug-block">{runtime?.user_prompt || stage.user_prompt || stage.user_prompt_template}</pre>
            <h4>Output Schema</h4><pre className="debug-block">{JSON.stringify(runtime?.response_schema || stage.response_schema, null, 2)}</pre>
          </article>;
        }) : <>
          <h3>System Prompt</h3><pre className="debug-block">{job.input?.system_prompt || "此任务没有独立的 System Prompt"}</pre>
          <h3>User Prompt</h3><pre className="debug-block">{job.input?.prompt || "未记录"}</pre>
          <h3>Output Schema · {job.input?.schema_version || "无版本"}</h3><pre className="debug-block">{job.input?.response_schema ? JSON.stringify(job.input.response_schema, null, 2) : "此任务没有结构化输出 Schema"}</pre>
        </>}
        {job.kind==='image'&&job.input?.image_spec&&<section><h3>图片提交规格（任务创建时冻结）</h3>
          <p>{job.input.image_spec.ratio} · {job.input.image_spec.size||'平台未发布像素尺寸'} · {job.input.image_spec.seedSupported
            ? `实际种子：${job.input.image_spec.seed??'未记录'}`:'供应商控制随机性'}</p>
          <p className="muted">{job.input.image_spec.sizeNote} 下方原始请求可能包含旧默认值；执行以此处冻结参数为准。</p>
          <pre className="debug-block">{JSON.stringify(job.input.image_spec.parameters,null,2)}</pre></section>}
        <h3>请求参数</h3><pre className="debug-block">{JSON.stringify(parameters, null, 2)}</pre>
      </section>
      <section className="task-detail-card">
        <h2>返回结果</h2>
        {text && <pre className="debug-block result-text">{text}</pre>}
        {!!assets.length && <div className="task-result-assets">{assets.map((asset: Value) => <article key={asset.id || asset.url}>
          {asset.kind === "video" ? <video src={asset.url} controls preload="metadata"/> : asset.kind === "audio" ? <audio src={asset.url} controls/> : <img src={asset.url} alt={asset.name || "生成结果"}/>}<a href={asset.url} download={asset.name}><Download size={14}/>{asset.name || "下载结果"}</a>
        </article>)}</div>}
        {!text && !assets.length && <pre className="debug-block">{job.result ? JSON.stringify(job.result, null, 2) : "尚未返回结果"}</pre>}
      </section>
    </>}
  </main>;
}
