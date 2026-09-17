import { useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, CheckSquare2, FilePlus2, Plus, RefreshCw, Save, Search, Sparkles, Square, Trash2, Upload, X } from "lucide-react";
import {OwnedContentPanel} from '../OwnedContentPanel';
import type {OwnedContentDrafts} from '../ownedContentDrafts';

type AnyValue = any;
type CreateDialog = { mode: "source" | "chapter"; sourceId?: string; sourceName?: string };

export function SourceLibraryPage({
  productionId, projectId, providers, defaultTarget, refreshKey = 0, request, notify, report,store,actorId,canManage,canEdit,
}: {
  productionId: string; projectId: string;
  store:OwnedContentDrafts;actorId:string;canManage:boolean;canEdit:boolean;
  providers: AnyValue[]; defaultTarget?: AnyValue; refreshKey?: number;
  request: (path: string, options?: RequestInit) => Promise<AnyValue>;
  notify: (message: string) => void; report: (error: unknown) => void;
}) {
  const [sources, setSources] = useState<AnyValue[]>([]);
  const [chapterIds,setChapterIds]=useState<string[]>([]),[,render]=useState(0),loadSequence=useRef(0);
  const redraw=()=>render(value=>value+1);
  const chapters=store.productionId===productionId?[...new Set([...chapterIds,...store.drafts.entries.keys()])]
    .map(id=>store.value(id)).filter((value):value is Record<string,any>=>value!==null):[];
  const [events, setEvents] = useState<AnyValue[]>([]);
  const [active, setActive] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<CreateDialog | null>(null);
  const [sourceName, setSourceName] = useState("");
  const [chapterTitle, setChapterTitle] = useState("第一章");
  const [chapterContent, setChapterContent] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const importTarget=useRef<{productionId:string;generation:number;sourceId?:string;sourceName?:string}|null>(null);
  const importing=useRef(false);
  const [loadedProduction,setLoadedProduction]=useState('');
  const ready=loadedProduction===productionId;
  const textProviders = useMemo(
    () => providers.filter((provider) => !provider.kind || provider.kind === "text"),
    [providers],
  );
  const configuredDefault = textProviders.find((provider) => provider.id === defaultTarget?.model_id);
  const defaultProviderId = configuredDefault?.id || "";
  const defaultModelId = configuredDefault?.id || "";
  const [providerId, setProviderId] = useState(defaultProviderId);
  const chapter = chapters.find((item) => item.id === active);
  const entry=store.drafts.entries.get(active),editable=canEdit&&store.editable(active,actorId);
  store.selectedId=active;
  const activeSource = sources.find((item) => item.id === chapter?.source_id) || sources[0];

  async function load() {
    const sequence=++loadSequence.current,generation=store.generation;
    const [nextSources, nextChapters, nextEvents] = await Promise.all([
      request(`/productions/${productionId}/sources`),
      request(`/productions/${productionId}/chapters`),
      request(`/productions/${productionId}/source-events`),
    ]);
    if(sequence!==loadSequence.current||!store.matches(productionId,generation))return;
    setLoadedProduction(productionId);
    setSources(nextSources);
    nextChapters.forEach((item:AnyValue)=>store.receive(item.id,item,productionId,generation));
    store.reconcileIds(nextChapters.map((item:AnyValue)=>item.id));
    setChapterIds(nextChapters.map((item:AnyValue)=>item.id));redraw();
    setEvents(nextEvents);
    setActive((value) => value && store.value(value) ? value : nextChapters[0]?.id || "");
  }

  useEffect(()=>{store.open(productionId);setSources([]);setLoadedProduction('');setChapterIds([]);setSelected(new Set());setDialog(null);
    return()=>{loadSequence.current++;};},[productionId,store]);
  useEffect(() => { void load().catch(report); }, [productionId, refreshKey]);
  useEffect(() => {
    setProviderId(defaultProviderId);
  }, [productionId, projectId, defaultTarget?.model_id, defaultTarget?.model_id]);

  function run(action: () => Promise<void>) { void action().catch(report); }
  function openCreateSource(additional=false) {
    if(!ready||busy||!canEdit||(sources.length>0&&!additional))return;
    setSourceName("");
    setChapterTitle("第一章");
    setChapterContent("");
    setDialog({ mode: "source" });
  }
  function openCreateChapter() {
    if(!ready||busy||!canEdit)return;
    const source = sources.find((item) => item.id === chapter?.source_id) || sources[0];
    if (!source) return;
    setChapterTitle(`第 ${Number(source.chapter_count || 0) + 1} 章`);
    setChapterContent("");
    setDialog({ mode: "chapter", sourceId: source.id, sourceName: source.title });
  }
  async function createManualContent() {
    if (!dialog || !chapterTitle.trim() || (dialog.mode === "source" && !sourceName.trim())) return;
    setBusy(true);
    const generation=store.generation;
    try {
      let sourceId = dialog.sourceId;
      if (dialog.mode === "source") {
        const source = await request(`/productions/${productionId}/sources`, {
          method: "POST", body: JSON.stringify({ title: sourceName.trim(), type: "manual", metadata: {} }),
        });
        sourceId = source.id;
      }
      if(!store.matches(productionId,generation))return;
      const created = await request(`/productions/${productionId}/sources/${sourceId}/chapters`, {
        method: "POST", body: JSON.stringify({ title: chapterTitle.trim(), content: chapterContent }),
      });
      if(!store.matches(productionId,generation))return;
      const mode = dialog.mode;
      setDialog(null);
      await load();
      setActive(created.id);
      notify(mode === "source" ? "原著和第一章已建立" : "章节已新增");
    } finally { setBusy(false); }
  }
  function chooseImport(additional=false){
    if(!ready||busy||!canEdit||importing.current)return;
    importTarget.current={productionId,generation:store.generation,
      sourceId:additional?undefined:activeSource?.id,sourceName:additional?undefined:activeSource?.title};
    fileRef.current?.click();
  }
  async function importFile(file: File) {
    const target=importTarget.current;
    if(importing.current)return;
    if(!target||target.productionId!==productionId||!store.matches(productionId,target.generation))
      throw new Error('作品已切换，请重新选择文件');
    importing.current=true;
    setBusy(true);
    const generation=target.generation;
    try {
      const content=await file.text();
      if(!store.matches(productionId,generation))return;
      const path=target.sourceId?`/productions/${productionId}/sources/${target.sourceId}/chapters/import`:`/productions/${productionId}/sources/import`;
      const imported=await request(path, { method: "POST", body: JSON.stringify({
        title: file.name.replace(/\.(txt|md|markdown)$/i, ""),
        type: /\.md|\.markdown$/i.test(file.name) ? "markdown" : "txt",
        content, metadata: { filename: file.name },
      }) });
      if(!store.matches(productionId,generation))return;
      await load();
      if(!store.matches(productionId,generation))return;
      setActive(imported.first_chapter_id||'');
      notify(target.sourceId?`已向“${target.sourceName}”追加 ${imported.imported_count} 章；原有章节及未保存草稿保留`:`已导入 ${file.name}`);
    } finally { importing.current=false;setBusy(false); }
  }
  async function saveChapter() {
    if (!chapter) return;
    setBusy(true);
    try {
      const pending=store.save(chapter.id,actorId,request);redraw();
      const saved=await pending;
      if(saved)notify(store.drafts.entries.get(chapter.id)?.state==='saved'?"章节已保存":"提交成功；后续编辑仍未保存");
    } finally { setBusy(false);redraw(); }
  }
  async function deleteActiveSource() {
    if (!activeSource) return;
    if(chapters.some(item=>item.source_id===activeSource.id&&store.drafts.entries.get(item.id)?.state!=='saved'))
      throw new Error('当前原著含未保存章节，请先处理草稿再删除');
    if (!window.confirm(`将原著“${activeSource.title}”及其 ${activeSource.chapter_count || 0} 个章节移入回收站？\n章节和已提取事件会暂时隐藏，恢复原著后会重新出现。`)) return;
    setBusy(true);
    try {
      await request(`/productions/${productionId}/sources/${activeSource.id}`, { method: "DELETE", body: JSON.stringify({
        versions: Object.fromEntries(chapters.filter(item => item.source_id === activeSource.id).map(item => [item.id,
          {revision:item.revision,assignment_epoch:item.assignment_epoch}]))
      }) });
      setSelected(new Set());
      await load();
      notify(`原著“${activeSource.title}”已移入回收站`);
    } finally { setBusy(false); }
  }
  async function deleteSelectedChapters() {
    if (!selected.size) return;
    if([...selected].some(id=>store.drafts.entries.get(id)?.state!=='saved'))throw new Error('所选章节含未保存草稿，请先处理');
    if (!window.confirm(`将选中的 ${selected.size} 个章节移入回收站？\n对应的已提取事件会暂时隐藏，恢复章节后会重新出现。`)) return;
    setBusy(true);
    try {
      await request(`/productions/${productionId}/chapters/trash`, {
        method: "POST", body: JSON.stringify({ chapter_ids: [...selected], versions: Object.fromEntries(
          chapters.filter(item => selected.has(item.id)).map(item => [item.id,{revision:item.revision,assignment_epoch:item.assignment_epoch}])) }),
      });
      const count = selected.size;
      setSelected(new Set());
      await load();
      notify(`已将 ${count} 个章节移入回收站`);
    } finally { setBusy(false); }
  }
  async function extract() {
    if (!selected.size) return;
    if([...selected].some(id=>store.drafts.entries.get(id)?.state!=='saved'))throw new Error('请先保存所选章节，再提取事件');
    const provider = textProviders.find((item) => item.id === providerId);
    const modelId = provider?.id || "";
    if (!provider) throw new Error("请先为作品配置平台文本模型；系统不会自动选择其他付费模型");
    if (!modelId) throw new Error("请选择已发布的平台文本模型");
    if (!window.confirm(`将分析 ${selected.size} 个章节\n模型：${provider.name} / ${modelId}\n确认创建文本任务？`)) return;
    setBusy(true);
    try {
      await request(`/productions/${productionId}/source-extractions`, { method: "POST", body: JSON.stringify({
        project_id: projectId, chapter_ids: [...selected], model_id: modelId,
        submission_id: `source-${Date.now()}`,
      }) });
      notify(`已创建 ${selected.size} 个事件提取任务，可在任务中心查看`);
    } finally { setBusy(false); }
  }

  const visible = chapters.filter((item) => !query || item.title.includes(query) || item.content.includes(query));
  return <section className="source-library-page">
    <header className="source-library-header">
      <div><span className="eyebrow">PRODUCTION SOURCE LIBRARY</span><h1>整部作品原著库</h1><p>Production 共享资料 · 章节与分集的对应关系在改编策划和单集剧本中设置。</p></div>
      <div className="settings-actions">
        <button onClick={() => run(load)} disabled={busy}><RefreshCw size={15}/>刷新</button>
        <button onClick={() => chooseImport()} disabled={busy||!ready||!canEdit} title={activeSource?`追加到“${activeSource.title}”，不覆盖原有章节`:undefined}><Upload size={15}/>{activeSource?'导入章节到当前原著':'导入 TXT / Markdown'}</button>
        <button onClick={()=>openCreateSource()} disabled={busy||!ready||!canEdit||sources.length>0}><FilePlus2 size={15}/>新建原著</button>
        <button onClick={openCreateChapter} disabled={busy || !ready || !canEdit || !sources.length}><Plus size={15}/>新增章节</button>
        {ready&&sources.length>0&&<details><summary>更多原著操作</summary>
          <button disabled={busy||!canEdit} onClick={()=>openCreateSource(true)}>添加另一部原著</button>
          <button disabled={busy||!canEdit} onClick={()=>chooseImport(true)}>导入为另一部原著</button>
        </details>}
        <button className="danger-button" onClick={() => run(deleteActiveSource)} disabled={busy || !canManage || !activeSource} title="移入回收站，可恢复；须先接管全部章节"><Trash2 size={15}/>移除当前原著</button>
      </div>
    </header>
    <input ref={fileRef} hidden type="file" accept=".txt,.md,.markdown,text/plain,text/markdown" onChange={(event) => { const file = event.target.files?.[0]; if (file) run(() => importFile(file)); event.target.value = ""; }}/>
    <div className="source-library-grid">
      <aside>
        <label className="source-search"><Search size={14}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索章节"/></label>
        <small>{sources.length} 部原著 · {chapters.length} 章</small>
        <div className="source-selection-actions"><span>已选 {selected.size} 章</span><div><button disabled={busy || !visible.length} onClick={() => setSelected(new Set(visible.map((item) => item.id)))}><CheckSquare2 size={14}/>全选</button><button disabled={busy || !selected.size} onClick={() => setSelected(new Set())}><Square size={14}/>全不选</button><button className="danger-button icon-button" title="移除所选章节" aria-label="移除所选章节" disabled={busy || !selected.size} onClick={() => run(deleteSelectedChapters)}><Trash2 size={14}/></button></div></div>
        {visible.map((item) => <button className={active === item.id ? "active" : ""} key={item.id} onClick={() => setActive(item.id)}><input type="checkbox" checked={selected.has(item.id)} onClick={(event) => event.stopPropagation()} onChange={(event) => setSelected((value) => { const next = new Set(value); event.target.checked ? next.add(item.id) : next.delete(item.id); return next; })}/><span><b>{item.display_no ?? item.chapter_no}. {item.title}</b><small>{item.source_title}</small></span></button>)}
      </aside>
      <main>{chapter ? <>
        <OwnedContentPanel key={`${productionId}:${active}`} store={store} id={active} actorId={actorId} canManage={canManage}
          canEdit={canEdit} request={request} onChange={redraw} onSave={saveChapter}/>
        <div className="chapter-editor-head"><input readOnly={!editable} value={chapter.title} onChange={(event) => {store.patch(active,{title:event.target.value});redraw();}}/><button disabled={busy||!editable||entry?.state==='conflict'} onClick={() => run(saveChapter)}><Save size={14}/>保存章节</button></div>
        <textarea className="chapter-editor" readOnly={!editable} value={chapter.content} onChange={(event) => {store.patch(active,{content:event.target.value});redraw();}}/>
        <h3>已提取事件</h3>{events.filter((item) => item.chapter_id === chapter.id).map((item) => <article className="source-event" key={item.id}><b>{item.event_order}. {item.summary}</b><small>{item.importance} · {item.emotion || "无情绪标注"} · {item.characters.join("、") || "无明确人物"}</small></article>)}
      </> : <div className="empty-state"><BookOpen/><h3>导入或新建原著</h3></div>}</main>
      <aside className="source-analysis">
        <h3>AI 事件提取</h3><p>作品级分析 · 已选 {selected.size} 章。任务失败时保留已有事件。</p>
        <label>文本模型<select value={providerId} onChange={(event) => setProviderId(event.target.value)}><option value="" disabled>请选择平台模型</option>{textProviders.map((provider) => <option key={provider.id} value={provider.id}>外部 API · {provider.name}</option>)}</select></label>
        {!textProviders.length&&<p className="error">暂无可用平台文本模型，请联系管理员。</p>}
        <button disabled={busy || !selected.size} onClick={() => run(extract)}><Sparkles size={15}/>提取所选章节事件</button>
      </aside>
    </div>
    {dialog && <div className="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="source-create-title"><div className="source-create-dialog">
      <header><div><span className="eyebrow">SOURCE</span><h2 id="source-create-title">{dialog.mode === "source" ? "手工新建原著" : `新增章节 · ${dialog.sourceName}`}</h2></div><button className="icon-button" aria-label="关闭" onClick={() => setDialog(null)}><X size={18}/></button></header>
      {dialog.mode === "source" && <label>原著名称 *<input autoFocus maxLength={200} value={sourceName} onChange={(event) => setSourceName(event.target.value)} placeholder="例如：小球下山"/></label>}
      <label>章节标题 *<input autoFocus={dialog.mode === "chapter"} maxLength={300} value={chapterTitle} onChange={(event) => setChapterTitle(event.target.value)} placeholder="例如：第一章 下山"/></label>
      <label>章节正文<textarea value={chapterContent} onChange={(event) => setChapterContent(event.target.value)} placeholder="可以先留空，建立后继续编辑"/></label>
      <footer><button onClick={() => setDialog(null)} disabled={busy}>取消</button><button className="primary" onClick={() => run(createManualContent)} disabled={busy || !chapterTitle.trim() || (dialog.mode === "source" && !sourceName.trim())}>{dialog.mode === "source" ? "建立原著和第一章" : "新增章节"}</button></footer>
    </div></div>}
  </section>;
}
