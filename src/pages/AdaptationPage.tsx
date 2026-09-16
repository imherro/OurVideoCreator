import { useEffect, useMemo, useState } from "react";
import { Check, RefreshCw, Save, Sparkles } from "lucide-react";
import {
  DURATION_OPTIONS,
  PAYWALL_LABELS,
  PAYWALL_ROLES,
  PLATFORM_OPTIONS,
  RATIO_OPTIONS,
  STATUS_LABELS,
  createEpisodePlans,
  type EpisodePlan,
} from "../adaptation";

type Value = Record<string, any>;
const storyGroups = [
  ["storyCore", "故事核心", [["premise", "核心前提"], ["theme", "主题"], ["protagonist", "主角"], ["goal", "主角目标"], ["stakes", "失败代价"]]],
  ["storyArc", "故事弧", [["opening", "开局"], ["development", "发展"], ["turningPoint", "转折"], ["climax", "高潮"], ["ending", "结局"]]],
  ["adaptationStrategy", "改编策略", [["audience", "目标受众"], ["tone", "基调"], ["changes", "改编取舍"], ["constraints", "保留约束"]]],
] as const;

export function AdaptationPage({
  productionId, projectId, providers, defaultTarget, refreshKey = 0, request, notify, report, onRevision, onOpenSource,
}: {
  productionId: string; projectId: string; providers: Value[]; defaultTarget?: Value; refreshKey?: number;
  request: (path: string, options?: RequestInit) => Promise<any>;
  notify: (message: string) => void; report: (error: unknown) => void;
  onRevision: (revision: number) => void;
  onOpenSource: () => void;
}) {
  const [draft, setDraft] = useState<Value | null>(null);
  const [chapters, setChapters] = useState<Value[]>([]);
  const [active, setActive] = useState(1);
  const [busy, setBusy] = useState(false);
  const textProviders = useMemo(
    () => providers.filter((p) => !p.kind || p.kind === "text"),
    [providers],
  );
  const configuredDefault = textProviders.find((provider) => provider.id === defaultTarget?.model_id);
  const defaultProviderId = configuredDefault?.id || "";
  const defaultModelId = configuredDefault?.id || "";
  const [providerId, setProviderId] = useState(defaultProviderId);

  async function load() {
    const [value, sourceChapters] = await Promise.all([
      request(`/productions/${productionId}/adaptation`),
      request(`/productions/${productionId}/chapters`),
    ]);
    setDraft(value);
    onRevision(value.revision);
    setChapters(sourceChapters);
    setActive((current) => Math.min(Math.max(1, current), Math.max(1, value.episodePlans.length)));
  }
  useEffect(() => { setDraft(null); setActive(1); void load().catch(report); }, [productionId, refreshKey]);
  useEffect(() => {
    setProviderId(defaultProviderId);
  }, [productionId, defaultTarget?.model_id, defaultTarget?.model_id]);
  function run(action: () => Promise<void>) {
    setBusy(true);
    void action().catch(report).finally(() => setBusy(false));
  }
  function setFormat(key: string, value: any) {
    setDraft((current) => current && ({ ...current, adaptationPlan: { ...current.adaptationPlan, format: { ...current.adaptationPlan.format, [key]: value } } }));
  }
  function setStory(group: string, key: string, value: string) {
    setDraft((current) => current && ({ ...current, adaptationPlan: { ...current.adaptationPlan, [group]: { ...current.adaptationPlan[group], [key]: value } } }));
  }
  function setPlan(patch: Partial<EpisodePlan>) {
    setDraft((current) => current && ({ ...current, episodePlans: current.episodePlans.map((item: EpisodePlan) => item.episodeNo === active ? { ...item, ...patch } : item) }));
  }
  async function save() {
    if (!draft) return;
    const value = await request(`/productions/${productionId}/adaptation`, {
      method: "PUT",
      body: JSON.stringify({ revision: draft.revision, adaptationPlan: draft.adaptationPlan, episodePlans: draft.episodePlans, monetizationPlan: draft.monetizationPlan }),
    });
    setDraft(value); onRevision(value.revision); notify("改编策划已保存为草稿");
  }
  async function transition(action: "review" | "approve") {
    if (!draft) return;
    const value = await request(`/productions/${productionId}/adaptation/${action}`, { method: "POST", body: JSON.stringify({ revision: draft.revision }) });
    setDraft(value); onRevision(value.revision);
    notify(action === "review" ? "改编策划已提交审核" : "改编策划已批准，可以生成逐集剧本");
  }
  async function generate() {
    if (!draft) return;
    const provider = textProviders.find((item) => item.id === providerId);
    if (!provider) throw new Error("请先为作品配置平台文本模型；系统不会自动选择其他付费模型");
    const modelId = provider?.id || "";
    if (!modelId) throw new Error("请选择已发布的平台文本模型");
    if (!window.confirm(`将依据 ${draft.sourceEventCount} 条原著事件重新生成完整改编策划。\n服务：${provider.name}\n模型：${modelId}\n生成结果会进入待审核状态。确认创建文本任务？`)) return;
    const episodePlans = createEpisodePlans(draft.adaptationPlan.format.episodeCount, draft.adaptationPlan.format.targetDuration, draft.episodePlans);
    const saved = await request(`/productions/${productionId}/adaptation`, {
      method: "PUT",
      body: JSON.stringify({ revision: draft.revision, adaptationPlan: draft.adaptationPlan, episodePlans, monetizationPlan: draft.monetizationPlan }),
    });
    setDraft({ ...saved, sourceEventCount: draft.sourceEventCount });
    onRevision(saved.revision);
    await request(`/productions/${productionId}/adaptation/generate`, {
      method: "POST",
      body: JSON.stringify({ project_id: projectId, model_id: modelId, submission_id: `adaptation-${Date.now()}` }),
    });
    notify("已创建改编策划任务；完成后本页会自动刷新");
  }
  if (!draft) return <div className="loading"><RefreshCw className="spin" />加载改编策划…</div>;
  const plan: EpisodePlan | undefined = draft.episodePlans.find((item: EpisodePlan) => item.episodeNo === active);
  const format = draft.adaptationPlan.format;
  return <section className="adaptation-page workflow-domain-page">
    <header className="domain-header">
      <div><span className="eyebrow">ADAPTATION</span><h1>改编工作台</h1><p>原著事件 → 故事骨架 → 改编策略 → 分集规划。所有 AI 结果都需要人工批准。</p></div>
      <div className="settings-actions">
        <span className={`workflow-status ${draft.adaptationPlan.status}`}>{STATUS_LABELS[draft.adaptationPlan.status] || draft.adaptationPlan.status}</span>
        <button disabled={busy} onClick={() => run(load)}><RefreshCw size={15} />刷新</button>
        <button disabled={busy} onClick={() => run(save)}><Save size={15} />保存草稿</button>
        <button disabled={busy} onClick={() => run(() => transition("review"))}>提交审核</button>
        <button className="primary" disabled={busy || draft.adaptationPlan.status !== "review"} onClick={() => run(() => transition("approve"))}><Check size={15} />批准</button>
      </div>
    </header>
    <div className="adaptation-layout"><main className="adaptation-main">
      <article className="domain-card"><h2>成片规格</h2><div className="domain-fields four">
        <label>总集数<input type="number" min="1" max="500" value={format.episodeCount} onChange={(e) => setFormat("episodeCount", Number(e.target.value))} /></label>
        <label>单集秒数<input list="adaptation-duration-options" type="number" min="1" max="3000" value={format.targetDuration} onChange={(e) => setFormat("targetDuration", Number(e.target.value))} /><datalist id="adaptation-duration-options">{DURATION_OPTIONS.map((value)=><option value={value} key={value}/>)}</datalist></label>
        <label>画幅<select value={format.ratio} onChange={(e) => setFormat("ratio", e.target.value)}>{RATIO_OPTIONS.map((value)=><option value={value} key={value}>{value}</option>)}</select></label>
        <label>平台<select value={format.platform} onChange={(e) => setFormat("platform", e.target.value)}>{!PLATFORM_OPTIONS.includes(format.platform) && <option value={format.platform}>{format.platform}</option>}{PLATFORM_OPTIONS.map((value)=><option value={value} key={value}>{value}</option>)}</select><small>用于 AI 决定节奏、钩子与商业卡点。</small></label>
      </div><button onClick={() => setDraft((current) => current && ({ ...current, episodePlans: createEpisodePlans(current.adaptationPlan.format.episodeCount, current.adaptationPlan.format.targetDuration, current.episodePlans) }))}>按规格建立 / 调整分集规划</button></article>
      {storyGroups.map(([key, title, fields]) => <article className="domain-card" key={key}><h2>{title}</h2><div className="domain-fields">{fields.map(([field, label]) => <label key={field}>{label}<textarea rows={2} value={draft.adaptationPlan[key]?.[field] || ""} onChange={(e) => setStory(key, field, e.target.value)} /></label>)}</div></article>)}
      <article className="domain-card"><div className="domain-card-heading"><div><h2>分集规划</h2><small>{draft.episodePlans.length} 集 · 当前 EP{String(active).padStart(2, "0")}</small></div></div>
        {plan ? <div className="episode-plan-editor"><div className="domain-fields">
          <label>一句话梗概<textarea rows={2} value={plan.logline} onChange={(e) => setPlan({ logline: e.target.value })} /></label>
          <label>核心冲突<textarea rows={2} value={plan.coreConflict} onChange={(e) => setPlan({ coreConflict: e.target.value })} /></label>
          <label>情绪节拍<textarea rows={2} value={plan.emotionalBeat} onChange={(e) => setPlan({ emotionalBeat: e.target.value })} /></label>
          <label>开场钩子<textarea rows={2} value={plan.hook} onChange={(e) => setPlan({ hook: e.target.value })} /></label>
          <label>结尾悬念<textarea rows={2} value={plan.cliffhanger} onChange={(e) => setPlan({ cliffhanger: e.target.value })} /></label>
          <label>付费角色<select value={plan.paywallRole} onChange={(e) => setPlan({ paywallRole: e.target.value })}>{PAYWALL_ROLES.map((role) => <option value={role} key={role}>{PAYWALL_LABELS[role]}</option>)}</select></label>
          <label>目标秒数<input type="number" value={plan.targetDuration} onChange={(e) => setPlan({ targetDuration: Number(e.target.value) })} /></label>
        </div><fieldset className="chapter-reference-field"><legend>原著章节引用</legend>{chapters.map((chapter) => <label className="check-label" key={chapter.id}><input type="checkbox" checked={plan.sourceChapterRefs.includes(chapter.id)} onChange={(e) => setPlan({ sourceChapterRefs: e.target.checked ? [...plan.sourceChapterRefs, chapter.id] : plan.sourceChapterRefs.filter((id) => id !== chapter.id) })} />{chapter.display_no ?? chapter.chapter_no}. {chapter.title}</label>)}</fieldset></div> : <div className="empty-state">请先建立分集规划</div>}
      </article>
      <MonetizationEditor draft={draft} setDraft={setDraft} />
    </main><aside className="episode-plan-list"><h3>分集导航</h3>{draft.episodePlans.map((item: EpisodePlan) => <button key={item.episodeNo} className={active === item.episodeNo ? "active" : ""} onClick={() => setActive(item.episodeNo)}><span>EP{String(item.episodeNo).padStart(2, "0")}</span><small className={item.status}>{STATUS_LABELS[item.status] || item.status}</small></button>)}</aside></div>
    <footer className="domain-generation-bar"><div><b>AI 基于原著生成整个改编工作台</b><small>{draft.sourceEventCount ? `${draft.sourceEventCount} 条原著事件 · 将生成故事骨架、策略、分集规划和商业卡点` : "尚未提取原著事件，请先完成原著分析"}</small></div><label>服务<select value={providerId} onChange={(e) => setProviderId(e.target.value)}><option value="" disabled>请选择平台模型</option>{textProviders.map((item) => <option key={item.id} value={item.id}>外部 API · {item.name}</option>)}</select></label>{!textProviders.length&&<p className="error">暂无可用平台文本模型，请联系管理员。</p>}{draft.sourceEventCount ? <button className="primary" disabled={busy} onClick={() => run(generate)}><Sparkles size={15} />生成整个工作台</button> : <button className="primary" disabled={busy} onClick={onOpenSource}>先提取原著事件</button>}</footer>
  </section>;
}

