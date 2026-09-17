import { updateShot } from "./shotSync.ts";
import { visualBibleOf, type FilmBibleDocument, type VisualKind } from "./filmBible/types.ts";

type Value = Record<string, any>;

export function shotIdentity(shot: Value) {
  return String(shot.uid || shot.id || "");
}

export function updateStoryboardShot<
  T extends FilmBibleDocument & { nodes: Value[]; edges: Value[] },
>(document: T, uid: string, patch: Value): T {
  const shot = document.shots.find((item) => shotIdentity(item) === uid);
  if (!shot) throw new Error("目标分镜不存在");
  return updateShot(document as any, shot.id, patch) as T;
}

export function moveStoryboardShot<T extends FilmBibleDocument>(
  document: T,
  uid: string,
  offset: -1 | 1,
): T {
  const shots = [...document.shots];
  const index = shots.findIndex((item) => shotIdentity(item) === uid);
  if (index < 0) throw new Error("目标分镜不存在");
  const target = index + offset;
  if (target < 0 || target >= shots.length) return document;
  [shots[index], shots[target]] = [shots[target], shots[index]];
  return { ...document, shots };
}

export function createStoryboardShot<T extends FilmBibleDocument>(
  document: T,
  newId: () => string,
): T {
  const uid = `shot-${newId()}`;
  return {
    ...document,
    shots: [
      ...document.shots,
      {
        id: uid,
        uid,
        duration: 3,
        videoReferenceMode: (document as Record<string,any>).videoReferenceMode && (document as Record<string,any>).videoReferenceMode !== 'legacy' ? undefined : 'multimodal',
        scene: "",
        characters: [],
        action: "",
        emotion: "",
        camera: "中景，固定机位",
        audio: "",
        image_prompt: "",
        video_prompt: "",
        assetBindings: { characters: [], scene: null, props: [] },
        pipeline: {},
      },
    ],
  };
}

export type ShotReferenceProjection = {
  group: "characters" | "scene" | "props";
  role: string;
  versionId: string;
  cardId: string;
  cardName: string;
  kind: VisualKind;
  version: number;
  status: string;
  primaryAssetId?: string;
};

export function projectShotReferences(
  document: FilmBibleDocument,
  shot: Value,
): ShotReferenceProjection[] {
  const visual = visualBibleOf(document);
  const bindings = shot.assetBindings || {};
  const grouped: Array<[ShotReferenceProjection["group"], Value[]]> = [
    ["characters", Array.isArray(bindings.characters) ? bindings.characters : []],
    ["scene", bindings.scene?.versionId ? [bindings.scene] : []],
    ["props", Array.isArray(bindings.props) ? bindings.props : []],
  ];
  return grouped.flatMap(([group, values]) =>
    values.flatMap((binding) => {
      const version = visual.versions[binding.versionId];
      const card = version ? visual.cards[version.cardId] : undefined;
      if (!version || !card) return [];
      const primary = version.references.find((item) => item.role === "primary");
      return [{
        group,
        role: String(binding.role || card.name),
        versionId: version.id,
        cardId: card.id,
        cardName: card.name,
        kind: card.kind,
        version: version.version,
        status: version.status,
        primaryAssetId: primary?.assetId,
      }];
    }),
  );
}

export function selectedShotImageNodeIds(document: FilmBibleDocument, uids: string[]) {
  const selected = new Set(uids);
  return document.shots
    .filter((shot) => selected.has(shotIdentity(shot)))
    .map((shot) => shot.imageNode || shot.pipeline?.imageNodeId)
    .filter((value): value is string => typeof value === "string" && Boolean(value));
}

export function selectedShotVideoNodeIds(document: FilmBibleDocument, uids: string[]) {
  const selected = new Set(uids);
  return document.shots
    .filter((shot) => selected.has(shotIdentity(shot)))
    .map((shot) => shot.videoNode || shot.pipeline?.videoNodeId)
    .filter((value): value is string => typeof value === "string" && Boolean(value));
}
