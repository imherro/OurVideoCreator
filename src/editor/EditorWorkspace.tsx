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
import {timelineWorkspaceDuration, withTimelineWorkspaceDuration} from './timelineDuration';
import { TIMELINE_DROP_MEDIA_TYPE } from "@twick/video-editor";
import type {EpisodeSummary} from '../app/production';
import "./editorWorkspace.css";

type EditorWorkspaceProps = {
  projectId: string;
  episodes: EpisodeSummary[];
  productionName: string;
  episodeLabel: string;
  editor?: EditorDocument;
  assets: EditorAsset[];
  ratio: string;
  duration: number;
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

function TimelineDurationFloor({projectDuration}: {projectDuration: number}) {
  const {editor, totalDuration, changeLog} = useTimelineContext();
  const [value, setValue] = useState(() => timelineWorkspaceDuration(editor.getProject(), projectDuration));
  const dirty = useRef(false);
  useEffect(() => {
    const floor = timelineWorkspaceDuration(editor.getProject(), projectDuration);
    if (!dirty.current) setValue(floor);
    // View state only: loading a remote document must never publish a write.
    if (Math.abs(totalDuration - floor) > 0.001) editor.getContext().setTotalDuration(floor);
  }, [changeLog, editor, projectDuration, totalDuration]);
  const commit = () => {
    if (!dirty.current) return;
    dirty.current = false;
    const project = withTimelineWorkspaceDuration(editor.getProject(), value, projectDuration);
    setValue(timelineWorkspaceDuration(project, projectDuration));
    editor.setMetadata(project.metadata || {});
  };
  return <label className="mvc-editor-duration" title="工作区长度不裁切素材，也不延长导出；最短为影片目标时长及现有内容长度">
    时间线 <input aria-label="时间线工作区时长" type="number" min={5} step={1} value={value}
      onChange={event => {dirty.current = true; setValue(Number(event.target.value));}}
      onBlur={commit} onKeyDown={event => {if (event.key === 'Enter') event.currentTarget.blur();}} /> 秒
  </label>;
}

function EditorSurface({
  projectId,
  episodes,
  productionName,
  episodeLabel,
  initialTimeline,
  assets,
  shots,
  nodes,
  audioId,
  musicVolume,
  duration,
  onChange,
  onExport,
}: {
  projectId: string;
  episodes: EpisodeSummary[];
  productionName: string;
  episodeLabel: string;
  initialTimeline: ProjectJSON;
  assets: EditorAsset[];
  shots: Record<string, any>[];
  nodes: Record<string, any>[];
  audioId?: string;
  musicVolume?: number;
  duration: number;
  onChange: EditorWorkspaceProps["onChange"];
  onExport: EditorWorkspaceProps["onExport"];
}) {
  const { editor, videoResolution, changeLog, setSelectedItem } = useTimelineContext();
  const { getCurrentTime, setCurrentTime, setSeekTime } = useLivePlayerContext();
  const [durationMode, setDurationMode] = useState<'preserve' | 'fit'>('preserve');
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
        const type = track.getType() === 'element' && track.getElements().some(item => ['video', 'image'].includes(item.getType())) ? 'video' : track.getType();
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
      { shots, nodes, assets, resolution: videoResolution, audioId, musicVolume, durationMode, targetDuration: duration },
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
    setCurrentTime(0);
    setSeekTime(0);
    setMessage(`已完整保留 ${plan.clipCount} 个镜头，共 ${plan.outputDuration.toFixed(2)} 秒${durationMode === 'fit' ? `（画面与已采纳对白同步 ${plan.playbackRate.toFixed(2)} 倍速）` : ''}`);
  }

  return (
    <>
      <TimelinePersistence initialTimeline={initialTimeline} assets={assets} onChange={onChange} />
      <EditorShortcuts onMessage={setMessage} />
      <div className="mvc-editor-actionbar">
        <button className="primary compact" onClick={generateInitialEdit}>
          <Sparkles size={15} /> 生成初剪
        </button>
        <label className="mvc-editor-duration">初剪
          <select aria-label="初剪时长模式" value={durationMode} onChange={event => setDurationMode(event.target.value as 'preserve' | 'fit')}>
            <option value="preserve">完整镜头</option>
            <option value="fit">匹配 {duration} 秒</option>
          </select>
        </label>
        <TimelineDurationFloor projectDuration={duration} />
        <span><b>{productionName} · {episodeLabel}</b>　{message}</span>
        <EditorToolbar assets={assets} onMessage={setMessage} onExport={onExport} />
      </div>
      <div className="mvc-editor-surface" ref={surfaceRef} onDragOverCapture={handleDragOver} onDropCapture={handleDrop}>
        <VideoEditor
          leftPanel={<ProjectAssetPanel currentProjectId={projectId} episodes={episodes} assets={assets} shots={shots} onMessage={setMessage} />}
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
  episodes,
  productionName,
  episodeLabel,
  editor,
  assets,
  ratio,
  duration,
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
            projectId={projectId}
            episodes={episodes}
            initialTimeline={initialTimeline}
            productionName={productionName}
            episodeLabel={episodeLabel}
            assets={assets}
            shots={shots}
            nodes={nodes}
            audioId={audioId}
            musicVolume={musicVolume}
            duration={duration}
            onChange={onChange}
            onExport={onExport}
          />
        </TimelineProvider>
      </LivePlayerProvider>
    </section>
  );
}
