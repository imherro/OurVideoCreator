import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createEpisodePlans,normalizeEpisodeSelection,splitList} from '../src/adaptation.ts';

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

test('single episode review uses saved revision and cannot discard dirty edits',()=>{
  const page=readFileSync(new URL('../src/pages/AdaptationPage.tsx',import.meta.url),'utf8');
  assert.match(page,/adaptation\/episodes\/\$\{active\}\/\$\{action\}/);
  assert.match(page,/planningContent\(draft\)!==savedContent/);
  assert.match(page,/JSON.stringify\(\{revision:draft.revision\}\)/);
  assert.match(page,/本集提交审核/);
  assert.match(page,/批准本集规划/);
  assert.match(page,/fieldset disabled=\{busy\}/);
});
