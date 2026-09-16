import test from 'node:test';
import assert from 'node:assert/strict';
import {existsSync,readFileSync} from 'node:fs';

const read=path=>readFileSync(new URL(`../${path}`,import.meta.url),'utf8');

test('P1 removes embedded inference files and runtime controls',()=>{
 assert.equal(existsSync(new URL('../inference',import.meta.url)),false);
 assert.equal(existsSync(new URL('../backend/runtime.py',import.meta.url)),false);
 const backend=read('backend/app.py');
 assert.doesNotMatch(backend,/\/api\/runtime\/(?:unload|maestro\/start)/);
 assert.doesNotMatch(backend,/app\.state\.worker|runtime\.bootstrap/);
});

test('default UI exposes external providers without legacy local-model controls',()=>{
 const ui=[
  read('src/main.tsx'),read('src/ModelSelector.tsx'),
  read('src/GenerationPolicyPanel.tsx'),
 ].join('\n');
 assert.match(ui,/外部 API-only/);
 assert.doesNotMatch(ui,/model_directories|llama_context|额外模型目录|卸载空闲文本模型/);
 assert.doesNotMatch(ui,/\/runtime\/unload|\/runtime\/maestro\/start/);
});
