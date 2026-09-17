import {
  AudioElement,
  CaptionElement,
  ElementAnimation,
  ImageElement,
  TextElement,
  VideoElement,
  snapTime,
  type Size,
  type TimelineEditor,
  type Track,
  type TrackElement,
} from "@twick/timeline";
import type { EditorAsset } from "./editorDocument";

export type ElementFade = {
  videoIn: number;
  videoOut: number;
  audioIn: number;
  audioOut: number;
};
export type VolumePoint = { time: number; value: number };

const EMPTY_FADE: ElementFade = { videoIn: 0, videoOut: 0, audioIn: 0, audioOut: 0 };

export function findElement(editor: TimelineEditor, elementId: string): TrackElement {
  for (const track of editor.getTimelineData()?.tracks || []) {
    const element = track.getElementById(elementId);
    // Twick returns a readonly view although its mutation API expects the same
    // live object. Keep that library typing mismatch at this boundary.
    if (element) return element as TrackElement;
  }
  throw new Error(`找不到剪辑元素：${elementId}`);
}

function requireFiniteNumber(value: number, label: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) throw new Error(`${label}必须是有效数字`);
  return parsed;
}

function mediaElement(element: TrackElement): VideoElement | AudioElement | null {
  return element instanceof VideoElement || element instanceof AudioElement ? element : null;
}

function mvcMetadata(element: TrackElement) {
  const metadata = element.getMetadata() || {};
  const mvc =
    metadata.mvc && typeof metadata.mvc === "object"
      ? (metadata.mvc as Record<string, unknown>)
      : {};
  return { metadata, mvc };
}

export function collectSnapTargets(editor: TimelineEditor, exceptId?: string) {
  const targets = new Set<number>([0]);
  for (const track of editor.getTimelineData()?.tracks || []) {
    for (const element of track.getElements()) {
      if (element.getId() === exceptId) continue;
      targets.add(element.getStart());
      targets.add(element.getEnd());
    }
  }
  return [...targets].sort((a, b) => a - b);
}

export function moveElement(
  editor: TimelineEditor,
  elementId: string,
  start: number,
  options: { snap?: boolean; threshold?: number } = {},
) {
  const element = findElement(editor, elementId);
  const duration = element.getDuration();
  const requested = Math.max(0, requireFiniteNumber(start, "时间线起点"));
  const nextStart = options.snap === false
    ? requested
    : snapTime(requested, collectSnapTargets(editor, elementId), options.threshold ?? 0.1).time;
  editor.updateElements([
    { elementId, updates: { s: nextStart, e: nextStart + duration } },
  ]);
  if (Math.abs(findElement(editor, elementId).getStart() - nextStart) > 0.001) {
    throw new Error("移动失败，请检查是否与同轨片段重叠");
  }
  return nextStart;
}

export function setElementDuration(
  editor: TimelineEditor,
  elementId: string,
  duration: number,
) {
  const element = findElement(editor, elementId);
  const nextDuration = Math.max(0.1, requireFiniteNumber(duration, "片段长度"));
  const media = mediaElement(element);
  const playbackRate = media?.getPlaybackRate() || 1;
  const sourceIn = media?.getStartAt() || 0;
  const mediaDuration = media?.getMediaDuration() ?? Number.POSITIVE_INFINITY;
  if (
    Number.isFinite(mediaDuration) &&
    sourceIn + nextDuration * playbackRate > mediaDuration + 0.01
  ) {
    const availableDuration = Math.max(0, (mediaDuration - sourceIn) / playbackRate);
    throw new Error(`片段长度超出素材剩余时长 ${availableDuration.toFixed(2)} 秒`);
  }
  editor.updateElements([
    { elementId, updates: { e: element.getStart() + nextDuration } },
  ]);
  if (Math.abs(findElement(editor, elementId).getDuration() - nextDuration) > 0.001) {
    throw new Error("片段长度调整失败，请检查是否与同轨片段重叠");
  }
}

export function setMediaSourceIn(
  editor: TimelineEditor,
  elementId: string,
  sourceIn: number,
) {
  const element = findElement(editor, elementId);
  const media = mediaElement(element);
  if (!media) throw new Error("只有视频和音频支持素材入点");
  const nextSourceIn = Math.max(0, requireFiniteNumber(sourceIn, "素材入点"));
  const sourceEnd = nextSourceIn + media.getDuration() * media.getPlaybackRate();
  if (sourceEnd > media.getMediaDuration() + 0.01) {
    const latestSourceIn = Math.max(
      0,
      media.getMediaDuration() - media.getDuration() * media.getPlaybackRate(),
    );
    throw new Error(`素材入点过晚，当前片段最晚只能从 ${latestSourceIn.toFixed(2)} 秒开始`);
  }
  media.setStartAt(nextSourceIn);
  editor.updateElement(media);
}

