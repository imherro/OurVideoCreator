import test from "node:test";
import assert from "node:assert/strict";
import { AudioElement, ImageElement, Track, VideoElement } from "@twick/timeline";
import { addAssetToTimeline, assetToTwickElement } from "../src/editor/assetAdapter.ts";

const resolution = { width: 1280, height: 720 };

test("asset adapter initializes protected media without a second metadata request", () => {
  const video = assetToTwickElement({
    id: "asset-video",
    name: "镜头.mp4",
    kind: "video",
    url: "/api/assets/asset-video/file",
    metadata: { duration: 5.2, width: 1280, height: 720 },
  }, resolution);
  assert.ok(video instanceof VideoElement);
  assert.equal(video.getDuration(), 5.2);
  assert.equal(video.getMediaDuration(), 5.2);
  assert.deepEqual(video.getFrame(), { x: 0, y: 0, size: [1280, 720] });
  assert.equal(video.getMetadata().assetId, "asset-video");

  const audio = assetToTwickElement({
    id: "asset-audio", name: "音乐.wav", kind: "audio", url: "/audio", metadata: { duration: 8 },
  }, resolution);
  assert.ok(audio instanceof AudioElement);
  assert.equal(audio.getDuration(), 8);

  const image = assetToTwickElement({
    id: "asset-image", name: "定妆图.png", kind: "image", url: "/image", metadata: {},
  }, resolution);
  assert.ok(image instanceof ImageElement);
  assert.equal(image.getDuration(), 5);
});

test("asset adapter reports media records that cannot form a valid clip", () => {
  assert.throws(() => assetToTwickElement({
    id: "broken", name: "坏素材.mp4", kind: "video", url: "/broken", metadata: {},
  }, resolution), /缺少有效时长/);
});

test("project assets append to a typed track and remain movable clips", () => {
  const tracks = [];
  let refreshes = 0;
  const editor = {
    getTracksByType: (type) => tracks.filter((track) => track.getType() === type),
    addTrack: (name, type) => {
      const track = new Track(name, type);
      tracks.push(track);
      return track;
    },
    refresh: () => { refreshes += 1; },
  };
  const asset = {
    id: "asset-video",
    name: "镜头.mp4",
    kind: "video",
    url: "/api/assets/asset-video/file",
    metadata: { duration: 5.2 },
  };
  const first = addAssetToTimeline(editor, asset, resolution, { append: true });
  const second = addAssetToTimeline(editor, { ...asset, id: "asset-video-2" }, resolution, { append: true });
  assert.equal(tracks.length, 1);
  assert.equal(tracks[0].getType(), "element");
  assert.deepEqual([first.getStart(), first.getEnd()], [0, 5.2]);
  assert.deepEqual([second.getStart(), second.getEnd()], [5.2, 10.4]);
  assert.equal(refreshes, 2);
});
