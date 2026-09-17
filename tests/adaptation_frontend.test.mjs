import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {appendEpisodeForChapter,createEpisodePlans,normalizeEpisodeSelection,resolvePlanningEpisode,splitList} from '../src/adaptation.ts';

test('episode planner creates sixty stable plans and preserves existing edits',()=>{
  const plans=createEpisodePlans(60,60);
  plans[11].hook='门外响起脚步声';
  const resized=createEpisodePlans(62,75,plans);
  assert.equal(resized.length,62);
  assert.equal(resized[11].hook,'门外响起脚步声');
  assert.equal(resized[60].targetDuration,75);
});

test('batch script generation includes only valid unique selected episodes',()=>{
  assert.deepEqual(normalizeEpisodeSelection([12,5,8,5,0,61],60),[5,8,12]);
});

test('production lists are trimmed and deduplicated',()=>{
  assert.deepEqual(splitList('阿青，老周\n阿青, 密使'),['阿青','老周','密使']);
});

test('an unassigned source chapter creates only the next planning episode',()=>{
  const original=createEpisodePlans(1,15);
  original[0].sourceChapterRefs=['chapter-1'];
  const plans=appendEpisodeForChapter(original,15,'chapter-2');
  assert.equal(plans.length,2);
  assert.deepEqual(plans[0].sourceChapterRefs,['chapter-1']);
  assert.deepEqual(plans[1].sourceChapterRefs,['chapter-2']);
  assert.equal(plans[1].status,'draft');
});

test('planning focus survives stage changes and falls back to unfinished work',()=>{
  const plans=[{episodeNo:1,status:'approved'},{episodeNo:2,status:'approved'},{episodeNo:3,status:'review'}];
  assert.equal(resolvePlanningEpisode(plans,2,[1,2]),2);
  assert.equal(resolvePlanningEpisode(plans,undefined,[1,2]),3);
  assert.equal(resolvePlanningEpisode(plans,99,[1,2]),3);
  assert.equal(resolvePlanningEpisode([],3),0);
});

test('single episode review uses saved revision and cannot discard dirty edits',()=>{
  const page=readFileSync(new URL('../src/pages/AdaptationPage.tsx',import.meta.url),'utf8');
  assert.match(page,/adaptation\/episodes\/\$\{active\}\/\$\{action\}/);
  assert.match(page,/planningContent\(draft\)!==savedContent/);
  assert.match(page,/JSON.stringify\(\{revision:draft.revision\}\)/);
  assert.match(page,/本集提交审核/);
  assert.match(page,/批准本集规划/);
  assert.match(page,/fieldset disabled=\{busy\}/);
});

test('single plan generation submits a candidate with a stable uncertain-retry identifier',()=>{
  const page=readFileSync(new URL('../src/pages/AdaptationPage.tsx',import.meta.url),'utf8');
  const action=page.slice(page.indexOf('async function generateEpisode'),page.indexOf('async function generate()'));
  assert.match(action,/adaptation\/episodes\/\$\{active\}\/generate/);
  assert.match(action,/submission_id:episodeSubmission.current.id/);
  assert.match(action,/episodeSubmission.current=null/);
  assert.doesNotMatch(action,/\/adopt|setDraft\(/);
  assert.match(page,/AI 生成本集规划候选/);
});

test('adaptation refresh preserves dirty planning and rejects late scope responses',()=>{
  const page=readFileSync(new URL('../src/pages/AdaptationPage.tsx',import.meta.url),'utf8');
  assert.match(page,/!mountedRef\.current\|\|sequence!==loadSequence\.current\|\|targetProduction!==productionRef\.current/);
  assert.ok((page.match(/!mountedRef\.current\|\|targetProduction!==productionRef\.current/g)||[]).length>=5);
  assert.match(page,/planningContent\(value\)!==savedContentRef\.current/);
  assert.match(page,/服务器上的改编规划已有更新/);
  assert.match(page,/放弃当前未保存的改编修改/);
  assert.match(page,/appendEpisodeForChapter/);
  assert.match(page,/adaptation-chapter-index/);
  assert.match(page,/onDirtyChange\(dirty\)/);
});

test('adaptation and script share one production planning focus',()=>{
  const main=readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8');
  const script=readFileSync(new URL('../src/pages/ScriptRoomPage.tsx',import.meta.url),'utf8');
  assert.match(main,/planningEpisodeFocus/);
  assert.match(main,/focusedEpisodeNo=\{planningEpisodeFocus\[project\.production_id\]\|\|project\.episode_no\}/);
  assert.match(main,/currentEpisodeNo=\{planningEpisodeFocus\[project\.production_id\]\|\|project\.episode_no\}/);
  assert.match(main,/workflowStageRef\.current==='adaptation'&&adaptationDirty\.current/);
  assert.match(script,/onFocusEpisode\(episodeNo\)/);
});
