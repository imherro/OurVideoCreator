import { useEffect, useMemo, useRef, useState } from "react";
import { BookOpen, CheckSquare2, FilePlus2, Plus, RefreshCw, Save, Search, Sparkles, Square, Trash2, Upload, X } from "lucide-react";

type AnyValue = any;
type CreateDialog = { mode: "source" | "chapter"; sourceId?: string; sourceName?: string };

export function SourceLibraryPage({
  productionId, projectId, providers, defaultTarget, refreshKey = 0, request, notify, report,
}: {
  productionId: string; projectId: string;
  providers: AnyValue[]; defaultTarget?: AnyValue; refreshKey?: number;
  request: (path: string, options?: RequestInit) => Promise<AnyValue>;
  notify: (message: string) => void; report: (error: unknown) => void;
}) {
  const [sources, setSources] = useState<AnyValue[]>([]);
  const [chapters, setChapters] = useState<AnyValue[]>([]);
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
  const textProviders = useMemo(
    () => providers.filter((provider) => !provider.kind || provider.kind === "text"),
    [providers],
  );
  const configuredDefault = textProviders.find((provider) => provider.id === defaultTarget?.providerId);
  const defaultProviderId = configuredDefault?.id || "";
  const defaultModelId = defaultTarget?.modelId || configuredDefault?.models?.text || configuredDefault?.model || "";
  const [providerId, setProviderId] = useState(defaultProviderId);
  const [model, setModel] = useState(defaultModelId);
  const chapter = chapters.find((item) => item.id === active);
  const activeSource = sources.find((item) => item.id === chapter?.source_id) || sources[0];

  async function load() {
    const [nextSources, nextChapters, nextEvents] = await Promise.all([
      request(`/productions/${productionId}/sources`),
      request(`/productions/${productionId}/chapters`),
      request(`/productions/${productionId}/source-events`),
    ]);
    setSources(nextSources);
    setChapters(nextChapters);
    setEvents(nextEvents);
    setActive((value) => value && nextChapters.some((item: AnyValue) => item.id === value) ? value : nextChapters[0]?.id || "");
  }

  useEffect(() => { setSelected(new Set()); void load().catch(report); }, [productionId, refreshKey]);
  useEffect(() => {
    setProviderId(defaultProviderId);
    setModel(defaultModelId);
  }, [productionId, projectId, defaultTarget?.providerId, defaultTarget?.modelId]);

  function run(action: () => Promise<void>) { void action().catch(report); }
  function openCreateSource() {
    setSourceName("");
    setChapterTitle("第一章");
    setChapterContent("");
    setDialog({ mode: "source" });
  }
  function openCreateChapter() {
    const source = sources.find((item) => item.id === chapter?.source_id) || sources[0];
    if (!source) return;
    setChapterTitle(`第 ${Number(source.chapter_count || 0) + 1} 章`);
    setChapterContent("");
    setDialog({ mode: "chapter", sourceId: source.id, sourceName: source.title });
  }
  async function createManualContent() {
    if (!dialog || !chapterTitle.trim() || (dialog.mode === "source" && !sourceName.trim())) return;
    setBusy(true);
    try {
      let sourceId = dialog.sourceId;
      if (dialog.mode === "source") {
        const source = await request(`/productions/${productionId}/sources`, {
          method: "POST", body: JSON.stringify({ title: sourceName.trim(), type: "manual", metadata: {} }),
        });
        sourceId = source.id;
      }
      const created = await request(`/productions/${productionId}/sources/${sourceId}/chapters`, {
        method: "POST", body: JSON.stringify({ title: chapterTitle.trim(), content: chapterContent }),
      });
      const mode = dialog.mode;
      setDialog(null);
      await load();
      setActive(created.id);
      notify(mode === "source" ? "原著和第一章已建立" : "章节已新增");
    } finally { setBusy(false); }
  }
  async function importFile(file: File) {
    setBusy(true);
    try {
      await request(`/productions/${productionId}/sources/import`, { method: "POST", body: JSON.stringify({
        title: file.name.replace(/\.(txt|md|markdown)$/i, ""),
        type: /\.md|\.markdown$/i.test(file.name) ? "markdown" : "txt",
        content: await file.text(), metadata: { filename: file.name },
      }) });
      await load();
      notify(`已导入 ${file.name}`);
    } finally { setBusy(false); }
  }
  async function saveChapter() {
    if (!chapter) return;
    setBusy(true);
    try {
      const saved = await request(`/productions/${productionId}/chapters/${chapter.id}`, {
        method: "PUT", body: JSON.stringify({ title: chapter.title, content: chapter.content, revision: chapter.revision }),
      });
      setChapters((items) => items.map((item) => item.id === saved.id ? saved : item));
      notify("章节已保存");
    } finally { setBusy(false); }
  }
  async function deleteActiveSource() {
    if (!activeSource) return;
    if (!window.confirm(`将原著“${activeSource.title}”及其 ${activeSource.chapter_count || 0} 个章节移入回收站？\n章节和已提取事件会暂时隐藏，恢复原著后会重新出现。`)) return;
    setBusy(true);
    try {
      await request(`/productions/${productionId}/sources/${activeSource.id}`, { method: "DELETE" });
      setSelected(new Set());
      await load();
      notify(`原著“${activeSource.title}”已移入回收站`);
    } finally { setBusy(false); }
  }
  async function deleteSelectedChapters() {
    if (!selected.size) return;
    if (!window.confirm(`将选中的 ${selected.size} 个章节移入回收站？\n对应的已提取事件会暂时隐藏，恢复章节后会重新出现。`)) return;
    setBusy(true);
    try {
      await request(`/productions/${productionId}/chapters/trash`, {
        method: "POST", body: JSON.stringify({ chapter_ids: [...selected] }),
      });
      const count = selected.size;
      setSelected(new Set());
      await load();
      notify(`已将 ${count} 个章节移入回收站`);
    } finally { setBusy(false); }
  }
  async function extract() {
    if (!selected.size) return;
    const provider = textProviders.find((item) => item.id === providerId);
    const modelId = model || provider?.models?.text || provider?.model || "";
    if (!provider) throw new Error("请先为作品配置外部文本 Provider；系统不会自动选择其他付费模型");
    if (!modelId) throw new Error("请填写文本模型 ID");
    if (!window.confirm(`将分析 ${selected.size} 个章节\n模型：${provider.name} / ${modelId}\n确认创建文本任务？`)) return;
    setBusy(true);
    try {
      await request(`/productions/${productionId}/source-extractions`, { method: "POST", body: JSON.stringify({
        project_id: projectId, chapter_ids: [...selected], provider: providerId, model: modelId,
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
        <button onClick={() => fileRef.current?.click()} disabled={busy}><Upload size={15}/>导入 TXT / Markdown</button>
        <button onClick={openCreateSource} disabled={busy}><FilePlus2 size={15}/>新建原著</button>
        <button onClick={openCreateChapter} disabled={busy || !sources.length}><Plus size={15}/>新增章节</button>
        <button className="danger-button" onClick={() => run(deleteActiveSource)} disabled={busy || !activeSource} title="移入回收站，可恢复"><Trash2 size={15}/>移除当前原著</button>
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
        <div className="chapter-editor-head"><input value={chapter.title} onChange={(event) => setChapters((items) => items.map((item) => item.id === chapter.id ? { ...item, title: event.target.value } : item))}/><button disabled={busy} onClick={() => run(saveChapter)}><Save size={14}/>保存章节</button></div>
        <textarea className="chapter-editor" value={chapter.content} onChange={(event) => setChapters((items) => items.map((item) => item.id === chapter.id ? { ...item, content: event.target.value } : item))}/>
        <h3>已提取事件</h3>{events.filter((item) => item.chapter_id === chapter.id).map((item) => <article className="source-event" key={item.id}><b>{item.event_order}. {item.summary}</b><small>{item.importance} · {item.emotion || "无情绪标注"} · {item.characters.join("、") || "无明确人物"}</small></article>)}
      </> : <div className="empty-state"><BookOpen/><h3>导入或新建原著</h3></div>}</main>
      <aside className="source-analysis">
        <h3>AI 事件提取</h3><p>作品级分析 · 已选 {selected.size} 章。任务失败时保留已有事件。</p>
        <label>文本服务<select value={providerId} onChange={(event) => { setProviderId(event.target.value); const provider = textProviders.find((item) => item.id === event.target.value); setModel(provider?.models?.text || provider?.model || ""); }}><option value="" disabled>请选择外部 Provider</option>{textProviders.map((provider) => <option key={provider.id} value={provider.id}>外部 API · {provider.name}</option>)}</select></label>
        <label>模型 ID<input value={model} placeholder="外部模型 ID" onChange={(event) => setModel(event.target.value)}/></label>
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
