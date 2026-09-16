import { useEffect, useMemo, useState } from "react";
import { AlertCircle, ArrowUpRight, CheckSquare2, Film, Image as ImageIcon, Play, RefreshCw, Scissors } from "lucide-react";
import { deriveVideoProductionRows, videoSubmissionSummary, type VideoProductionStatus } from "../videoProduction.ts";
import { compileVideoPrompt } from "../videoDialogue.ts";

type Value = Record<string, any>;
type Asset = { id: string; name: string; kind: string; url: string; metadata: Value; category: string; source: string };
type Props = {
  document: Value;
  assets: Asset[];
  jobs: Value[];
  providers: Value[];
  busy: boolean;
  request: (path: string) => Promise<any>;
  onPatchShot: (uid: string, patch: Value) => void;
  onPatchVideoNode: (nodeId: string, patch: Value) => void;
  onGenerate: (uids: string[]) => Promise<void>;
  onOpenCanvas: (nodeId: string) => void;
  onOpenEditor: () => void;
  onPreview: (asset: Asset) => void;
};

const statusLabels: Record<VideoProductionStatus, string> = {
  ready: "待生成", generating: "生成中", failed: "失败", stale: "待更新", complete: "已完成", blocked: "条件未满足",
};
const jobLabels: Record<string, string> = { queued: "排队中", running: "生成中", interrupted: "等待恢复", failed: "失败", succeeded: "已完成" };

