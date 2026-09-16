import { useEffect, useLayoutEffect, useMemo, useRef, useState, type DragEvent } from "react";
import { Sparkles } from "lucide-react";
import VideoEditor from "@twick/video-editor";
import "@twick/video-editor/dist/video-editor.css";
import { LivePlayerProvider } from "@twick/live-player";
import { useLivePlayerContext } from "@twick/live-player";
import {
  TimelineProvider,
  useTimelineContext,
  type ProjectJSON,
} from "@twick/timeline";
import { attachAssetReferences, editorResolution, readEditorTimeline } from "./editorDocument";
import type { EditorAsset, EditorDocument } from "./editorDocument";
import { ProjectAssetPanel } from "./ProjectAssetPanel";
import { EditorInspector } from "./EditorInspector";
import { EditorToolbar } from "./EditorToolbar";
import { EditorShortcuts } from "./EditorShortcuts";
import { planInitialTimeline } from "./initialTimeline";
import { addAssetToTimeline } from "./assetAdapter";
import { TimelineInputSync } from "./timelineInputSync";
import { TIMELINE_DROP_MEDIA_TYPE } from "@twick/video-editor";
import "./editorWorkspace.css";

type EditorWorkspaceProps = {
  projectId: string;
  productionName: string;
  episodeLabel: string;
  editor?: EditorDocument;
  assets: EditorAsset[];
  ratio: string;
  shots: Record<string, any>[];
  nodes: Record<string, any>[];
  audioId?: string;
  musicVolume?: number;
  onChange: (editor: EditorDocument) => void;
  onExport: (timeline: ProjectJSON) => void;
};

function TimelinePersistence({
  initialTimeline,
  assets,
  onChange,
}: {
  initialTimeline: ProjectJSON;
  assets: EditorAsset[];
  onChange: EditorWorkspaceProps["onChange"];
}) {
  const { editor, present, changeLog } = useTimelineContext();
  const sync = useRef<TimelineInputSync | null>(null);

  useLayoutEffect(() => {
    if (!present) return;
    if (!sync.current) {
      // Loading existing JSON may normalize track kinds/version. It is not a
      // user edit, particularly on a read-only collaborator's first render.
      sync.current = new TimelineInputSync(initialTimeline, attachAssetReferences(editor.getProject(), assets));
      return;
    }
    const timeline = sync.current.update(initialTimeline,
      () => attachAssetReferences(editor.getProject(), assets),
      (remote) => editor.loadProject(remote));
    if (timeline) onChange({ version: 1, timeline });
  }, [assets, changeLog, editor, initialTimeline, onChange, present]);

  return null;
}

