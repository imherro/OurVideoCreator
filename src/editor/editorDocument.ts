import type { ElementJSON, ProjectJSON } from "@twick/timeline";

export type EditorAsset = {
  id: string;
  name: string;
  kind: string;
  url: string;
  created?: number;
  metadata: Record<string, any>;
};

export type EditorDocument = {
  version: 1;
  timeline: ProjectJSON;
};

export const EMPTY_EDITOR_TIMELINE: ProjectJSON = {
  tracks: [],
  version: 1,
  backgroundColor: "#000000",
  metadata: {
    custom: {
      host: "my-video-creator",
      schema: "mvc-editor-v1",
    },
  },
};

const LEGACY_FILTER_ALIASES: Record<string, string> = {
  grayscale: "blackWhite",
  contrast: "cinematic",
};

export function readEditorTimeline(editor?: EditorDocument): ProjectJSON {
  if (!editor || editor.version !== 1 || !Array.isArray(editor.timeline?.tracks)) {
    return structuredClone(EMPTY_EDITOR_TIMELINE);
  }
  return structuredClone(editor.timeline);
}

function mediaAssetForElement(
  element: ElementJSON,
  assetsByUrl: Map<string, EditorAsset>,
) {
  const source = element.props?.src;
  return typeof source === "string" ? assetsByUrl.get(source) : undefined;
}

/**
 * Twick creates dragged media from its URL. Re-attach the host asset id before
 * persistence so every timeline element remains connected to the canonical
 * MyVideoCreator asset record.
 */
export function attachAssetReferences(
  timeline: ProjectJSON,
  assets: EditorAsset[],
): ProjectJSON {
  const assetsByUrl = new Map(assets.map((asset) => [asset.url, asset]));
  const assetsById = new Map(assets.map((asset) => [asset.id, asset]));
  const referencedAssets = new Set<string>();
  const tracks = timeline.tracks.map((track) => ({
    ...track,
    // Text is an element kind, not a renderer track kind in Twick.
    ...(track.type === "text" ? { type: "element" } : {}),
    elements: track.elements.map((element) => {
      const currentFilter = element.props?.mediaFilter;
      const normalized = typeof currentFilter === "string" && LEGACY_FILTER_ALIASES[currentFilter]
        ? { ...element, props: { ...element.props, mediaFilter: LEGACY_FILTER_ALIASES[currentFilter] } }
        : element;
      const linkedId = normalized.metadata?.assetId || normalized.props?.srcAssetId;
      const asset =
        (typeof linkedId === "string" ? assetsById.get(linkedId) : undefined) ||
        mediaAssetForElement(normalized, assetsByUrl);
      if (!asset) return normalized;
      referencedAssets.add(asset.id);
      return {
        ...normalized,
        props: { ...normalized.props, src: asset.url, srcAssetId: asset.id },
        metadata: {
          ...(normalized.metadata || {}),
          assetId: asset.id,
          assetSource: "my-video-creator",
        },
      };
    }),
  }));

  const manifest = Object.fromEntries(
    assets
      .filter((asset) => referencedAssets.has(asset.id))
      .map((asset) => [
        asset.id,
        {
          id: asset.id,
          type: asset.kind,
          url: asset.url,
          duration:
            Number.isFinite(Number(asset.metadata?.duration)) &&
            Number(asset.metadata.duration) > 0
              ? Number(asset.metadata.duration) * 1000
              : undefined,
          width: Number(asset.metadata?.width) || undefined,
          height: Number(asset.metadata?.height) || undefined,
          source: "user" as const,
          origin: "my-video-creator",
        },
      ]),
  );

  return {
    ...timeline,
    tracks,
    assets: manifest,
  };
}

export function editorResolution(ratio: string) {
  if (ratio === "9:16") return { width: 720, height: 1280 };
  if (ratio === "1:1") return { width: 1080, height: 1080 };
  return { width: 1280, height: 720 };
}
