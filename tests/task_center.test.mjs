import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  deriveTaskCenterRows,
  filterTaskCenterRows,
  taskShotLabel,
} from "../src/taskCenter.ts";

const taskCenterComponent = readFileSync(new URL("../src/pages/TaskCenter.tsx", import.meta.url), "utf8");
const taskCenterStyles = readFileSync(new URL("../src/style.css", import.meta.url), "utf8");

const episodes = [
  { id: "ep-1", production_id: "prod", episode_no: 1, episode_title: "第一集", name: "第一集" },
  { id: "ep-2", production_id: "prod", episode_no: 2, episode_title: "第二集", name: "第二集" },
];

test('single episode planning is not labeled as whole production regeneration',()=>{
  assert.equal(taskShotLabel({job:{input:{stage:'adaptation_generation',adaptation_generation:{mode:'episode',episodeNo:2}}}}),'EP02 单集规划');
});
const documents = {
  "ep-1": {
    nodes: [{ id: "video-1", data: { model_id: "video-model" } }],
    shots: [{ uid: "shot-1", shot_id: "001", pipeline: { videoNodeId: "video-1" } }],
  },
  "ep-2": {
    nodes: [{ id: "image-2", data: { model_id: "image-model" } }],
    shots: [{ uid: "shot-2", shot_id: "002", imageNode: "image-2" }],
  },
};

test("task center projects durable jobs across episodes with ownership and model context", () => {
  const jobs = [
    { id: "old", project_id: "ep-1", node_id: "video-1", kind: "video", status: "succeeded", created: 1, input: {} },
    { id: "new", project_id: "ep-2", node_id: "image-2", kind: "image", status: "failed", created: 2, input: {} },
    { id: "export", project_id: "ep-1", node_id: "export", kind: "export", status: "interrupted", created: 1.5, input: {} },
  ];
  const rows = deriveTaskCenterRows(jobs, episodes, documents, [
    { id: "video-model", name: "火山方舟" },
    { id: "image-model", name: "平台图片" },
  ]);

  assert.deepEqual(rows.map((row) => row.job.id), ["new", "export", "old"]);
  assert.equal(rows[0].episode.episode_no, 2);
  assert.equal(rows[0].providerName, "平台图片");
  assert.equal(rows[0].modelName, "image-model");
  assert.equal(taskShotLabel(rows[0]), "SHOT 002");
  assert.equal(rows[1].providerName, "本机导出");
  assert.equal(rows[1].modelName, "FFmpeg");
});

test("task center filters reuse the six persisted job states", () => {
  const statuses = ["queued", "running", "succeeded", "failed", "interrupted", "cancelled"];
  const jobs = statuses.map((status, index) => ({
    id: status,
    project_id: index % 2 ? "ep-2" : "ep-1",
    node_id: index % 2 ? "image-2" : "video-1",
    kind: index % 2 ? "image" : "video",
    status,
    created: index,
    input: {},
  }));
  const rows = deriveTaskCenterRows(jobs, episodes, documents, []);
  assert.deepEqual(new Set(rows.map((row) => row.job.status)), new Set(statuses));
  assert.deepEqual(
    filterTaskCenterRows(rows, { episodeId: "ep-2", kind: "image", status: "failed" }).map((row) => row.job.id),
    ["failed"],
  );
});

test("production jobs are labelled and filtered independently from their storage episode", () => {
  const jobs = [{
    id: "source", project_id: "ep-2", node_id: "source-chapter:c1", kind: "text",
    status: "succeeded", created: 3, scope: "production",
    input: { stage: "source_analysis", prompt: "章节标题：第五章\n\n原文：内容" },
  }];
  const rows = deriveTaskCenterRows(jobs, episodes, documents, []);
  assert.equal(rows[0].scope, "production");
  assert.equal(taskShotLabel(rows[0]), "原著事件提取 · 第五章");
  assert.deepEqual(filterTaskCenterRows(rows, { episodeId: "production", kind: "", status: "" }).length, 1);
  assert.deepEqual(filterTaskCenterRows(rows, { episodeId: "ep-2", kind: "", status: "" }).length, 0);
});

test("task center keeps all three filters visible in one compact bounded row", () => {
  assert.match(taskCenterComponent, /<h2>任务中心<span className="task-center-production" title=\{productionName\}>/);
  assert.match(taskCenterComponent, /<p title="直接读取现有生成任务，不会自动重试或产生费用。">/);
  assert.match(taskCenterStyles, /\.task-center-filters\{[^}]*grid-template-columns:minmax\(0,1\.4fr\) repeat\(2,minmax\(0,1fr\)\)/);
  assert.match(taskCenterStyles, /\.task-center-filters select\{[^}]*width:100%[^}]*min-width:0[^}]*max-width:100%/);
  assert.match(taskCenterStyles, /\.task-center-production\{[^}]*text-overflow:ellipsis/);
});
