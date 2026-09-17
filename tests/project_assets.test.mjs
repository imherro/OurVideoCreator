import test from "node:test";
import assert from "node:assert/strict";
import { filterEditorAssetsByEpisode, presentEditorAssets } from "../src/editor/projectAssets.ts";

test("collaboration UUID identities do not become enormous shot numbers", () => {
  const asset = {id: 'a', project_id: 'ep', name: '生成结果.mp4', kind: 'video', url: '/a',
    metadata: {node_id: 'video-a'}};
  const shot = {id: 'shot-123456abcdef', uid: '98765-uuid', videoNode: 'video-a', title: '开场'};
  assert.equal(presentEditorAssets([asset], [shot], 'ep')[0].title, '镜头 01 · 视频');
});

test("version groups cannot alias colon-delimited episode/node identities", () => {
  const assets = [
    {id: 'a', project_id: 'ep:a', name: 'a', kind: 'video', url: '/a', metadata: {node_id: 'b'}},
    {id: 'b', project_id: 'ep', name: 'b', kind: 'video', url: '/b', metadata: {node_id: 'a:b'}},
  ];
  for (const item of presentEditorAssets(assets, [])) assert.doesNotMatch(item.details, /V[12]/);
});

test("editor asset labels recover shot identity and versions from generated metadata", () => {
  const assets = [
    { id: "old", name: "生成结果.mp4", kind: "video", url: "/old", created: 1, category: "shot", metadata: { node_id: "video-2", duration: 5, input: { label: "shot-002 · 视频", model_id: "seedance" } } },
    { id: "new", name: "生成结果.mp4", kind: "video", url: "/new", created: 2, category: "shot", metadata: { node_id: "video-2", duration: 4, input: { label: "shot-002 · 视频", model_id: "seedance" } } },
  ];
  const shots = [{ id: "shot-002", title: "机器人整理柜台", duration: 3, pipeline: { videoNodeId: "video-2" } }];
  const presented = presentEditorAssets(assets, shots);
  assert.equal(presented[0].title, "镜头 02 · 视频");
  assert.equal(presented[0].subtitle, "机器人整理柜台");
  assert.match(presented[0].details, /素材 5\.0 秒 · 镜头 3\.0 秒 · V1 · 镜头 · seedance/);
  assert.match(presented[1].details, /素材 4\.0 秒 · 镜头 3\.0 秒 · V2/);
  assert.match(presented[1].searchText, /机器人整理柜台/);
});

test("editor asset labels keep uploaded filenames and expose generated task labels", () => {
  const presented = presentEditorAssets([
    { id: "upload", name: "门店环境.jpg", kind: "image", url: "/image", metadata: {}, source: "uploaded" },
    { id: "generated", name: "Seedream 生成图.png", kind: "image", url: "/generated", metadata: { node_id: "image-6", input: { label: "shot-006 · 分镜图" } } },
  ], []);
  assert.equal(presented[0].title, "门店环境.jpg");
  assert.equal(presented[1].title, "镜头 06 · 分镜图");
});

test("editor library shows only the chosen episode, with other episodes opt-in", () => {
  const assets = [
    { id: "ep01-video", project_id: "ep01", kind: "video" },
    { id: "ep02-image", project_id: "ep02", kind: "image" },
    { id: "ep03-video", project_id: "ep03", kind: "video" },
    { id: "ep03-audio", project_id: "ep03", kind: "audio" },
    { id: "legacy-ep03", origin_project_id: "ep03", kind: "image" },
    { id: "unknown", kind: "video" },
  ];
  assert.deepEqual(filterEditorAssetsByEpisode(assets, "ep03").map((item) => item.id), ["ep03-video", "ep03-audio", "legacy-ep03"]);
  assert.deepEqual(filterEditorAssetsByEpisode(assets, "ep02").map((item) => item.id), ["ep02-image"]);
  assert.deepEqual(filterEditorAssetsByEpisode(assets, "ep04"), []);
  assert.deepEqual(filterEditorAssetsByEpisode(assets, "all"), assets);
  assert.equal(assets.length, 6, "library filtering must not remove assets needed by the timeline");
});

test("cross-episode assets do not borrow current shot descriptions or version numbers", () => {
  const assets = [
    { id: "ep02", project_id: "ep02", origin_episode_no: 2, name: "生成结果.mp4", kind: "video", url: "/ep02", created: 1, metadata: { node_id: "video-1", input: { label: "shot-001 · 第二集" } } },
    { id: "ep03", project_id: "ep03", origin_episode_no: 3, name: "生成结果.mp4", kind: "video", url: "/ep03", created: 2, metadata: { node_id: "video-1", input: { label: "shot-001 · 第三集" } } },
  ];
  const shots = [{ id: "shot-001", title: "第三集镜头内容", pipeline: { videoNodeId: "video-1" } }];
  const result = presentEditorAssets(assets, shots, "ep03");
  assert.match(result[0].title, /第二集/);
  assert.doesNotMatch(result[0].subtitle, /第三集镜头内容/);
  assert.equal(result[1].subtitle, "第三集镜头内容");
  assert.match(result[0].details, /EP02/);
  assert.match(result[1].details, /EP03/);
  assert.doesNotMatch(result[0].details, /V1/);
  assert.doesNotMatch(result[1].details, /V2/);
});
