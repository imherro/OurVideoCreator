import test from "node:test";
import assert from "node:assert/strict";
import { deriveVideoProductionRows, selectedVideoNodeIds, validateVideoSubmission, videoSubmissionSummary } from "../src/videoProduction.ts";

const providers = [
  { id: "video-model", name: "火山方舟", kind: "video", local: false, type: "volcengine_ark" },
  { id: "local-video", name: "本地视频", kind: "video", local: true },
];
const assets = [
  { id: "frame-a", kind: "image", name: "首帧 A", url: "/a.png" },
  { id: "tail-a", kind: "image", name: "尾帧 A", url: "/tail.png" },
  { id: "clip-a", kind: "video", name: "视频 A", url: "/a.mp4" },
];
const capabilities = { "video-model": { end_frame: true } };

function fixture() {
  const shots = [
    { id: "s-ready", uid: "u-ready", scene: "街道", video_prompt: "向前走", pipeline: { imageNodeId: "i-ready", videoNodeId: "v-ready" } },
    { id: "s-generating", uid: "u-generating", pipeline: { imageNodeId: "i-generating", videoNodeId: "v-generating" } },
    { id: "s-failed", uid: "u-failed", pipeline: { imageNodeId: "i-failed", videoNodeId: "v-failed" } },
    { id: "s-stale", uid: "u-stale", pipeline: { imageNodeId: "i-stale", videoNodeId: "v-stale" } },
    { id: "s-complete", uid: "u-complete", pipeline: { imageNodeId: "i-complete", videoNodeId: "v-complete" } },
    { id: "s-blocked", uid: "u-blocked", pipeline: { imageNodeId: "i-blocked", videoNodeId: "v-blocked" } },
    { id: "s-review", uid: "u-review", pipeline: { imageNodeId: "i-review", videoNodeId: "v-review" } },
  ];
  const nodes = shots.flatMap((shot) => {
    const suffix = shot.id.slice(2);
    const frame = suffix === "blocked" ? undefined : "frame-a";
    return [
      { id: `i-${suffix}`, data: { kind: "image", prompt: suffix === "review" ? "室内灯完全熄灭" : "当前画面", assetId: frame, state_reviewed: false } },
      { id: `v-${suffix}`, data: { kind: "video", model_id: "video-model", prompt: "人物移动", ...(suffix === "failed" ? { assetId: "clip-a" } : {}), ...(suffix === "stale" ? { stale: true, assetId: "clip-a" } : {}), ...(suffix === "complete" ? { assetId: "clip-a", end_asset_id: "tail-a" } : {}) } },
    ];
  });
  const jobs = [
    { node_id: "v-generating", status: "running", created: 3 },
    { node_id: "v-failed", status: "failed", error: "provider error", created: 4 },
  ];
  return { document: { shots, nodes, edges: [] }, jobs };
}

test("video workspace projects canonical shots into all production states", () => {
  const { document, jobs } = fixture();
  const rows = deriveVideoProductionRows(document, assets, jobs, providers, capabilities);
  assert.deepEqual(rows.map((row) => row.status), ["ready", "generating", "failed", "stale", "complete", "blocked", "blocked"]);
  assert.equal(rows[4].firstFrame.id, "frame-a");
  assert.equal(rows[4].endFrame.id, "tail-a");
  assert.equal(rows[4].videoAsset.id, "clip-a");
  assert.equal(rows[4].endFrameSupported, true);
  assert.match(rows[6].readinessReason, /人工核验/);
});

test("selected submission contains only explicit stable pipeline video nodes", () => {
  const { document, jobs } = fixture();
  const rows = deriveVideoProductionRows(document, assets, jobs, providers, capabilities);
  assert.deepEqual(selectedVideoNodeIds(rows, ["u-complete", "u-ready"]), ["v-ready", "v-complete"]);
  assert.deepEqual(validateVideoSubmission(rows, ["u-ready"]).map((row) => row.uid), ["u-ready"]);
  assert.throws(() => validateVideoSubmission(rows, ["u-ready", "u-blocked"]), /缺少已生成的首帧/);
  assert.throws(() => validateVideoSubmission(rows, ["u-generating"]), /队列/);
});

test("batch review names count provider model and cloud use before submission", () => {
  const { document, jobs } = fixture();
  const rows = deriveVideoProductionRows(document, assets, jobs, providers, capabilities);
  const summary = videoSubmissionSummary(rows, ["u-ready", "u-complete"]);
  assert.equal(summary.count, 2);
  assert.equal(summary.cloudCount, 2);
  assert.deepEqual(summary.groups, [{ providerId: "video-model", providerName: "火山方舟", modelId: "video-model", count: 2, cloud: true }]);
});

test("Ark end frame visibility follows the selected model capability, not provider type", () => {
  const { document, jobs } = fixture();
  const withoutCapability = deriveVideoProductionRows(document, assets, jobs, providers);
  assert.equal(withoutCapability[4].endFrameSupported, false);
  assert.match(withoutCapability[4].readinessReason, /不支持尾帧/);
});

test("fresh model catalog overrides a stale cached end-frame capability", () => {
  const { document, jobs } = fixture();
  const videoNode = document.nodes.find((node) => node.id === "v-complete");
  videoNode.data.model_capabilities = { end_frame: false };
  const rows = deriveVideoProductionRows(document, assets, jobs, providers, capabilities);
  assert.equal(rows[4].endFrameSupported, true);
  assert.equal(rows[4].readinessReason, "");
});

