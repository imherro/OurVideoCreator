import React, { useEffect, useMemo, useState } from "react";
import { Boxes, GitBranch, ImagePlus, Layers3, LockKeyhole, Sparkles } from "lucide-react";
import { FilmBiblePanel } from "../filmBible/FilmBiblePanel";
import { primaryReference, resolveVisualGenerationTarget } from "../filmBible/references";
import { visualKindLabels, type VisualKind } from "../filmBible/types";
import { deriveArtStatus, usageLabels } from "../artDepartment";

type PanelProps = React.ComponentProps<typeof FilmBiblePanel>;
type Usage = {
  version_id: string;
  episodes: Array<{ project_id: string; episode_no: number; episode_title: string }>;
  shots: Array<{ project_id: string; episode_no: number; shot_uid: string; shot_id: string }>;
};

const filters: Array<{ id: "all" | VisualKind; label: string }> = [
  { id: "all", label: "全部" },
  { id: "character", label: "角色" },
  { id: "character_state", label: "角色状态" },
  { id: "scene", label: "场景" },
  { id: "scene_state", label: "场景状态" },
  { id: "prop", label: "道具" },
];

export function ArtDepartmentPage({
  productionName,
  usage,
  ...panelProps
}: PanelProps & { productionName: string; usage: Usage[] }) {
  const [filter, setFilter] = useState<"all" | VisualKind>("all");
  const [scope, setScope] = useState<"episode" | "production">("episode");
  const [activeVersionId, setActiveVersionId] = useState(panelProps.focusVersionId || "");
  const [busyVersionId, setBusyVersionId] = useState("");
  const requiredVersionIds = useMemo(() => {
    const ids = new Set<string>();
    for (const shot of panelProps.shots || []) {
      const bindings = shot.assetBindings || {};
      for (const item of bindings.characters || []) if (item?.versionId) ids.add(item.versionId);
      for (const item of bindings.props || []) if (item?.versionId) ids.add(item.versionId);
      if (bindings.scene?.versionId) ids.add(bindings.scene.versionId);
    }
    return ids;
  }, [panelProps.shots]);
  const requiredCardIds = useMemo(() => new Set([...requiredVersionIds].map((id) => panelProps.visual.versions[id]?.cardId).filter(Boolean)), [requiredVersionIds, panelProps.visual.versions]);
  const cards = useMemo(
    () => Object.values(panelProps.visual.cards)
      .filter((card) => !card.deletedAt && (scope === "production" || requiredCardIds.has(card.id)) && (filter === "all" || card.kind === filter))
      .sort((left, right) => `${left.kind}:${left.name}`.localeCompare(`${right.kind}:${right.name}`)),
    [panelProps.visual.cards, filter, scope, requiredCardIds],
  );
  const scopedVisual = useMemo(() => {
    const cardIds = new Set(cards.map((card) => card.id));
    return {
      cards: Object.fromEntries(Object.entries(panelProps.visual.cards).filter(([id]) => cardIds.has(id))),
      versions: Object.fromEntries(Object.entries(panelProps.visual.versions).filter(([, version]) => cardIds.has(version.cardId))),
    };
  }, [cards, panelProps.visual.cards, panelProps.visual.versions]);
  useEffect(() => {
    if (panelProps.focusVersionId) setActiveVersionId(panelProps.focusVersionId);
  }, [panelProps.focusVersionId]);
  useEffect(() => {
    if (cards[0] && !cards.some((card) => Object.values(panelProps.visual.versions).some((version) => version.cardId === card.id && version.id === activeVersionId))) setActiveVersionId(cards[0].currentVersionId);
  }, [activeVersionId, cards]);
  const usageByVersion = useMemo(
    () => new Map(usage.map((item) => [item.version_id, item])),
    [usage],
  );
  const select = (versionId: string) => {
    setActiveVersionId(versionId);
    panelProps.onFocusVersion(versionId);
  };
  const perform = async (versionId: string, action: () => Promise<void> | void) => {
    setBusyVersionId(versionId);
    try { await action(); } finally { setBusyVersionId(""); }
  };
  return (
    <section className="workflow-page art-department-page">
      <header className="workflow-page-header art-department-header">
        <div>
          <span className="eyebrow">ART DEPARTMENT · PRODUCTION ASSETS</span>
          <h2>塑角造景</h2>
          <p>统一管理“{productionName}”的角色、状态、场景与道具。锁定后的主参考图可供同一 Production 的所有分集直接引用。</p>
        </div>
        <div className="art-summary">
          <b>{cards.length}</b><span>当前筛选</span>
          <b>{Object.values(panelProps.visual.versions).filter((item) => item.status === "locked").length}</b><span>已锁定版本</span>
        </div>
      </header>
      <nav className="art-scope-switch" aria-label="资产范围">
        <button className={scope === "episode" ? "active" : ""} onClick={() => setScope("episode")}>本集需要 <small>{requiredCardIds.size}</small></button>
        <button className={scope === "production" ? "active" : ""} onClick={() => setScope("production")}>全部作品资产 <small>{Object.values(panelProps.visual.cards).filter((card) => !card.deletedAt).length}</small></button>
      </nav>
      <nav className="art-filters" aria-label="视觉资产类型">
        {filters.map((item) => (
          <button key={item.id} className={filter === item.id ? "active" : ""} onClick={() => setFilter(item.id)}>
            {item.label}<small>{item.id === "all" ? Object.values(panelProps.visual.cards).filter((card) => !card.deletedAt).length : Object.values(panelProps.visual.cards).filter((card) => !card.deletedAt && card.kind === item.id).length}</small>
          </button>
        ))}
      </nav>
      {!cards.length ? (
        <div className="empty-state art-empty"><Boxes /><h3>{scope === "episode" ? "本集暂无需要确认的资产" : "此分类还没有资产卡"}</h3><p>{scope === "episode" ? "先完成分镜规划和资产绑定，或切换到“全部作品资产”查看。" : "从剧本生成分镜时会提取共享视觉资产；进入本页不会自动调用模型。"}</p></div>
      ) : (
        <div className="art-card-grid">
          {cards.map((card) => {
            const versions = Object.values(panelProps.visual.versions)
              .filter((version) => version.cardId === card.id)
              .sort((left, right) => right.version - left.version);
            const current = panelProps.visual.versions[card.currentVersionId] || versions[0];
            const displayed = versions.find((item) => item.id === activeVersionId) || current;
            const reference = primaryReference(displayed);
            const generationActive = panelProps.jobs.some((job) =>
              job.node_id === `visual-version:${displayed.id}` && ["queued", "running"].includes(job.status),
            );
            const parentVersion = displayed.parentVersionId ? panelProps.visual.versions[displayed.parentVersionId] : undefined;
            const stateBlocked = ["character_state", "scene_state"].includes(card.kind) && (
              parentVersion?.status !== "locked" || !primaryReference(parentVersion)
            );
            const asset = panelProps.assets.find((item) => item.id === reference?.assetId);
            const currentUsage = usageByVersion.get(displayed?.id);
            let model = "尚未配置";
            try {
              const target = resolveVisualGenerationTarget(card, panelProps.generationPolicy, panelProps.providers, panelProps.localModels);
              const provider = panelProps.providers.find((item) => item.id === target.model_id);
              model = `${provider?.name || target.model_id} · ${target.model_id || "服务默认"}`;
            } catch {}
            return (
              <article className={`art-card ${activeVersionId === displayed?.id ? "active" : ""}`} key={card.id}>
                <button className="art-card-preview" onClick={() => select(displayed.id)}>
                  {asset ? <img src={asset.url} alt={`${card.name} 主参考图`} /> : <span><ImagePlus /><small>等待主参考图</small></span>}
                  <em>{deriveArtStatus(card, displayed, versions)}</em>
                </button>
                <div className="art-card-body">
                  <small>{visualKindLabels[card.kind]}</small><h3>{card.name}</h3>
                  <div className="art-version-row">
                    <label>当前版本</label>
                    <select value={displayed.id} onChange={(event) => select(event.target.value)}>
                      {versions.map((version) => <option key={version.id} value={version.id}>V{version.version} · {deriveArtStatus(card, version, versions)}</option>)}
                    </select>
                  </div>
                  <p className="art-model" title={model}>{model}</p>
                  <div className="art-usages">
                    {usageLabels(currentUsage?.episodes || []).slice(0, 4).map((label, index) => <span key={`${label}-${currentUsage?.episodes[index]?.project_id}`}>{label}</span>)}
                    {!currentUsage?.episodes.length && <small>尚未用于分镜</small>}
                    {!!currentUsage?.shots.length && <small>{currentUsage.shots.length} 镜</small>}
                  </div>
                  <div className="art-card-actions">
                    <button onClick={() => select(current.id)}><Layers3 size={14} />版本 {versions.length}</button>
                    {["draft", "pending_reference"].includes(displayed.status) && <button title={stateBlocked ? "请先生成并锁定基础角色或场景" : "生成参考图"} disabled={busyVersionId === displayed.id || generationActive || stateBlocked} onClick={() => void perform(displayed.id, () => panelProps.onGenerateReference(displayed.id))}><Sparkles size={14} />{generationActive ? "生成中" : stateBlocked ? "等待基础图锁定" : "生成参考"}</button>}
                    {displayed.status === "locked" && card.currentVersionId === displayed.id && <button onClick={() => panelProps.onFork(displayed.id, { description: displayed.spec.description, attributes: displayed.spec.attributes, invariants: displayed.invariants })}><GitBranch size={14} />派生新版</button>}
                    {displayed.status === "locked" && <span className="art-locked"><LockKeyhole size={13} />可跨集引用</span>}
                  </div>
                </div>
              </article>
            );
          })}
        </div>
      )}
      {!!cards.length && (
        <div className="art-department-detail">
          <div className="art-detail-heading"><div><span className="eyebrow">CANONICAL VERSION</span><h3>版本详情与参考图</h3></div><p>下方操作直接修改 Production Film Bible。</p></div>
          <FilmBiblePanel {...panelProps} visual={scopedVisual} focusVersionId={activeVersionId || panelProps.focusVersionId} onFocusVersion={select} />
        </div>
      )}
    </section>
  );
}
