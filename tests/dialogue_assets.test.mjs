import test from "node:test";
import assert from "node:assert/strict";
import { projectCharacterDialogueRows } from "../src/filmBible/dialogueAssets.ts";

test("character dialogue rows connect shots to current voice assets and jobs", () => {
  const shots = [{ id: "shot-001", uid: "shot-uid", order: 1, dialogues: [
    { id: "d-ready", characterCardId: "hero", text: "我回来了。", emotion: "平静", audioAssetId: "voice-1", audioVoiceVersion: 2 },
    { id: "d-running", characterCardId: "hero", text: "等等！", emotion: "紧张" },
    { id: "d-other", characterCardId: "villain", text: "太迟了。", emotion: "冷漠" },
  ] }];
  const assets = [{ id: "voice-1", kind: "audio", metadata: { input: { dialogue: { id: "d-ready", voiceVersion: 2, text: "我回来了。" } } } }];
  const jobs = [{ id: "job-1", status: "running", input: { dialogue: { id: "d-running", voiceVersion: 2 } } }];
  const rows = projectCharacterDialogueRows({ shots, assets, jobs, cardId: "hero", voiceVersion: 2 });
  assert.deepEqual(rows.map((row) => [row.id, row.status]), [["d-ready", "ready"], ["d-running", "running"]]);
  assert.equal(rows[0].asset.id, "voice-1");
  assert.equal(rows[1].job.id, "job-1");
});

test("successful unadopted audio remains a candidate, and newer takes never replace the adopted take", () => {
  const dialogue = {id:"d",characterCardId:"hero",text:"saved words"};
  const input = {dialogue:{id:"d",voiceVersion:2,text:dialogue.text}};
  const assets = [{id:"new",kind:"audio",metadata:{input}},{id:"chosen",kind:"audio",metadata:{input}}];
  const jobs = [{id:"j",status:"succeeded",input}];
  const rows = () => projectCharacterDialogueRows({shots:[{dialogues:[dialogue]}],assets,jobs,cardId:"hero",voiceVersion:2});
  assert.equal(rows()[0].status,"syncing");
  assert.equal(rows()[0].asset,undefined);
  Object.assign(dialogue,{audioAssetId:"chosen",audioVoiceVersion:2});
  assert.equal(rows()[0].asset.id,"chosen");
  dialogue.text="edited words";
  assert.equal(rows()[0].asset,undefined);
});

test("dialogue generated with an older voice version is shown as missing", () => {
  const rows = projectCharacterDialogueRows({
    shots: [{ id: "shot-1", dialogues: [{ id: "d1", characterCardId: "hero", text: "你好" }] }],
    assets: [{ id: "old", kind: "audio", metadata: { input: { dialogue: { id: "d1", voiceVersion: 1 } } } }],
    jobs: [], cardId: "hero", voiceVersion: 2,
  });
  assert.equal(rows[0].status, "missing");
});