export function setElementVolume(
  editor: TimelineEditor,
  elementId: string,
  volume: number,
) {
  const element = findElement(editor, elementId);
  const media = mediaElement(element);
  if (!media) throw new Error("只有视频和音频支持音量设置");
  media.setVolume(Math.max(0, Math.min(2, requireFiniteNumber(volume, "音量"))));
  editor.updateElement(media);
}

export function getVolumeAutomation(element: TrackElement): VolumePoint[] {
  const { mvc } = mvcMetadata(element);
  if (!Array.isArray(mvc.volumeKeyframes)) return [];
  return mvc.volumeKeyframes
    .filter((point): point is Record<string, unknown> => Boolean(point) && typeof point === "object")
    .map((point) => ({ time: Number(point.time), value: Number(point.value) }))
    .filter((point) => Number.isFinite(point.time) && Number.isFinite(point.value))
    .sort((a, b) => a.time - b.time);
}

export function parseVolumeAutomation(value: string, duration: number): VolumePoint[] {
  if (!value.trim()) return [];
  const points = value.split(/[,，]/).map((item) => {
    const match = item.trim().match(/^([\d.]+)\s*[:：]\s*([\d.]+)%?$/);
    if (!match) throw new Error("音量关键帧格式应为 时间:百分比，例如 0:30, 2:80");
    return { time: Number(match[1]), value: Number(match[2]) / 100 };
  });
  if (points.some((point) => !Number.isFinite(point.time) || point.time < 0 || point.time > duration || !Number.isFinite(point.value) || point.value < 0 || point.value > 2)) {
    throw new Error("音量关键帧必须位于片段内，音量范围为 0–200%");
  }
  points.sort((a, b) => a.time - b.time);
  if (points.some((point, index) => index > 0 && point.time <= points[index - 1].time)) {
    throw new Error("音量关键帧时间必须递增且不能重复");
  }
  return points;
}

export function setVolumeAutomation(editor: TimelineEditor, elementId: string, points: VolumePoint[]) {
  const element = findElement(editor, elementId);
  if (!mediaElement(element)) throw new Error("只有视频和音频支持音量自动化");
  const { metadata, mvc } = mvcMetadata(element);
  element.setMetadata({ ...metadata, mvc: { ...mvc, volumeKeyframes: structuredClone(points) } });
  editor.updateElement(element);
}

export function setPlaybackRate(
  editor: TimelineEditor,
  elementId: string,
  playbackRate: number,
) {
  const element = findElement(editor, elementId);
  const media = mediaElement(element);
  if (!media) throw new Error("只有视频和音频支持播放速度");
  const nextRate = Math.max(0.25, Math.min(4, requireFiniteNumber(playbackRate, "播放速度")));
  if (media.getStartAt() + media.getDuration() * nextRate > media.getMediaDuration() + 0.01) {
    throw new Error("当前片段长度与素材入点无法使用此播放速度");
  }
  media.setPlaybackRate(nextRate);
  editor.updateElement(media);
}

export function getElementFade(element: TrackElement): ElementFade {
  const { mvc } = mvcMetadata(element);
  const raw = mvc.fade && typeof mvc.fade === "object" ? mvc.fade as Record<string, unknown> : {};
  return {
    videoIn: Math.max(0, Number(raw.videoIn) || 0),
    videoOut: Math.max(0, Number(raw.videoOut) || 0),
    audioIn: Math.max(0, Number(raw.audioIn) || 0),
    audioOut: Math.max(0, Number(raw.audioOut) || 0),
  };
}

