// Run from the repository root. Logs are command output, never fabricated results.
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
const output=process.argv[2];
if(!output)throw new Error('supply a new evidence output directory');
fs.mkdirSync(output,{recursive:false});
const cwd=process.cwd();
const clean=text=>text.replaceAll(cwd,'<REPO>').replaceAll(cwd.replaceAll('\\','/'),'<REPO>')
  .replaceAll(os.homedir(),'<USERPROFILE>').replaceAll(os.homedir().replaceAll('\\','/'),'<USERPROFILE>');
const head=spawnSync('git',['rev-parse','HEAD'],{encoding:'utf8'}).stdout.trim();
const specs=[
  ['targeted','node',['--test','tests/p5_receipt_host.test.mjs','tests/object_drafts.test.mjs','tests/owned_content_drafts.test.mjs','tests/collaboration_client.test.mjs']],
  ['frontend','node',['--test','tests/*.test.mjs']],
  ['typescript','node',['node_modules/typescript/bin/tsc','-b']],
  ['build','node',['node_modules/vite/bin/vite.js','build']],
  ['backend-equivalence','git',['diff','--exit-code','34d646d5c17d5ba12fdc56d4948ab513703731ff',head,'--','backend']],
  ['diff-check','git',['diff','--check','78fd14f40339e0b71908a685efb2354a0c1045ce',head]],
];
const runs=[];
for(const [name,command,args] of specs){
  const started=new Date().toISOString();
  const result=spawnSync(command,args,{encoding:'utf8',maxBuffer:20*1024*1024});
  const ended=new Date().toISOString();
  fs.writeFileSync(path.join(output,`${name}.txt`),clean((result.stdout||'')+(result.stderr||'')));
  const record={name,command:[command,...args],started,ended,exit:result.status,error:result.error?.message};
  runs.push(record);console.log(JSON.stringify(record));
}
fs.writeFileSync(path.join(output,'runs.json'),JSON.stringify({head,node:process.version,runs},null,2)+'\n');
if(runs.some(run=>run.exit!==0))process.exitCode=1;