export function VideoProductionWorkspace(props: Props) {
  const [catalogCapabilities, setCatalogCapabilities] = useState<Record<string, Value>>({});
  const arkProviderIds = useMemo(() => {
    const providerMap = new Map(props.providers.map((provider) => [provider.id, provider]));
    const ids = new Set<string>();
    for (const shot of props.document.shots || []) {
      const nodeId = shot.videoNode || shot.pipeline?.videoNodeId;
      const node = (props.document.nodes || []).find((item: Value) => item.id === nodeId);
      const provider = providerMap.get(node?.data?.provider);
      if (provider && ["volcengine_ark", "runninghub"].includes(provider.type)) ids.add(provider.id);
    }
    return [...ids].sort();
  }, [props.document.shots, props.document.nodes, props.providers]);
  useEffect(() => {
    let active = true;
    if (!arkProviderIds.length) {
      setCatalogCapabilities({});
      return () => { active = false; };
    }
    void Promise.all(arkProviderIds.map(async (providerId) => {
      const value = await props.request("/providers/" + encodeURIComponent(providerId) + "/models?kind=video");
      return (value.models || []).map((model: Value) => [
        [providerId, String(model.id || "")].join("\u0000"),
        model.capabilities || {},
      ]);
    })).then((groups) => {
      if (active) setCatalogCapabilities(Object.fromEntries(groups.flat()));
    }).catch(() => {
      if (active) setCatalogCapabilities({});
    });
    return () => { active = false; };
  }, [arkProviderIds.join("|"), props.request]);
  const rows = useMemo(
    () => deriveVideoProductionRows(props.document, props.assets, props.jobs, props.providers, catalogCapabilities),
    [props.document, props.assets, props.jobs, props.providers, catalogCapabilities],
  );
  const [filter, setFilter] = useState<"all" | VideoProductionStatus>("all");
  const [selected, setSelected] = useState<string[]>([]);
  const [reviewing, setReviewing] = useState(false);
  const [error, setError] = useState("");
  const identities = rows.map((row) => row.uid);
  useEffect(() => setSelected((items) => items.filter((item) => identities.includes(item))), [identities.join("|")]);
  useEffect(() => setReviewing(false), [selected.join("|")]);
  const visible = filter === "all" ? rows : rows.filter((row) => row.status === filter);
  const summary = videoSubmissionSummary(rows, selected);
  const selectedRows = rows.filter((row) => selected.includes(row.uid));
  const submissionBlockers = selectedRows.filter((row) => row.readinessReason || row.status === "generating");
  const toggle = (uid: string) => setSelected((items) => items.includes(uid) ? items.filter((item) => item !== uid) : [...items, uid]);
  const submit = async (uids: string[]) => {
    setError("");
    try { await props.onGenerate(uids); setReviewing(false); }
    catch (reason: any) { setError(reason?.message || String(reason)); }
  };
  return <section className="video-production-workspace">
    <header className="video-production-header">
      <div><span className="eyebrow">VIDEO PRODUCTION WORKSPACE</span><h2>视频工作区</h2><p>从已核验分镜首帧生成逐镜视频；旧结果会保留，变更后标记为待更新。</p></div>
      <div className="video-production-header-actions"><button className="primary compact" onClick={props.onOpenEditor}><Scissors size={15}/>进入剪辑</button><div className="video-status-filters" aria-label="视频状态筛选">
        {(["all","ready","generating","failed","stale","complete"] as const).map((value) => <button key={value} className={filter === value ? "active" : ""} onClick={() => setFilter(value)}>{value === "all" ? "全部" : statusLabels[value]} <b>{value === "all" ? rows.length : rows.filter((row) => row.status === value).length}</b></button>)}
      </div></div>
    </header>
    {!!rows.length && <div className="video-selection-bar">
      <label className="check-label"><input type="checkbox" checked={selected.length === rows.length} onChange={(event) => setSelected(event.target.checked ? identities : [])}/>全选 {rows.length} 镜</label>
      <span>已选 {selected.length} 镜</span>
      <button className="primary compact" disabled={props.busy || !selected.length} onClick={() => setReviewing(true)}><Film size={15}/>生成所选视频</button>
    </div>}
    {reviewing && <div className="video-submit-review" role="dialog" aria-label="批量生成确认">
      <div><CheckSquare2 size={20}/><div><b>提交前复核</b><p>将提交 {summary.count} 个明确选中的视频任务{summary.cloudCount ? `，其中 ${summary.cloudCount} 个使用云端服务` : ""}。</p></div></div>
      <ul>{summary.groups.map((group) => <li key={`${group.providerId}:${group.modelId}`}><span>{group.cloud ? "公网 API" : "直连 API"}</span><b>{group.providerName}</b><code>{group.modelId}</code><em>× {group.count}</em></li>)}</ul>
      {!!submissionBlockers.length && <p className="error"><AlertCircle size={15}/>有 {submissionBlockers.length} 个所选镜头暂不可提交：{submissionBlockers.slice(0,2).map((row) => `SHOT ${String(row.index+1).padStart(2,"0")} ${row.status === "generating" ? "任务已在队列中" : row.readinessReason}`).join("；")}</p>}
      <div className="settings-actions"><button onClick={() => setReviewing(false)}>取消</button><button className="primary" disabled={props.busy || !!submissionBlockers.length} onClick={() => void submit(selected)}>确认提交 {summary.count} 个任务</button></div>
    </div>}
    {error && <p className="error"><AlertCircle size={15}/>{error}</p>}
    {!rows.length ? <div className="empty-state"><Film/><h3>还没有可生产的视频镜头</h3><p>请先在分镜工作区创建镜头并生成首帧。</p></div> : !visible.length ? <div className="empty-state"><Film/><h3>当前筛选没有镜头</h3></div> : <div className="video-production-list">{visible.map((row) => {
      const data = row.videoNode?.data || {};
      const providers = props.providers.filter((item) => item.kind === "video" || !item.kind);
      const canGenerate = !row.readinessReason && row.status !== "generating";
      return <article key={row.uid} className={`video-production-card ${selected.includes(row.uid) ? "selected" : ""}`}>
        <header><label className="check-label"><input type="checkbox" checked={selected.includes(row.uid)} onChange={() => toggle(row.uid)}/><strong>{String(row.index + 1).padStart(2,"0")}</strong><span>SHOT</span></label><b>{row.shot.scene || "未命名场景"}</b><span className={`video-production-state ${row.status}`}>{statusLabels[row.status]}</span></header>
        <div className="video-production-main">
          <div className="video-frame-column"><small>FIRST FRAME</small><button className="video-frame-preview" disabled={!row.firstFrame} onClick={() => row.firstFrame && props.onPreview(row.firstFrame as Asset)}>{row.firstFrame ? <img src={row.firstFrame.url} alt="首帧"/> : <span><ImageIcon/>缺少首帧</span>}</button>{row.imageNode?.data?.stale && <em>首帧已过期</em>}{row.readinessReason && <p>{row.readinessReason}</p>}</div>
          {row.endFrameSupported && <div className="video-frame-column"><small>END FRAME · 可选</small><button className="video-frame-preview" disabled={!row.endFrame} onClick={() => row.endFrame && props.onPreview(row.endFrame as Asset)}>{row.endFrame ? <img src={row.endFrame.url} alt="尾帧"/> : <span><ImageIcon/>未设置尾帧</span>}</button><select aria-label="尾帧素材" value={data.end_asset_id || ""} onChange={(event) => props.onPatchVideoNode(row.videoNode!.id,{end_asset_id:event.target.value})}><option value="">不使用尾帧</option>{props.assets.filter((asset) => asset.kind === "image").map((asset) => <option key={asset.id} value={asset.id}>{asset.name}</option>)}</select></div>}
          <div className="video-production-fields">
            <label>Video Prompt<textarea value={row.shot.video_prompt || ""} onChange={(event) => props.onPatchShot(row.uid,{video_prompt:event.target.value})}/></label>
          <div className="video-dialogue-projection" aria-label="实际发送给视频模型"><header><b>实际发送给视频模型</b><small>{row.shot.dialogues?.length ? `已自动加入 ${row.shot.dialogues.length} 条对白` : "本镜无结构化对白"}</small></header><pre>{compileVideoPrompt(row.shot.video_prompt,row.shot,row.submissionDuration)}</pre>{row.submissionDuration !== row.plannedDuration && <small>分镜计划 {row.plannedDuration} 秒；结合项目策略、对白长度和模型限制，实际提交 {row.submissionDuration} 秒。</small>}{row.shot.dialogues?.length > 0 && ["volcengine_ark", "runninghub"].includes(row.provider?.type) && <small>{row.dialogueAudioAssets.length === row.shot.dialogues.length ? `固定音色对白已就绪 ${row.dialogueAudioAssets.length}/${row.shot.dialogues.length}；将作为 Seedance 2.5 音频参考提交。` : "请先在塑角造景生成当前音色版本的本镜对白。"}</small>}</div>
            <div className="domain-fields three"><label>时长（秒）<input type="number" min="0.1" step="0.1" value={row.shot.duration ?? 3} onChange={(event) => props.onPatchShot(row.uid,{duration:Number(event.target.value)})}/></label><label>Provider<select value={data.provider || ""} onChange={(event) => { const provider=props.providers.find((item)=>item.id===event.target.value); props.onPatchVideoNode(row.videoNode!.id,{provider:event.target.value,model:provider?.models?.video||provider?.model||"",model_capabilities:undefined,end_asset_id:provider?.type==="minimax"?"":data.end_asset_id}); }}><option value="" disabled>请选择外部 Provider</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>外部 API · {provider.name}</option>)}</select></label><label>Model<input value={data.model || ""} onChange={(event) => props.onPatchVideoNode(row.videoNode!.id,{model:event.target.value,model_capabilities:undefined})}/></label></div>
            <div className="video-shot-context"><span>{row.shot.action || "未填写镜头动作"}</span><small>{row.shot.camera || "未设置机位"} · 分镜 {row.plannedDuration || 0} 秒 · 提交 {row.submissionDuration || 0} 秒</small></div>
          </div>
          <div className="video-result-column"><small>GENERATED VIDEO</small><button className="video-result-preview" disabled={!row.videoAsset} onClick={() => row.videoAsset && props.onPreview(row.videoAsset as Asset)}>{row.videoAsset ? <video src={row.videoAsset.url} muted preload="metadata"/> : <span><Film/>等待视频</span>}</button>{row.job && <div className="video-job-state"><span>{jobLabels[row.job.status] || row.job.status}</span>{row.job.progress != null && <b>{Math.round(row.job.progress)}%</b>}<small>{row.job.phase}</small></div>}</div>
        </div>
        <footer>{row.status === "stale" && <span className="danger">依赖已变化，旧视频仍保留</span>}<div/><button disabled={props.busy || !canGenerate} onClick={() => void submit([row.uid])}>{row.videoAsset ? <><RefreshCw size={14}/>重新生成</> : <><Play size={14}/>开始生成</>}</button>{row.videoAsset && <button onClick={() => props.onPreview(row.videoAsset as Asset)}>预览</button>}{row.videoNode && <button className="quiet" onClick={() => props.onOpenCanvas(row.videoNode!.id)}>高级画布<ArrowUpRight size={13}/></button>}</footer>
      </article>;
    })}</div>}
  </section>;
}
