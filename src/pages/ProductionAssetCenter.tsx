import React, { useMemo, useState, type ReactNode } from "react";
import { BookOpen, Download, FolderOpen, Image as ImageIcon, Music, Trash2, Upload } from "lucide-react";
import { primaryReference } from "../filmBible/references";
import { visualBibleOf, visualKindLabels, type FilmBibleDocument } from "../filmBible/types";

type Any = Record<string, any>;
type Usage = { version_id: string; episodes: Any[]; shots: Any[] };

const categoryLabels: Record<string, string> = { character: "角色", scene: "场景", prop: "道具", shot: "镜头", music: "音乐", sfx: "音效", voice: "配音", reference: "参考", motion_reference:"动作参考", other: "其他" };
const kindLabels: Record<string, string> = { image: "图片", video: "视频", audio: "声音", subtitle: "字幕" };
const sourceLabels: Record<string, string> = { generated: "模型生成", uploaded: "上传", imported: "导入" };

function semanticStatus(card: Any, version: Any) {
  if (card.deletedAt || card.status === "deprecated" || version?.status === "deprecated") return "已弃用";
  if (!version?.spec?.description) return "未设计";
  if (version.status === "locked") return "已锁定";
  if (version.status === "pending_reference") return version.references?.some((item: Any) => item?.role === "primary") ? "待确认" : "待参考";
  return "草稿";
}

