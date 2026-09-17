import { useEffect, useMemo, useState } from "react";
import type {ReactNode} from 'react';
import {
  ArrowDown,
  ArrowUp,
  ArrowUpRight,
  CheckSquare2,
  Download,
  Image as ImageIcon,
  Layers,
  Plus,
  Sparkles,
  Unlink,
} from "lucide-react";
import { projectShotReferences, shotIdentity } from "../storyboard";
import { visualBibleOf, visualKindLabels, type FilmBibleDocument } from "../filmBible/types";

type Value = Record<string, any>;
type PreviewAsset = {
  id: string;
  name: string;
  kind: string;
  url: string;
  metadata: Value;
  category: string;
  source: string;
};

type Props = {
  purpose: "planning" | "images";
  mode: "table" | "grid";
  document: FilmBibleDocument;
  assets: PreviewAsset[];
  jobs: Value[];
  busy: boolean;
  renderImageSettings?: (node: Value) => ReactNode;
  onPatch: (uid: string, patch: Value) => void;
  onMove: (uid: string, offset: -1 | 1) => void;
  onCreate: () => void;
  onCreatePlan: () => void;
  onEnsureAll: () => void;
  onAppendTimeline: () => void;
  onBind: (uid: string, versionId: string) => void;
  onUnbind: (uid: string, versionId: string) => void;
  onUpgrade: (uid: string, cardId: string, versionId: string) => void;
  onGenerate: (uids: string[]) => Promise<void>;
  onOpenCanvas: (shot: Value, index: number) => void;
  onOpenVideo: () => void;
  onPreview: (asset: PreviewAsset) => void;
  onExport: (columns: number, page: number) => Promise<void>;
};

const statusLabel: Record<string, string> = {
  queued: "排队中",
  running: "生成中",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "待恢复",
};

function stringList(value: unknown) {
  return Array.isArray(value) ? value.join("、") : String(value || "");
}

function latestJob(jobs: Value[], nodeId?: string) {
  return jobs
    .filter((item) => item.node_id === nodeId)
    .sort((left, right) => Number(right.created || 0) - Number(left.created || 0))[0];
}