function EditorSurface({
  productionName,
  episodeLabel,
  initialTimeline,
  assets,
  shots,
  nodes,
  audioId,
  musicVolume,
  onChange,
  onExport,
}: {
  productionName: string;
  episodeLabel: string;
  initialTimeline: ProjectJSON;
  assets: EditorAsset[];
  shots: Record<string, any>[];
  nodes: Record<string, any>[];
  audioId?: string;
  musicVolume?: number;
  onChange: EditorWorkspaceProps["onChange"];
  onExport: EditorWorkspaceProps["onExport"];
}) {
  const { editor, videoResolution, changeLog, setSelectedItem } = useTimelineContext();
  const { getCurrentTime } = useLivePlayerContext();
  const [message, setMessage] = useState("编辑会随当前项目自动保存");
  const surfaceRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const surface = surfaceRef.current;
    if (!surface) return;
    let frame = 0;
    const notifyLayout = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => window.dispatchEvent(new Event("resize")));
    };
    const observer = new ResizeObserver(notifyLayout);
    observer.observe(surface);
    notifyLayout();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, []);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const tracks = editor.getTimelineData()?.tracks || [];
      const counters = new Map<string, number>();
      surfaceRef.current?.querySelectorAll<HTMLElement>(".twick-track-header-content").forEach((header, index) => {
        const track = tracks[index];
        if (!track) return;
        const type = track.getType();
        const number = (counters.get(type) || 0) + 1;
        counters.set(type, number);
        const label = type === "video" ? `V${number}` : type === "audio" ? `A${number}` : type === "caption" ? "字幕" : type === "text" || type === "element" ? `T${number}` : "空";
        header.dataset.trackLabel = label;
        header.title = `${label} · ${track.getName() || "未命名轨道"}`;
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [changeLog, editor]);

  function draggedAsset(event: DragEvent<HTMLElement>) {
    try {
      const raw = event.dataTransfer.getData(TIMELINE_DROP_MEDIA_TYPE);
      const data = raw ? JSON.parse(raw) : null;
      return assets.find((asset) => asset.id === data?.assetId);
    } catch {
      return undefined;
    }
  }

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    if (event.dataTransfer.types.includes(TIMELINE_DROP_MEDIA_TYPE) && (event.target as Element).closest(".twick-track")) {
      event.preventDefault();
      event.dataTransfer.dropEffect = "copy";
    }
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    const trackNode = (event.target as Element).closest(".twick-track");
    const asset = draggedAsset(event);
    if (!trackNode || !asset) return;
    event.preventDefault();
    event.stopPropagation();
    const nodes = [...(surfaceRef.current?.querySelectorAll(".twick-track") || [])];
    const targetTrack = editor.getTimelineData()?.tracks[nodes.indexOf(trackNode)];
    try {
      const element = addAssetToTimeline(editor, asset, videoResolution, {
        start: getCurrentTime(),
        targetTrack,
      });
      setSelectedItem(element);
      setMessage(`已将“${asset.name}”放到 ${element.getStart().toFixed(2)} 秒`);
    } catch (cause: any) {
      setMessage(`加入失败：${cause?.message || String(cause)}`);
    }
  }

  function generateInitialEdit() {
    const plan = planInitialTimeline(
      { shots, nodes, assets, resolution: videoResolution, audioId, musicVolume },
      () => crypto.randomUUID(),
    );
    if (plan.issues.length) {
      setMessage(`暂未生成：${plan.issues.join("；")}`);
      return;
    }
    if (!plan.clipCount) {
      setMessage("暂未生成：分镜中还没有可用的视频素材");
      return;
    }
    const hasExistingEdit = (editor.getProject().tracks || []).some(
      (track) => track.elements.length > 0,
    );
    if (
      hasExistingEdit &&
      !window.confirm("生成初剪会替换当前剪辑时间线，是否继续？")
    ) {
      return;
    }
    editor.loadProject(plan.timeline);
    setMessage(`已按分镜顺序建立 ${plan.clipCount} 个镜头的初剪`);
  }

  return (
    <>
      <TimelinePersistence initialTimeline={initialTimeline} assets={assets} onChange={onChange} />
      <EditorShortcuts onMessage={setMessage} />
      <div className="mvc-editor-actionbar">
        <button className="primary compact" onClick={generateInitialEdit}>
          <Sparkles size={15} /> 生成初剪
        </button>
        <span><b>{productionName} · {episodeLabel}</b>　{message}</span>
        <EditorToolbar assets={assets} onMessage={setMessage} onExport={onExport} />
      </div>
      <div className="mvc-editor-surface" ref={surfaceRef} onDragOverCapture={handleDragOver} onDropCapture={handleDrop}>
        <VideoEditor
          leftPanel={<ProjectAssetPanel assets={assets} onMessage={setMessage} />}
          rightPanel={<EditorInspector assets={assets} />}
          editorConfig={{
            canvasMode: true,
            videoProps: { ...videoResolution, backgroundColor: "#000000" },
            fps: 24,
            timelineZoomConfig: { min: 0.25, max: 4, step: 0.25, default: 1 },
          }}
        />
      </div>
    </>
  );
}

export function EditorWorkspace({
  projectId,
  productionName,
  episodeLabel,
  editor,
  assets,
  ratio,
  shots,
  nodes,
  audioId,
  musicVolume,
  onChange,
  onExport,
}: EditorWorkspaceProps) {
  const initialTimeline = useMemo(
    () => attachAssetReferences(readEditorTimeline(editor), assets),
    [projectId, editor, assets],
  );
  const resolution = editorResolution(ratio);

  return (
    <section className="mvc-editor-workspace">
      <LivePlayerProvider key={`${projectId}:${ratio}`}>
        <TimelineProvider
          key={projectId}
          contextId={`mvc-editor-${projectId}`}
          initialData={initialTimeline}
          resolution={resolution}
          maxHistorySize={50}
          analytics={{ enabled: false }}
        >
          <EditorSurface
            initialTimeline={initialTimeline}
            productionName={productionName}
            episodeLabel={episodeLabel}
            assets={assets}
            shots={shots}
            nodes={nodes}
            audioId={audioId}
            musicVolume={musicVolume}
            onChange={onChange}
            onExport={onExport}
          />
        </TimelineProvider>
      </LivePlayerProvider>
    </section>
  );
}
