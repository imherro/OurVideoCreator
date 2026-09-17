import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Check, RefreshCw, Save, Sparkles } from "lucide-react";
import { STATUS_LABELS, normalizeEpisodeSelection, splitList } from "../adaptation";
import {OwnedContentPanel} from '../OwnedContentPanel';
import type {OwnedContentDrafts} from '../ownedContentDrafts';

type Value = Record<string, any>;

export function ScriptRoomPage({
  productionId, currentEpisodeNo, providers, defaultTarget, refreshKey = 0, request, notify, report, onChanged, onSelectEpisode, onEnterEpisode,
  store,actorId,canManage,canEdit,
}: {
  productionId: string; currentEpisodeNo: number; providers: Value[]; defaultTarget?: Value; refreshKey?: number;
  store:OwnedContentDrafts;actorId:string;canManage:boolean;canEdit:boolean;
  request: (path: string, options?: RequestInit) => Promise<any>;
  notify: (message: string) => void; report: (error: unknown) => void;
  onChanged: (projectId?: string) => void | Promise<void>;
  onSelectEpisode: (episodeNo: number) => void | Promise<void>;
  onEnterEpisode: (episodeNo: number) => void | Promise<void>;
}) {
  const [items, setItems] = useState<Value[]>([]);
  const [chapters, setChapters] = useState<Value[]>([]);
  const [active, setActive] = useState(currentEpisodeNo);
  const [,render]=useState(0),selection=useRef(0),listSequence=useRef(0),activeRef=useRef(active);
  const redraw=()=>render(value=>value+1);
  const draft=store.productionId===productionId?store.value(String(active)):null;
  const entry=store.drafts.entries.get(String(active));
  store.selectedId=String(active);
  const editable=canEdit&&store.editable(String(active),actorId);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [assistInstructions,setAssistInstructions]=useState<Record<string,string>>({});
  const assistKey=`${productionId}:${active}`;
  const assistInstruction=assistInstructions[assistKey]||'';
  const assistSubmission=useRef<{key:string;id:string}|null>(null);
  const textProviders = useMemo(
    () => providers.filter((p) => !p.kind || p.kind === "text"),
    [providers],
  );
  const configuredDefaultProvider = textProviders.find((provider) => provider.id === defaultTarget?.model_id);
  const defaultProviderId = configuredDefaultProvider?.id || "";
  const defaultModelId = configuredDefaultProvider?.id || "";

  async function loadList(preferred = active) {
    const sequence=++listSequence.current,selectedAtStart=selection.current,generation=store.generation;
    const [scripts, sourceChapters] = await Promise.all([
      request(`/productions/${productionId}/scripts`),
      request(`/productions/${productionId}/chapters`),
    ]);
    if(!store.matches(productionId,generation)||sequence!==listSequence.current)return;
    scripts.forEach((item:Value)=>{if(item.script)store.receive(String(item.episodeNo),item.script,productionId,generation);});
    store.reconcileIds(scripts.map((item:Value)=>String(item.episodeNo)));
    setItems(scripts); setChapters(sourceChapters);
    redraw();
    if(selectedAtStart!==selection.current)return;
    const target = scripts.some((item: Value) => item.episodeNo === preferred) ? preferred : scripts[0]?.episodeNo || 1;
    if(scripts.length)await selectEpisode(target);
  }
  async function selectEpisode(episodeNo: number) {
    const selected=++selection.current,generation=store.generation;
    activeRef.current=episodeNo;setActive(episodeNo);
    const value=await request(`/productions/${productionId}/episode-scripts/${episodeNo}`);
    if(selected!==selection.current||!store.matches(productionId,generation))return;
    store.receive(String(episodeNo),value,productionId,generation);redraw();
  }
  useEffect(()=>{store.open(productionId);setItems([]);setSelected(new Set());
    return()=>{listSequence.current++;selection.current++;};},[productionId,store]);
  useEffect(() => { void loadList(activeRef.current).catch(report); }, [productionId, refreshKey]);
  useEffect(() => {
    if (currentEpisodeNo !== active) void selectEpisode(currentEpisodeNo).catch(report);
  }, [currentEpisodeNo]);
  function run(action: () => Promise<void>) {
    setBusy(true);
    void action().catch(report).finally(() => setBusy(false));
  }
  const item = items.find((value) => value.episodeNo === active);
  const plan = item?.plan;
  const displayedStatus=(value:Value)=>store.value(String(value.episodeNo))?.status||value.script?.status||value.plan?.status||'draft';
  function patch(value: Value) { if(editable){store.patch(String(active),value);redraw();} }

  async function save() {
    if (!draft) return;
    const pending=store.save(String(active),actorId,request);redraw();
    try{const value=await pending;if(!value)return;
      notify(store.unsaved?'提交成功；后续编辑仍未保存':`EP${String(active).padStart(2,"0")} 剧本已保存为草稿`);
      if(!store.unsaved)await onChanged(value.project_id);
    }finally{redraw();}
  }
  async function transition(action: "review" | "approve" | "needs-changes") {
    if (!draft) return;
    if(entry?.state!=='saved')throw new Error('请先保存或解决当前剧本草稿，再审核');
    const generation=store.generation;
    const value = await request(`/productions/${productionId}/episode-scripts/${active}/${action}`, { method: "POST", body: JSON.stringify({ revision: draft.revision, assignment_epoch: draft.assignment_epoch }) });
    if(!store.matches(productionId,generation))return;
    store.receive(String(active),value,productionId,generation);redraw();
    if(!store.unsaved)await onChanged(value.project_id);
    notify(action === "review" ? "本集剧本已提交审核" : action === "approve" ? "本集剧本已批准；下一步可以进入分镜规划" : "本集剧本已退回修改");
  }
  async function generate(episodeNos: number[]) {
    if(store.unsaved)throw new Error('请先保存或处理剧本草稿，再生成');
    const normalized = normalizeEpisodeSelection(episodeNos, Math.max(0,...items.map(item=>item.episodeNo)));
    if (!normalized.length) return;
    const provider = configuredDefaultProvider;
    if (!provider) throw new Error("项目默认平台文本模型 尚未配置，请到作品设置中选择");
    const providerId = provider.id;
    const modelId = provider?.id || "";
    if (!modelId) throw new Error("项目默认平台文本模型 尚未配置，请到作品设置中填写");
    if (!window.confirm(`将使用项目默认模型生成 ${normalized.length} 集剧本：${normalized.map((no) => `EP${String(no).padStart(2, "0")}`).join("、")}\n服务：${provider.name}\n模型：${modelId}\n确认创建 ${normalized.length} 个文本任务？`)) return;
    const result = await request(`/productions/${productionId}/script-generations`, {
      method: "POST",
      body: JSON.stringify({ episode_nos: normalized, model_id: modelId, submission_id: `scripts-${Date.now()}` }),
    });
    await onChanged(); await loadList(active);
    notify(`已创建 ${result.count} 个剧本任务，可在任务中心查看`);
  }

  async function assist() {
    if(!draft||!editable||entry?.state!=='saved')throw new Error('请先保存当前正文并解决冲突，再使用 AI 辅助');
    if(!defaultModelId)throw new Error('请先在作品设置中选择平台文本模型');
    const instruction=assistInstruction.trim();
    if(!instruction)throw new Error('请填写本集创作要求');
    const payload={instruction,model_id:defaultModelId,revision:draft.revision,assignment_epoch:draft.assignment_epoch};
    const key=JSON.stringify([assistKey,payload]);
    if(assistSubmission.current?.key!==key)assistSubmission.current={key,id:crypto.randomUUID()};
    await request(`/productions/${productionId}/episode-scripts/${active}/assist`,{
      method:'POST',body:JSON.stringify({...payload,submission_id:assistSubmission.current.id}),
    });
    // Only uncertain retries reuse the id; a later deliberate generation is new.
    assistSubmission.current=null;
    notify('本集 AI 辅助任务已提交。结果在任务中心比较并明确采纳，当前正文保持不变。');
    await onChanged();
  }

  return <section className="script-room-page workflow-domain-page">
    <header className="domain-header"><div><span className="eyebrow">SCRIPT ROOM</span><h1>剧本室</h1><p>直接编写或粘贴本集剧本；正式正文与画布共用一份，保存后仍需审核批准。</p></div><div className="settings-actions">
      <button disabled={busy} onClick={() => run(() => loadList(active))}><RefreshCw size={15} />刷新</button>
      <button disabled={busy || !editable || entry?.state==='conflict'} onClick={() => run(save)}><Save size={15} />保存草稿</button>
      <button disabled={busy || !editable || entry?.state!=='saved'||!draft?.body?.trim()} onClick={() => run(() => transition("review"))}>提交审核</button>
      <button className="primary" disabled={busy || !canManage || entry?.state!=='saved' || draft?.status !== "review"} onClick={() => run(() => transition("approve"))}><Check size={15} />批准</button>
    </div></header>
    <div className="script-room-layout">
      <aside className="script-episode-list"><header><b>分集</b><small>勾选后批量生成</small></header>{items.map((value) => <div className={active === value.episodeNo ? "active" : ""} key={value.episodeNo}>
        <input type="checkbox" disabled={value.plan?.status!=='approved'} checked={selected.has(value.episodeNo)} onChange={(e) => setSelected((current) => { const next = new Set(current); e.target.checked ? next.add(value.episodeNo) : next.delete(value.episodeNo); return next; })} />
        <button onClick={() => run(async () => { await onSelectEpisode(value.episodeNo); await selectEpisode(value.episodeNo); })}><b>EP{String(value.episodeNo).padStart(2, "0")}</b><span>{value.episodeTitle}</span><small className={displayedStatus(value)}>{STATUS_LABELS[displayedStatus(value)]}</small></button>
      </div>)}</aside>
      <main>{draft ? <>
        <OwnedContentPanel key={`${productionId}:${active}`} store={store} id={String(active)} actorId={actorId}
          canManage={canManage} canEdit={canEdit} request={request} onChange={redraw} onSave={save}/>
        {draft.metadata?.origin === "canvas" && <div className="notice"><b>来自画布快速创作</b><span>这里保存的是同一份正式剧本；修改后画布投影会同步更新。</span></div>}
        <div className="script-summary-strip"><span className={`workflow-status ${draft.status}`}>{STATUS_LABELS[draft.status]}</span><span>目标 {draft.estimatedDuration} 秒</span><span>{plan?.paywallRole || ''}</span><span>{draft.project_id ? "已建立 Episode" : "首次保存或生成时建立 Episode"}</span></div>
        <article className="domain-card script-body-card"><h2>剧本正文</h2><textarea aria-label="剧本正文" disabled={!editable} value={draft.body} onChange={(e) => patch({ body: e.target.value })} placeholder="直接编写或粘贴：场景标题、可见动作和对白…" /></article>
        <details className="domain-card"><summary>AI 辅助本集剧本（无需改编规划）</summary>
          <p>参考已保存正文、最近三集及 Bible，只生成本集候选，不自动覆盖。采纳后仍需审核；已有采纳视频的集不支持此操作。</p>
          <label>本集创作要求<textarea aria-label="本集 AI 创作要求" rows={3} maxLength={24000} disabled={!editable||busy}
            value={assistInstruction} onChange={event=>setAssistInstructions(current=>({...current,[assistKey]:event.target.value}))}
            placeholder="例如：在现有情节基础上补充车站重逢的动作与对白，保持人物关系…"/></label>
          <p>平台文本模型：{configuredDefaultProvider?.name||'未配置'}。创建任务可能产生供应商费用。</p>
          {entry?.state!=='saved'&&<p>请先保存当前正文或解决冲突。</p>}
          <button disabled={busy||!editable||entry?.state!=='saved'||!defaultModelId||!assistInstruction.trim()}
            onClick={()=>run(assist)}><Sparkles size={15}/>创建本集 AI 辅助任务</button>
        </details>
        <fieldset className="owned-content-fields" disabled={!editable}><article className="domain-card"><div className="domain-fields">
          <label>标题<input value={draft.title} onChange={(e) => patch({ title: e.target.value })} /></label>
          <label>预计时长（秒）<input type="number" value={draft.estimatedDuration} onChange={(e) => patch({ estimatedDuration: Number(e.target.value) })} /></label>
          <label>本集概要<textarea value={draft.synopsis} onChange={(e) => patch({ synopsis: e.target.value })} /></label>
          <label>剧情目标<textarea value={draft.storyGoal} onChange={(e) => patch({ storyGoal: e.target.value })} /></label>
        </div><fieldset className="chapter-reference-field"><legend>原著来源</legend>{chapters.map((chapter) => <label className="check-label" key={chapter.id}><input type="checkbox" checked={draft.sourceChapterRefs.includes(chapter.id)} onChange={(e) => patch({ sourceChapterRefs: e.target.checked ? [...draft.sourceChapterRefs, chapter.id] : draft.sourceChapterRefs.filter((id: string) => id !== chapter.id) })} />{chapter.display_no ?? chapter.chapter_no}. {chapter.title}</label>)}</fieldset>
        {plan&&<div className="plan-evidence"><div><b>开场钩子</b><p>{plan.hook || "未填写"}</p></div><div><b>结尾悬念</b><p>{plan.cliffhanger || "未填写"}</p></div><div><b>核心冲突</b><p>{plan.coreConflict || "未填写"}</p></div></div>}</article>
        <article className="domain-card"><h2>制作清单</h2><div className="domain-fields three">
          <label>角色（逗号或换行）<textarea rows={3} value={draft.characters.join("、")} onChange={(e) => patch({ characters: splitList(e.target.value) })} /></label>
          <label>场景（逗号或换行）<textarea rows={3} value={draft.scenes.join("、")} onChange={(e) => patch({ scenes: splitList(e.target.value) })} /></label>
          <label>道具（逗号或换行）<textarea rows={3} value={draft.props.join("、")} onChange={(e) => patch({ props: splitList(e.target.value) })} /></label>
        </div></article></fieldset><div className="script-state-actions"><button disabled={busy||!canManage||entry?.state!=='saved'} onClick={() => run(() => transition("needs-changes"))}>退回修改</button><button disabled={busy||!editable||store.unsaved||plan?.status!=='approved'} onClick={() => run(() => generate([active]))}><Sparkles size={15} />根据已批准规划生成本集</button>{draft.status === "approved" && <button className="primary" disabled={busy || !draft.project_id||entry?.state!=='saved'} onClick={() => run(() => Promise.resolve(onEnterEpisode(active)))} >进入分镜规划<ArrowRight size={15}/></button>}</div>
      </> : <div className="empty-state"><h3>选择一集开始写剧本</h3><p>可在作品列表新增一集；直接创作无需先生成改编规划。</p></div>}</main>
    </div>
    {!!selected.size&&<footer className="domain-generation-bar"><div><b>根据已批准规划批量生成所选剧本</b><small>已选 {selected.size} 集 · 使用项目默认模型：{configuredDefaultProvider?.name || "未配置外部 Provider"} · {defaultModelId || "未配置模型 ID"}</small></div><button className="primary" disabled={busy || !selected.size} onClick={() => run(() => generate([...selected]))}><Sparkles size={15} />生成 {selected.size} 集</button></footer>}
  </section>;
}