export function StoryboardWorkspace(props: Props) {
  const shots = props.document.shots || [];
  const visual = visualBibleOf(props.document);
  const [selected, setSelected] = useState<string[]>([]);
  const [columns, setColumns] = useState(3);
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const identities = shots.map(shotIdentity);
  useEffect(() => {
    setSelected((items) => items.filter((item) => identities.includes(item)));
  }, [identities.join("|")]);

  const availableVersions = useMemo(() =>
    Object.values(visual.versions)
      .filter((version) => {
        const card = visual.cards[version.cardId];
        return card && !card.deletedAt && card.status !== "deprecated" && version.status !== "deprecated";
      })
      .sort((left, right) => {
        const a = visual.cards[left.cardId];
        const b = visual.cards[right.cardId];
        return `${a.kind}-${a.name}-${left.version}`.localeCompare(`${b.kind}-${b.name}-${right.version}`, "zh-CN");
      }), [visual]);
  const pages = Math.max(1, Math.ceil(shots.length / 9));
  const currentPage = Math.min(page, pages);
  const pageShots = shots.slice((currentPage - 1) * 9, currentPage * 9);
  const planningActive = props.jobs.some((job) =>
    job.kind === "storyboard" && ["queued", "running"].includes(job.status),
  );
  const referenceAsset = (assetId?: string) => props.assets.find((item) => item.id === assetId);
  const referenceChip = (item: ReturnType<typeof projectShotReferences>[number]) => {
    const reference = referenceAsset(item.primaryAssetId);
    return <span className="storyboard-reference-chip" key={`${item.group}:${item.versionId}`}>
      {reference ? <img src={reference.url} alt={item.cardName}/> : <span className="reference-placeholder"><ImageIcon size={14}/></span>}
      <span><b>{item.cardName}</b><small>{visualKindLabels[item.kind]} · V{item.version}</small></span>
    </span>;
  };

  const toggle = (uid: string) => setSelected((items) =>
    items.includes(uid) ? items.filter((item) => item !== uid) : [...items, uid]);
  const generate = async (uids: string[]) => {
    setError("");
    try { await props.onGenerate(uids); }
    catch (reason: any) { setError(reason?.message || String(reason)); }
  };

  const header = <>
    <div className="storyboard-workspace-header">
      <div><span className="eyebrow">{props.purpose === "planning" ? "SHOT PLANNING" : "STORYBOARD IMAGES"}</span><h2>{props.purpose === "planning" ? "分镜规划" : "分镜图"}</h2><p>{props.purpose === "planning" ? "拆解镜头、编辑提示词并绑定视觉版本。" : "这里生成视频首帧；尾帧请进入“视频”页，在对应镜头的 END FRAME 中选择图片。"}</p></div>
      <div className="settings-actions">
        {props.purpose === "planning" && <button onClick={props.onCreate}><Plus size={15}/>新建镜头</button>}
        {props.purpose === "planning" && <button className="primary" disabled={props.busy || planningActive} onClick={props.onCreatePlan}><Sparkles size={15}/>{planningActive ? "分镜规划进行中" : shots.length ? "重新生成规划" : "从剧本生成规划"}</button>}
        {props.purpose === "images" && !!shots.length && <button onClick={props.onEnsureAll}><Layers size={15}/>补齐生成节点</button>}
        {props.purpose === "images" && !!shots.length && <button onClick={props.onOpenVideo}>设置首尾帧<ArrowUpRight size={14}/></button>}
      </div>
    </div>
    {props.purpose === "images" && !!shots.length && <div className="storyboard-selection-bar">
      <label className="check-label"><input type="checkbox" checked={selected.length === shots.length} onChange={(event) => setSelected(event.target.checked ? identities : [])}/>全选 {shots.length} 镜</label>
      <span>已选 {selected.length} 镜</span>
      <button className="primary compact" disabled={props.busy || !selected.length} onClick={() => void generate(selected)}><ImageIcon size={15}/>生成所选分镜图</button>
    </div>}
    {error && <p className="error">{error}</p>}
  </>;

  if (!shots.length) return <section className="storyboard-workspace">{header}<div className="empty-state"><Layers/><h3>还没有分镜</h3><p>{props.purpose === "planning" ? "从已批准的正式剧本生成分镜规划，也可以手工新建镜头。" : "请先到“分镜规划”建立本集镜头。"}</p>{props.purpose === "planning" && <button className="primary" disabled={props.busy || planningActive} onClick={props.onCreatePlan}>{planningActive ? "分镜规划进行中" : "开始分镜规划"}</button>}</div></section>;

  if (props.mode === "grid") return <section className="storyboard-workspace">{header}
    <div className="storyboard-grid-toolbar"><label>布局<select value={columns} onChange={(event) => setColumns(Number(event.target.value))}><option value="3">三列宫格</option><option value="2">两列图板</option></select></label><button onClick={() => void props.onExport(columns, currentPage)}><Download size={15}/>下载当前页 PNG</button></div>
    <div className="storyboard-grid" style={{gridTemplateColumns:`repeat(${columns},minmax(0,1fr))`}}>{pageShots.map((shot, offset) => {
      const index = (currentPage - 1) * 9 + offset;
      const uid = shotIdentity(shot);
      const imageNodeId = shot.imageNode || shot.pipeline?.imageNodeId;
      const node = props.document.nodes.find((item: Value) => item.id === imageNodeId);
      const asset = props.assets.find((item) => item.id === node?.data?.assetId);
      const job = latestJob(props.jobs, imageNodeId);
      const references = projectShotReferences(props.document, shot);
      const state = node?.data?.stale ? "待更新" : asset ? "已完成" : statusLabel[job?.status] || "待生成";
      return <article key={uid} className={`storyboard-tile ${selected.includes(uid) ? "selected" : ""}`}>
        <button className="storyboard-picture" onClick={() => asset ? props.onPreview(asset) : void generate([uid])}>{asset ? <img src={asset.url} alt={shot.scene || `镜头 ${index + 1}`}/> : <span><ImageIcon/>等待分镜图</span>}<em>{state}</em></button>
        <div><label className="check-label"><input type="checkbox" checked={selected.includes(uid)} onChange={() => toggle(uid)}/>SHOT {String(index + 1).padStart(2,"0")} · {shot.duration || 0} 秒</label><b>{shot.scene || "未命名场景"}</b><p>{shot.action || "尚未填写动作"}</p><small>{shot.camera || "未设置机位"}</small><div className="storyboard-grid-refs">{references.map(referenceChip)}</div><div className="storyboard-grid-actions"><button onClick={() => void generate([uid])}>{asset ? "重新生成" : "生成分镜图"}</button><button className="quiet" onClick={() => props.onOpenCanvas(shot,index)}>高级画布<ArrowUpRight size={13}/></button></div></div>
        {props.purpose==='images'&&node&&props.renderImageSettings?.(node)}
      </article>;
    })}</div>
    {pages > 1 && <div className="settings-actions"><button disabled={currentPage===1} onClick={() => setPage(currentPage-1)}>上一页</button><span>{currentPage} / {pages}</span><button disabled={currentPage===pages} onClick={() => setPage(currentPage+1)}>下一页</button></div>}
  </section>;

  return <section className="storyboard-workspace">{header}<div className="storyboard-table">{shots.map((shot, index) => {
    const uid = shotIdentity(shot);
    const imageNodeId = shot.imageNode || shot.pipeline?.imageNodeId;
    const node = props.document.nodes.find((item: Value) => item.id === imageNodeId);
    const asset = props.assets.find((item) => item.id === node?.data?.assetId);
    const job = latestJob(props.jobs, imageNodeId);
    const references = projectShotReferences(props.document, shot);
    const imageState = node?.data?.stale ? "待更新" : asset ? "已完成" : statusLabel[job?.status] || "待生成";
    return <article key={uid} className={selected.includes(uid) ? "selected" : ""}>
      <header><label className="check-label">{props.purpose === "images" && <input type="checkbox" checked={selected.includes(uid)} onChange={() => toggle(uid)}/>}<strong>{String(index+1).padStart(2,"0")}</strong><span>SHOT</span></label><code>{uid}</code><span className={`storyboard-state ${node?.data?.stale ? "stale" : ""}`}>{props.purpose === "planning" ? shot.prompts_need_review ? "需检查" : references.length || !Object.keys(visual.cards).length ? "规划完成" : "待绑定资产" : imageState}</span><button className="icon-button" disabled={index===0} onClick={() => props.onMove(uid,-1)} title="上移"><ArrowUp size={15}/></button><button className="icon-button" disabled={index===shots.length-1} onClick={() => props.onMove(uid,1)} title="下移"><ArrowDown size={15}/></button></header>
      <div className="storyboard-table-main">
        <button className="storyboard-table-preview" onClick={() => asset ? props.onPreview(asset) : undefined}>{asset ? <img src={asset.url} alt={shot.scene || `镜头 ${index+1}`}/> : <span><ImageIcon/>等待分镜图</span>}</button>
        <div className="storyboard-shot-fields">
          <div className="domain-fields four"><label>时长（秒）<input type="number" min="0.1" step="0.1" value={shot.duration ?? 3} onChange={(event) => props.onPatch(uid,{duration:Number(event.target.value)})}/></label><label>场景<input value={shot.scene || ""} onChange={(event) => props.onPatch(uid,{scene:event.target.value})}/></label><label>角色<input value={stringList(shot.characters)} onChange={(event) => props.onPatch(uid,{characters:event.target.value.split(/[、,，]/).map((item)=>item.trim()).filter(Boolean)})}/></label><label>情绪<input value={shot.emotion || ""} onChange={(event) => props.onPatch(uid,{emotion:event.target.value})}/></label></div>
          <label>动作<textarea value={shot.action || ""} onChange={(event) => props.onPatch(uid,{action:event.target.value})}/></label>
          <div className="domain-fields"><label>机位 / Camera<input value={shot.camera || ""} onChange={(event) => props.onPatch(uid,{camera:event.target.value})}/></label><label>声音 / Audio<input value={shot.audio || ""} onChange={(event) => props.onPatch(uid,{audio:event.target.value})}/></label></div>
        </div>
      </div>
      <div className="storyboard-bindings"><div><b>VisualVersion 绑定</b><small>直接引用 Production Film Bible</small></div><div className="storyboard-reference-list">{references.map((item) => {
        const card = visual.cards[item.cardId];
        const target = visual.versions[card?.currentVersionId];
        const canUpgrade = target && target.id !== item.versionId && target.status === "locked";
        const reference = referenceAsset(item.primaryAssetId);
        return <span key={`${item.group}:${item.versionId}`} className="storyboard-binding-card">{reference ? <img src={reference.url} alt={item.cardName}/> : <span className="reference-placeholder"><ImageIcon size={15}/></span>}<span><b>{item.cardName} V{item.version}</b><small>{visualKindLabels[item.kind]} · {item.primaryAssetId ? "主参考已就绪" : "缺少主参考"}</small></span>{canUpgrade && <button onClick={() => props.onUpgrade(uid,item.cardId,target.id)}>升级到 V{target.version}</button>}<button className="icon-button" onClick={() => props.onUnbind(uid,item.versionId)} title="解除绑定"><Unlink size={13}/></button></span>;
      })}{!references.length && <small>尚未绑定角色、场景或道具版本</small>}</div><label>添加视觉版本<select value="" onChange={(event) => { if(event.target.value) props.onBind(uid,event.target.value); }}><option value="">选择 Production 视觉版本…</option>{availableVersions.map((version) => { const card=visual.cards[version.cardId]; return <option value={version.id} key={version.id}>{visualKindLabels[card.kind]} · {card.name} · V{version.version} · {version.status}</option>; })}</select></label></div>
      {props.purpose==='images'&&node&&props.renderImageSettings?.(node)}
      <details className="storyboard-prompts"><summary>生成提示词与参考编译投影</summary><div className="domain-fields"><label>Image Prompt<textarea value={shot.image_prompt || ""} onChange={(event) => props.onPatch(uid,{image_prompt:event.target.value})}/></label><label>Video Prompt<textarea value={shot.video_prompt || ""} onChange={(event) => props.onPatch(uid,{video_prompt:event.target.value})}/></label></div><div className="reference-projection"><CheckSquare2 size={15}/><span>{references.length ? references.map((item) => `${item.group}:${item.cardName} V${item.version}`).join(" → ") : "Reference Compiler 当前没有 identity reference"}</span></div></details>
      <footer>{shot.prompts_need_review && <span className="danger">镜头内容已改变，请核对提示词</span>}<div/>{props.purpose === "images" && <button onClick={() => void generate([uid])}>{asset ? "重新生成" : "生成分镜图"}</button>}{asset && <button onClick={() => props.onPreview(asset)}>查看结果</button>}{props.purpose === "images" && asset && <button onClick={props.onOpenVideo}>设置尾帧</button>}<button className="quiet" onClick={() => props.onOpenCanvas(shot,index)}>高级画布<ArrowUpRight size={14}/></button></footer>
    </article>;
  })}</div></section>;
}