function MonetizationEditor({ draft, setDraft }: { draft: Value; setDraft: (value: Value) => void }) {
  const money = draft.monetizationPlan;
  const update = (patch: Value) => setDraft({ ...draft, monetizationPlan: { ...money, ...patch } });
  const updateBeat = (index: number, patch: Value) => update({ beats: money.beats.map((beat: Value, i: number) => i === index ? { ...beat, ...patch } : beat) });
  return <article className="domain-card"><h2>付费卡点</h2><div className="domain-fields three">
    <label>模式<input value={money.mode} onChange={(e) => update({ mode: e.target.value })} /></label>
    <label>免费集数<input type="number" value={money.freeEpisodes} onChange={(e) => update({ freeEpisodes: Number(e.target.value) })} /></label>
    <label>首个付费集<input type="number" value={money.firstPaywallEpisode} onChange={(e) => update({ firstPaywallEpisode: Number(e.target.value) })} /></label>
  </div>{money.beats.map((beat: Value, index: number) => <div className="paywall-beat" key={index}><div className="domain-fields three">
    <label>集数<input type="number" value={beat.episodeNo} onChange={(e) => updateBeat(index, { episodeNo: Number(e.target.value) })} /></label>
    {[["type", "类型"], ["setup", "铺垫"], ["cliffhanger", "悬念"], ["expectedEmotion", "预期情绪"], ["rationale", "设置理由"]].map(([key, label]) => <label key={key}>{label}<input value={beat[key]} onChange={(e) => updateBeat(index, { [key]: e.target.value })} /></label>)}
  </div><button className="quiet danger" onClick={() => update({ beats: money.beats.filter((_: Value, i: number) => i !== index) })}>移除此卡点</button></div>)}
  <button onClick={() => update({ beats: [...money.beats, { episodeNo: Math.min(draft.adaptationPlan.format.episodeCount, money.firstPaywallEpisode), type: "paywall", setup: "", cliffhanger: "", expectedEmotion: "", rationale: "" }] })}>添加付费卡点</button></article>;
}