export function ProductionAssetCenter({
  document,
  assets,
  projects,
  currentProjectId,
  usage,
  uploadCategory,
  onUploadCategory,
  onUpload,
  onCreatePanorama,
  onOpenArt,
  onPreview,
  renderMedia,
  onCategory,
  onDelete,
  onTimeline,
  onPanorama,
  onReference,
}: {
  document: FilmBibleDocument;
  assets: Any[];
  projects: Any[];
  currentProjectId: string;
  usage: Usage[];
  uploadCategory: string;
  onUploadCategory: (value: string) => void;
  onUpload: () => void;
  onCreatePanorama: () => void;
  onOpenArt: (versionId?: string) => void;
  onPreview: (asset: Any) => void;
  renderMedia: (asset: Any) => ReactNode;
  onCategory: (asset: Any, category: string) => void;
  onDelete: (asset: Any) => void;
  onTimeline: (asset: Any) => void;
  onPanorama: (asset: Any) => void;
  onReference?: (asset: Any) => void;
}) {
  const [layer, setLayer] = useState<"semantic" | "media">("semantic");
  const [episode, setEpisode] = useState("all");
  const [kind, setKind] = useState("all");
  const [category, setCategory] = useState("all");
  const [source, setSource] = useState("all");
  const [status, setStatus] = useState("all");
  const [provider, setProvider] = useState("all");
  const [model, setModel] = useState("all");
  const visual = visualBibleOf(document);
  const usageByVersion = useMemo(() => new Map(usage.map((item) => [item.version_id, item])), [usage]);
  const providers = [...new Set(assets.map((item) => item.provider_id).filter(Boolean))];
  const models = [...new Set(assets.map((item) => item.model_id).filter(Boolean))];
  const media = assets.filter((item) =>
    (episode === "all" || item.project_id === episode) &&
    (kind === "all" || item.kind === kind) &&
    (category === "all" || item.category === category) &&
    (source === "all" || item.source === source) &&
    (status === "all" || item.status === status) &&
    (provider === "all" || item.provider_id === provider) &&
    (model === "all" || item.model_id === model));
  return (
    <div className="production-asset-center">
      <div className="asset-center-intro">
        <div><span className="eyebrow">PRODUCTION ASSET CENTER</span><h3>资产中心</h3><p>语义资产来自 Film Bible；媒体文件按 Production 共享，来源分集仍保留。</p></div>
        <div><button onClick={onCreatePanorama}><ImageIcon size={15} />全景节点</button><button onClick={() => onOpenArt()}><BookOpen size={15} />塑角造景</button></div>
      </div>
      <div className="segmented asset-layer-tabs" aria-label="资产层级">
        <button className={layer === "semantic" ? "active" : ""} onClick={() => setLayer("semantic")}><BookOpen size={15} />语义资产 <span>{Object.values(visual.cards).filter((item) => !item.deletedAt).length}</span></button>
        <button className={layer === "media" ? "active" : ""} onClick={() => setLayer("media")}><FolderOpen size={15} />媒体资产 <span>{assets.length}</span></button>
      </div>
      {layer === "semantic" ? (
        <div className="semantic-asset-list">
          {Object.values(visual.cards).filter((card) => !card.deletedAt).map((card) => {
            const version = visual.versions[card.currentVersionId];
            const reference = primaryReference(version);
            const asset = assets.find((item) => item.id === reference?.assetId);
            const currentUsage = usageByVersion.get(version?.id);
            return <article key={card.id}>
              <button className="semantic-thumb" onClick={() => asset ? onPreview(asset) : onOpenArt(version?.id)}>{asset ? renderMedia(asset) : <ImageIcon />}</button>
              <div><small>{visualKindLabels[card.kind]}</small><b>{card.name}</b><span>V{version?.version || "?"} · {semanticStatus(card, version)}</span><p>{(currentUsage?.episodes || []).map((item) => `EP${String(item.episode_no).padStart(2, "0")}`).join(" · ") || "尚未用于分镜"}</p></div>
              <button onClick={() => onOpenArt(version?.id)}>管理版本</button>
            </article>;
          })}
          {!Object.values(visual.cards).some((item) => !item.deletedAt) && <div className="empty-state"><BookOpen /><h3>还没有语义资产</h3><p>分镜拆解后，角色、场景和道具会显示在这里。</p></div>}
        </div>
      ) : (
        <>
          <div className="asset-upload-row"><label>上传分类<select value={uploadCategory} onChange={(event) => onUploadCategory(event.target.value)}>{Object.entries(categoryLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label><button className="primary" onClick={onUpload}><Upload size={15} />上传素材</button></div>
          <div className="asset-center-filters">
            <label>范围<select value={episode} onChange={(event) => setEpisode(event.target.value)}><option value="all">整个 Production</option>{projects.map((item) => <option key={item.id} value={item.id}>EP{String(item.episode_no).padStart(2, "0")} · {item.episode_title || item.name}{item.id === currentProjectId ? "（当前）" : ""}</option>)}</select></label>
            <label>类型<select value={kind} onChange={(event) => setKind(event.target.value)}><option value="all">全部</option>{Object.entries(kindLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
            <label>分类<select value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">全部</option>{Object.entries(categoryLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
            <label>来源<select value={source} onChange={(event) => setSource(event.target.value)}><option value="all">全部</option>{Object.entries(sourceLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
            <label>状态<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="all">全部</option><option value="active">可用</option></select></label>
            <label>Provider<select value={provider} onChange={(event) => setProvider(event.target.value)}><option value="all">全部</option>{providers.map((id) => <option key={id} value={id}>{id}</option>)}</select></label>
            <label>Model<select value={model} onChange={(event) => setModel(event.target.value)}><option value="all">全部</option>{models.map((id) => <option key={id} value={id}>{id}</option>)}</select></label>
          </div>
          <div className="asset-grid production-media-grid">
            {media.map((asset) => <article className="asset-card" key={asset.id}>
              <button className="asset-visual" onClick={() => onPreview(asset)}>{["image", "video"].includes(asset.kind) ? renderMedia(asset) : asset.kind === "audio" ? <Music /> : <FolderOpen />}</button>
              <b title={asset.name}>{asset.name}</b>
              <select aria-label={`${asset.name} 分类`} value={asset.category || "other"} onChange={(event) => onCategory(asset, event.target.value)}>{Object.entries(categoryLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select>
              <small>{kindLabels[asset.kind] || asset.kind} · {sourceLabels[asset.source] || asset.source} · EP{String(asset.origin_episode_no || "?").padStart(2, "0")}</small>
              <details><summary>来源与使用记录</summary>{(() => { const version = Object.values(visual.versions).find((item) => primaryReference(item)?.assetId === asset.id); const used = version ? usageByVersion.get(version.id) : undefined; const history = version ? Object.values(visual.versions).filter((item) => item.cardId === version.cardId).sort((left, right) => left.version - right.version) : []; return <dl><dt>Asset ID</dt><dd>{asset.id}</dd><dt>来源项目</dt><dd>{asset.origin_project_name || asset.project_id}</dd><dt>创建时间</dt><dd>{new Date(asset.created * 1000).toLocaleString()}</dd><dt>Provider / Model</dt><dd>{asset.provider_id || "—"} / {asset.model_id || "—"}</dd><dt>Job</dt><dd>{asset.metadata?.job_id || "—"}</dd><dt>VisualVersion</dt><dd>{asset.visual_version_id || version?.id || "—"}</dd><dt>使用范围</dt><dd>{used ? `${used.episodes.map((item) => `EP${String(item.episode_no).padStart(2, "0")}`).join(" · ")} / ${used.shots.length} 镜` : "—"}</dd><dt>版本历史</dt><dd>{history.length ? history.map((item) => `V${item.version} ${item.status}`).join(" → ") : "—"}</dd><dt>Fingerprint</dt><dd>{asset.generation_fingerprint?.hash || "—"}</dd></dl>; })()}</details>
              <div>{asset.kind === "image" && <button onClick={() => onPanorama(asset)}>全景构图</button>}{asset.kind === "image" && onReference && <button onClick={() => onReference(asset)}>引用</button>}{["image", "video"].includes(asset.kind) && <button onClick={() => onTimeline(asset)}>入时间线</button>}<a href={asset.url} download={asset.name}><Download size={14} /></a><button className="icon-button danger asset-delete-button" onClick={() => onDelete(asset)} title="移入回收站"><Trash2 size={14} /></button></div>
            </article>)}
          </div>
          {!media.length && <div className="empty-state"><FolderOpen /><h3>没有符合筛选条件的媒体</h3><p>可切换分集或清除筛选。</p></div>}
        </>
      )}
    </div>
  );
}
