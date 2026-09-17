import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {OwnedContentDrafts} from '../src/ownedContentDrafts.ts';

test('append refresh preserves dirty chapter without saving it',()=>{
  const store=new OwnedContentDrafts('chapter');store.open('p');
  const row={id:'old',title:'old',content:'server',revision:1,assignment_epoch:1,assignee_id:'a'};
  store.receive('old',row);store.patch('old',{content:'unsaved'});
  store.receive('old',row);store.receive('new',{...row,id:'new',content:'imported'});
  store.reconcileIds(['old','new']);
  assert.equal(store.value('old').content,'unsaved');
  assert.equal(store.drafts.entries.get('old').state,'dirty');
  assert.equal(store.value('new').content,'imported');
});

test('source import captures target before file selection and checks generation after read',()=>{
  const source=readFileSync(new URL('../src/pages/SourceLibraryPage.tsx',import.meta.url),'utf8');
  assert.match(source,/importTarget.current=\{productionId,generation:store.generation/);
  assert.match(source,/导入章节到当前原著/);
  assert.match(source,/导入为另一部原著/);
  const action=source.slice(source.indexOf('async function importFile'),source.indexOf('async function saveChapter'));
  assert.match(action,/await file.text\(\);\s*if\(!store.matches\(productionId,generation\)\)return/);
  assert.match(action,/if\(importing.current\)return/);
  assert.doesNotMatch(action,/store.save|persistChapter/);
});

test('source extraction waits for production activity and ignores pre-submission snapshots',()=>{
  const source=readFileSync(new URL('../src/pages/SourceLibraryPage.tsx',import.meta.url),'utf8');
  assert.match(source,/productionId\}\/source-extractions/);
  assert.match(source,/epoch===extractionSnapshotEpoch.current/);
  assert.match(source,/extractionSnapshotEpoch.current\+\+/);
  assert.match(source,/if\(polling\)return/);
  assert.match(source,/disposed=true;window.clearInterval\(timer\)/);
  assert.match(source,/selectedExtractingCount>0/);
  assert.match(source,/正在提取/);
});
