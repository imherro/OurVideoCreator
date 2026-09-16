import test from "node:test";
import assert from "node:assert/strict";
import {
  attachAssetReferences,
  editorResolution,
  readEditorTimeline,
} from "../src/editor/editorDocument.ts";

test("missing editor state starts as a fresh Twick project", () => {
  const first = readEditorTimeline();
  const second = readEditorTimeline();
  assert.deepEqual(first.tracks, []);
  assert.equal(first.version, 1);
  first.tracks.push({ id: "changed", name: "changed", elements: [] });
  assert.deepEqual(second.tracks, []);
});

test("persisted Twick media keeps the canonical MyVideoCreator asset id", () => {
  const timeline = {
    version: 3,
    tracks: [
      {
        id: "t-v1",
        name: "V1",
        elements: [
          {
            id: "e-shot-1",
            type: "video",
            s: 0,
            e: 5,
            props: { src: "/api/assets/asset-video/file", time: 1 },
          },
        ],
      },
    ],
  };
  const assets = [
    {
      id: "asset-video",
      name: "镜头 1",
      kind: "video",
      url: "/api/assets/asset-video/file",
      metadata: { duration: 6.5, width: 1280, height: 720 },
    },
  ];

  const persisted = attachAssetReferences(timeline, assets);
  const element = persisted.tracks[0].elements[0];
  assert.equal(element.metadata.assetId, "asset-video");
  assert.equal(element.props.srcAssetId, "asset-video");
  assert.equal(persisted.assets["asset-video"].duration, 6500);
  assert.equal(timeline.tracks[0].elements[0].metadata, undefined);
});

test("persisted asset ids rebind stale media URLs to the current project endpoint", () => {
  const timeline = attachAssetReferences(
    {
      version: 2,
      tracks: [{ id: "t1", name: "V1", elements: [{
        id: "e1", type: "video", s: 0, e: 1,
        props: { src: "http://old-host/api/assets/a1/file", srcAssetId: "a1" },
        metadata: { assetId: "a1" },
      }] }],
    },
    [{ id: "a1", name: "shot", kind: "video", url: "/api/assets/a1/file", metadata: { duration: 1 } }],
  );
  assert.equal(timeline.tracks[0].elements[0].props.src, "/api/assets/a1/file");
  assert.equal(timeline.assets.a1.id, "a1");
});

test("a regenerated shot asset does not replace an existing timeline clip reference", () => {
  const timeline = attachAssetReferences(
    {
      version: 2,
      tracks: [{ id: "v1", name: "V1", elements: [{
        id: "clip-1", type: "video", s: 0, e: 2,
        props: { src: "/api/assets/old/file", srcAssetId: "old" },
        metadata: { assetId: "old", shotId: "shot-1" },
      }] }],
    },
    [
      { id: "old", name: "旧版本", kind: "video", url: "/api/assets/old/file", metadata: { duration: 2 } },
      { id: "new", name: "重新生成版本", kind: "video", url: "/api/assets/new/file", metadata: { duration: 2 } },
    ],
  );
  const clip = timeline.tracks[0].elements[0];
  assert.equal(clip.metadata.assetId, "old");
  assert.equal(clip.props.srcAssetId, "old");
  assert.equal(clip.props.src, "/api/assets/old/file");
  assert.equal(timeline.assets.new, undefined);
});

test("legacy filter names migrate to Twick preview-compatible filter ids", () => {
  const timeline = attachAssetReferences(
    {
      version: 2,
      tracks: [{ id: "t1", name: "V1", elements: [
        { id: "e1", type: "image", s: 0, e: 1, props: { mediaFilter: "grayscale" } },
        { id: "e2", type: "image", s: 1, e: 2, props: { mediaFilter: "contrast" } },
      ] }],
    },
    [],
  );
  assert.equal(timeline.tracks[0].elements[0].props.mediaFilter, "blackWhite");
  assert.equal(timeline.tracks[0].elements[1].props.mediaFilter, "cinematic");
});

test("editor resolution follows the project aspect ratio", () => {
  assert.deepEqual(editorResolution("16:9"), { width: 1280, height: 720 });
  assert.deepEqual(editorResolution("9:16"), { width: 720, height: 1280 });
  assert.deepEqual(editorResolution("1:1"), { width: 1080, height: 1080 });
});

test("title tracks use Twick's renderable element kind without changing titles or other tracks", () => {
  const timeline = {version: 3, tracks: [
    {id: 'title-track', type: 'text', elements: [
      {id: 'title', type: 'text', s: 0, e: 3, props: {text: 'Keep title'}}]},
    {id: 'video-track', type: 'video', elements: []},
  ]};
  const result = attachAssetReferences(timeline, []);
  assert.equal(result.tracks[0].type, 'element');
  assert.deepEqual(result.tracks[0].elements, timeline.tracks[0].elements);
  assert.equal(result.tracks[1].type, 'video');
  assert.equal(timeline.tracks[0].type, 'text');
  assert.deepEqual(attachAssetReferences(result, []), result);
});
