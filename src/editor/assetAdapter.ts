import {
  AudioElement,
  ImageElement,
  VideoElement,
  type Size,
  type TimelineEditor,
  type Track,
  type TrackElement,
} from "@twick/timeline";
import type { MediaItem } from "@twick/video-editor";
import type { EditorAsset } from "./editorDocument";

export const TWICK_MEDIA_DRAG_TYPE = "application/x-twick-media";

export function assetToMediaItem(asset: EditorAsset): MediaItem {
  const duration = Number(asset.metadata?.duration);
  return {
    id: asset.id,
    name: asset.name,
    type: asset.kind,
    url: asset.url,
    previewUrl: asset.metadata?.thumbnail_url,
    thumbnail: asset.metadata?.thumbnail_url,
    duration: Number.isFinite(duration) && duration > 0 ? duration * 1000 : undefined,
    width: Number(asset.metadata?.width) || undefined,
    height: Number(asset.metadata?.height) || undefined,
    source: "user",
    origin: "my-video-creator",
    metadata: { ...asset.metadata, assetId: asset.id, title: asset.name },
  };
}

export function assetToTwickElement(
  asset: EditorAsset,
  resolution: Size,
): TrackElement {
  const mediaDuration = Number(asset.metadata?.duration);
  const duration = Number.isFinite(mediaDuration) && mediaDuration > 0
    ? mediaDuration
    : asset.kind === "image" ? 5 : 0;
  if (!duration) throw new Error(`素材“${asset.name}”缺少有效时长`);
  let element: TrackElement;
  if (asset.kind === "video") {
    element = new VideoElement(asset.url, resolution)
      .setMediaDuration(duration)
      .setFrame({ x: 0, y: 0, size: [resolution.width, resolution.height] });
  } else if (asset.kind === "audio") {
    element = new AudioElement(asset.url).setMediaDuration(duration);
  } else if (asset.kind === "image") {
    element = new ImageElement(asset.url, resolution)
      .setFrame({ x: 0, y: 0, size: [resolution.width, resolution.height] });
  } else {
    throw new Error(`不支持加入剪辑器的素材类型：${asset.kind}`);
  }
  element.setName(asset.name);
  element.setStart(0).setEnd(duration);
  element.setMetadata({
    assetId: asset.id,
    assetSource: "my-video-creator",
  });
  element.setProps({ ...element.getProps(), srcAssetId: asset.id });
  return element;
}

function trackType(asset: EditorAsset) {
  return asset.kind === "audio" ? "audio" : "element";
}

function nextTrackName(editor: TimelineEditor, type: "element" | "audio") {
  const count = editor.getTracksByType(type).length + (type === 'element' ? editor.getTracksByType('video').length : 0);
  return `${type === "element" ? "V" : "A"}${count + 1}`;
}

/**
 * Add a canonical project asset without asking Twick to reload protected media
 * metadata. Twick's stock helper swallows that failure and leaves an empty
 * Track_* row behind, so MyVideoCreator initializes the element from the asset
 * record and performs the validated track insertion itself.
 */
export function addAssetToTimeline(
  editor: TimelineEditor,
  asset: EditorAsset,
  resolution: Size,
  options: { start?: number; targetTrack?: Track; append?: boolean } = {},
) {
  const type = trackType(asset);
  const candidates = editor.getTracksByType(type);
  let target = options.targetTrack?.getType() === type ? options.targetTrack : candidates[0];
  if (!target) target = editor.addTrack(nextTrackName(editor, type), type);

  const element = assetToTwickElement(asset, resolution);
  const duration = element.getDuration();
  const appendStart = Math.max(0, ...target.getElements().map((item) => item.getEnd()));
  const start = Math.max(0, options.append ? appendStart : Number(options.start) || 0);
  element.setStart(start).setEnd(start + duration);

  try {
    target.createFriend().addElement(element);
  } catch {
    target = editor.addTrack(nextTrackName(editor, type), type);
    target.createFriend().addElement(element);
  }
  editor.refresh();
  return element;
}