for (const providerType of ["volcengine_ark", "runninghub", "hc_atom"]) {
test(`${providerType} dialogue requires the current locked voice take before paid submission`, () => {
  const providers = [{ id: "video-model", type: providerType, capabilities: { audio_reference: true } }];
  const { document, jobs } = fixture();
  document.shots[0].duration = 5;
  document.shots[0].dialogues = [{ id: "dialogue-1", characterCardId: "robot", characterName: "球球", text: "你好" }];
  document.filmBible = { voices: { profiles: { robot: { status: "locked", voiceType: "robot-speaker", version: 2 } } } };
  let rows = deriveVideoProductionRows(document, assets, jobs, providers, capabilities);
  assert.match(rows[0].readinessReason, /尚未使用当前固定音色生成/);
  const voiceAsset = { id: "voice-1", kind: "audio", created: 5, metadata: { duration: 1.5, input: { dialogue: { id: "dialogue-1", voiceVersion: 2, text: "你好" } } } };
  rows = deriveVideoProductionRows(document, [...assets, voiceAsset], jobs, providers, capabilities);
  assert.match(rows[0].readinessReason, /明确采纳/);
  Object.assign(document.shots[0].dialogues[0],{audioAssetId:"voice-1",audioVoiceVersion:2});
  rows = deriveVideoProductionRows(document, [...assets, voiceAsset], jobs, providers, capabilities);
  assert.equal(rows[0].readinessReason, "");
  assert.deepEqual(rows[0].dialogueAudioAssets.map((asset) => asset.id), ["voice-1"]);
});
}

test("HC models without published audio capability retain text-only dialogue readiness", () => {
  const { document, jobs } = fixture();
  document.shots[0].dialogues = [{ id: "line", characterCardId: "hero", text: "你好" }];
  const models = [{ id: "video-model", type: "hc_atom", capabilities: { audio_reference: false } }];
  const rows = deriveVideoProductionRows(document, assets, jobs, models, capabilities);
  assert.equal(rows[0].readinessReason, "");
  assert.deepEqual(rows[0].dialogueAudioAssets, []);
});

test("Seedance dialogue extends a short shot instead of blocking submission", () => {
  const { document, jobs } = fixture();
  document.shots[0].duration = 2;
  document.shots[0].dialogues = [
    { id: "dialogue-1", characterCardId: "robot", characterName: "球球", text: "第一句", audioAssetId:"voice-1",audioVoiceVersion:2 },
    { id: "dialogue-2", characterCardId: "robot", characterName: "球球", text: "第二句", audioAssetId:"voice-2",audioVoiceVersion:2 },
  ];
  document.filmBible = { voices: { profiles: { robot: { status: "locked", voiceType: "robot-speaker", version: 2 } } } };
  const voiceAssets = [
    { id: "voice-1", kind: "audio", created: 5, metadata: { duration: 1.4, input: { dialogue: { id: "dialogue-1", voiceVersion: 2, text:"第一句" } } } },
    { id: "voice-2", kind: "audio", created: 6, metadata: { duration: 1.1, input: { dialogue: { id: "dialogue-2", voiceVersion: 2, text:"第二句" } } } },
  ];
  const rows = deriveVideoProductionRows(document, [...assets, ...voiceAssets], jobs, providers, capabilities);
  assert.equal(rows[0].readinessReason, "");
  assert.equal(rows[0].plannedDuration, 2);
  assert.equal(rows[0].effectiveDuration, 3);
  assert.equal(rows[0].submissionDuration, 4);
  assert.doesNotThrow(() => validateVideoSubmission(rows, ["u-ready"]));
});

test("locked dialogue never shortens the fixed project video duration", () => {
  const { document, jobs } = fixture();
  document.videoDuration = 12;
  document.shots[0].duration = 3;
  document.shots[0].dialogues = [{ id: "dialogue-1", characterCardId: "robot", characterName: "球球", text: "你好" }];
  document.filmBible = { voices: { profiles: { robot: { status: "locked", voiceType: "robot-speaker", version: 2 } } } };
  const voiceAsset = { id: "voice-1", kind: "audio", created: 5, metadata: { duration: 1.5, input: { dialogue: { id: "dialogue-1", voiceVersion: 2, text:"你好" } } } };
  Object.assign(document.shots[0].dialogues[0],{audioAssetId:"voice-1",audioVoiceVersion:2});
  const rows = deriveVideoProductionRows(document, [...assets, voiceAsset], jobs, providers, capabilities);
  assert.equal(rows[0].effectiveDuration, 12);
  assert.equal(rows[0].submissionDuration, 12);
});

test("project fixed duration overrides a shorter shot and remains visible as submitted duration", () => {
  const { document, jobs } = fixture();
  document.shots[0].duration = 2;
  document.videoDuration = 8;
  const rows = deriveVideoProductionRows(document, assets, jobs, providers, capabilities);
  assert.equal(rows[0].plannedDuration, 2);
  assert.equal(rows[0].effectiveDuration, 8);
  assert.equal(rows[0].submissionDuration, 8);
});
