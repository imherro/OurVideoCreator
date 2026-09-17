import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
test('both episode entrypoints share the dialog and retain project-switch guard',()=>{
 const main=readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8');
 assert.match(main,/onCreateEpisode=\{setEpisodeSetupProduction\}/);
 assert.match(main,/<ScriptRoomPage\s+onAddEpisode=/);
 const create=main.slice(main.indexOf('async function createEpisode('),main.indexOf('async function renameProduction('));
 assert.ok(create.indexOf('await prepareProjectSwitch()')<create.indexOf('await api('));
 assert.match(create,/creation_mode:creationMode/);
 assert.match(create,/creationMode==='direct'\?'script':'source'/);
 assert.ok(create.indexOf('setEpisodeSetupProduction(null)')<create.indexOf('await refreshProductionHierarchy()'));
 assert.doesNotMatch(create,/window\.prompt/);
});
test('episode setup uses native modal and preserves error and duplicate-submit guards',()=>{
 const source=readFileSync(new URL('../src/pages/EpisodeSetupDialog.tsx',import.meta.url),'utf8');
 assert.match(source,/element\.showModal\(\)/);
 assert.match(source,/if\(submitting\.current\)return/);
 assert.match(source,/if\(!title\.trim\(\)\)/);
 assert.match(source,/onCreate\(title\.trim\(\),mode\)/);
 assert.match(source,/role="alert"/);
});