export function setElementFade(
  editor: TimelineEditor,
  elementId: string,
  patch: Partial<ElementFade>,
) {
  const element = findElement(editor, elementId);
  const duration = element.getDuration();
  const next = { ...EMPTY_FADE, ...getElementFade(element) };
  for (const key of Object.keys(patch) as (keyof ElementFade)[]) {
    next[key] = Math.max(0, Math.min(duration / 2, requireFiniteNumber(patch[key]!, "淡化时长")));
  }
  const { metadata, mvc } = mvcMetadata(element);
  element.setMetadata({ ...metadata, mvc: { ...mvc, fade: next } });
  if (element instanceof VideoElement || element instanceof ImageElement || element instanceof TextElement) {
    const hasIn = next.videoIn > 0;
    const hasOut = next.videoOut > 0;
    if (!hasIn && !hasOut) {
      if (element.getAnimation()?.getName() === "fade") element.setAnimation(undefined);
    } else {
      const previewDuration = hasIn && hasOut
        ? Math.min(next.videoIn, next.videoOut)
        : hasIn ? next.videoIn : next.videoOut;
      element.setAnimation(
        new ElementAnimation("fade")
          .setAnimate(hasIn && hasOut ? "both" : hasIn ? "enter" : "exit")
          .setInterval(previewDuration)
          .setDuration(element.getDuration()),
      );
    }
  }
  editor.updateElement(element);
}

export function setElementTransform(
  editor: TimelineEditor,
  elementId: string,
  patch: { x?: number; y?: number; width?: number; height?: number; rotation?: number; opacity?: number },
) {
  const element = findElement(editor, elementId);
  const position = element.getPosition();
  if (patch.x !== undefined || patch.y !== undefined) {
    element.setPosition({
      x: patch.x === undefined ? position.x : requireFiniteNumber(patch.x, "水平位置"),
      y: patch.y === undefined ? position.y : requireFiniteNumber(patch.y, "垂直位置"),
    });
  }
  if (patch.rotation !== undefined) element.setRotation(requireFiniteNumber(patch.rotation, "旋转角度"));
  if (patch.opacity !== undefined) {
    element.setOpacity(Math.max(0, Math.min(1, requireFiniteNumber(patch.opacity, "透明度"))));
  }
  if (patch.width !== undefined || patch.height !== undefined) {
    const frame = (element as VideoElement | ImageElement).getFrame?.();
    if (!frame?.size) throw new Error("当前元素不支持画面尺寸调整");
    (element as VideoElement | ImageElement).setFrame({
      ...frame,
      size: [
        Math.max(1, patch.width === undefined ? frame.size[0] : requireFiniteNumber(patch.width, "宽度")),
        Math.max(1, patch.height === undefined ? frame.size[1] : requireFiniteNumber(patch.height, "高度")),
      ],
    });
  }
  editor.updateElement(element);
}

export function setMediaFilter(editor: TimelineEditor, elementId: string, filter: string) {
  const element = findElement(editor, elementId);
  if (!(element instanceof VideoElement || element instanceof ImageElement)) {
    throw new Error("只有视频和图片支持画面滤镜");
  }
  element.setMediaFilter(filter);
  editor.updateElement(element);
}

export function setTextContent(editor: TimelineEditor, elementId: string, text: string) {
  const element = findElement(editor, elementId);
  if (!(element instanceof TextElement || element instanceof CaptionElement)) {
    throw new Error("当前元素不支持文字编辑");
  }
  element.setText(text);
  editor.updateElement(element);
}

export function setTextStyle(
  editor: TimelineEditor,
  elementId: string,
  patch: Record<string, unknown>,
) {
  const element = findElement(editor, elementId);
  if (!(element instanceof TextElement)) throw new Error("只有标题文字支持此样式");
  element.setProps({ ...element.getProps(), ...patch, text: element.getText() });
  editor.updateElement(element);
}

export function addTrack(editor: TimelineEditor, type: "video" | "audio" | "text" | "caption") {
  const trackType = type === "text" || type === "video" ? "element" : type;
  const index = editor.getTracksByType(trackType).length + 1;
  const prefix = type === "video" ? "V" : type === "audio" ? "A" : type === "caption" ? "字幕" : "T";
  return editor.addTrack(`${prefix}${index}`, trackType);
}

function preferredTrack(editor: TimelineEditor, type: string, name: string): Track {
  return editor.getTracksByType(type)[0] || editor.addTrack(name, type);
}

export async function addTextElement(
  editor: TimelineEditor,
  resolution: Size,
  options: { text?: string; start?: number; duration?: number } = {},
) {
  const start = Math.max(0, options.start || 0);
  const duration = Math.max(0.1, options.duration || 3);
  const element = new TextElement(options.text || "在右侧编辑标题", {
    fontSize: Math.round(resolution.height * 0.065),
    fontFamily: "Microsoft YaHei",
    fontWeight: 700,
    fill: "#ffffff",
    stroke: "#000000",
    strokeWidth: 2,
    textAlign: "center",
  })
    .setName("标题")
    .setStart(start)
    .setEnd(start + duration)
    .setPosition({ x: resolution.width * 0.15, y: resolution.height * 0.12 })
    .setMetadata({ mvc: { role: "title" } });
  const track = preferredTrack(editor, "element", "T1 · 标题");
  if (!(await editor.addElementToTrack(track, element))) {
    const fallback = addTrack(editor, "text");
    if (!(await editor.addElementToTrack(fallback, element))) throw new Error("标题加入时间线失败");
  }
  return element;
}

export async function addCaptionElements(
  editor: TimelineEditor,
  captions: Array<{ start: number; end: number; text: string }>,
) {
  if (!captions.length) throw new Error("字幕文件中没有可导入的字幕");
  const track = preferredTrack(editor, "caption", "字幕");
  track.setProps({
    ...track.getProps(),
    font: { family: "Microsoft YaHei", size: 42, weight: 700 },
    colors: { text: "#ffffff", outlineColor: "#000000", bgColor: "#000000" },
    capStyle: "default",
  });
  for (const caption of captions) {
    const element = new CaptionElement(caption.text, caption.start, caption.end)
      .setName("字幕")
      .setMetadata({ mvc: { role: "subtitle" } });
    if (!(await editor.addElementToTrack(track, element))) {
      throw new Error(`字幕在 ${caption.start.toFixed(2)} 秒处与现有字幕重叠`);
    }
  }
  editor.refresh();
  return captions.length;
}

export function setTransition(
  editor: TimelineEditor,
  fromElementId: string,
  toElementId: string | undefined,
  kind: string,
  duration: number,
) {
  if (!toElementId || kind === "none") {
    if (findElement(editor, fromElementId).getTransition()) editor.removeTransition(fromElementId);
    return;
  }
  const from = findElement(editor, fromElementId);
  const to = findElement(editor, toElementId);
  if (!(["video", "image"].includes(from.getType()) && ["video", "image"].includes(to.getType()))) {
    throw new Error("转场只能连接图像或视频片段");
  }
  if (to.getStart() < from.getStart()) throw new Error("转场目标必须位于当前片段之后");
  const nextDuration = Math.max(0.05, Math.min(from.getDuration() / 2, to.getDuration() / 2, requireFiniteNumber(duration, "转场时长")));
  if (!editor.addTransition(fromElementId, toElementId, kind, nextDuration)) throw new Error("设置转场失败");
}

export async function replaceElementAsset(
  editor: TimelineEditor,
  elementId: string,
  asset: EditorAsset,
) {
  const element = findElement(editor, elementId);
  if (element.getType() !== asset.kind || !["video", "image", "audio"].includes(asset.kind)) {
    throw new Error("替换素材必须与当前片段类型一致");
  }
  const oldFrame = element instanceof VideoElement || element instanceof ImageElement
    ? structuredClone(element.getFrame())
    : undefined;
  await (element as VideoElement | ImageElement | AudioElement).setSrc(asset.url);
  if (oldFrame && (element instanceof VideoElement || element instanceof ImageElement)) element.setFrame(oldFrame);
  const duration = Number(asset.metadata?.duration);
  if (element instanceof VideoElement || element instanceof AudioElement) {
    if (Number.isFinite(duration) && duration > 0) element.setMediaDuration(duration);
    if (element.getStartAt() + element.getDuration() * element.getPlaybackRate() > element.getMediaDuration()) {
      element.setStartAt(0);
      element.setEnd(element.getStart() + Math.max(0.1, element.getMediaDuration() / element.getPlaybackRate()));
    }
  }
  element.setProps({ ...element.getProps(), srcAssetId: asset.id });
  element.setMetadata({
    ...(element.getMetadata() || {}),
    assetId: asset.id,
    assetSource: "my-video-creator",
  });
  editor.updateElement(element);
}

export async function splitElement(editor: TimelineEditor, elementId: string, time: number) {
  const result = await editor.splitElement(findElement(editor, elementId), requireFiniteNumber(time, "切分位置"));
  if (!result.success) throw new Error("切分失败，请确认切分点位于片段内部");
  return result;
}

export function removeElement(editor: TimelineEditor, elementId: string) {
  if (!editor.removeElement(findElement(editor, elementId))) throw new Error("删除剪辑元素失败");
}
