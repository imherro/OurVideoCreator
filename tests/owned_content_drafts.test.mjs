import test from 'node:test';
import assert from 'node:assert/strict';
import {OwnedContentDrafts} from '../src/ownedContentDrafts.ts';

const row=(id,revision=1,content='base',epoch=1)=>({id,title:id,content,revision,assignment_epoch:epoch,assignee_id:'a'});
const setup=()=>{const store=new OwnedContentDrafts('chapter');store.open('production');store.receive('x',row('x'));store.receive('y',row('y'));return store;};
test('chapter refresh merges clean Y and preserves dirty X with its old version',()=>{
  const store=setup();store.patch('x',{content:'local'});store.receive('x',row('x',2,'remote'));store.receive('y',row('y',2,'new Y'));
  assert.equal(store.value('x').content,'local');assert.equal(store.value('x').revision,1);
  assert.equal(store.drafts.entries.get('x').state,'conflict');assert.equal(store.value('y').content,'new Y');
});
test('actual relational save freezes only the chapter payload; 409 cannot resend',async()=>{
  const store=setup();store.patch('x',{content:'draft'});let calls=0;
  const request=async(path,options)=>{calls++;assert.equal(path,'/productions/production/chapters/x');
    assert.deepEqual(JSON.parse(options.body),{revision:1,assignment_epoch:1,title:'x',content:'draft'});
    throw Object.assign(new Error('conflict'),{status:409});};
  await assert.rejects(store.save('x','a',request));await assert.rejects(store.save('x','a',request));
  assert.equal(calls,1);assert.equal(store.value('x').content,'draft');
});
test('typing during save survives acknowledgement and stays dirty',async()=>{
  const store=setup();store.patch('x',{content:'sent'});let finish;
  const pending=store.save('x','a',()=>new Promise(resolve=>{finish=resolve;}));
  store.patch('x',{content:'typed later'});finish(row('x',2,'sent'));await pending;
  assert.equal(store.value('x').content,'typed later');assert.equal(store.value('x').revision,2);
  assert.equal(store.drafts.entries.get('x').state,'dirty');
});
test('a later remote version arriving before an earlier save response is retained for explicit comparison',async()=>{
  const store=setup();store.patch('x',{content:'sent'});let finish;
  const pending=store.save('x','a',()=>new Promise(resolve=>{finish=resolve;}));
  store.receive('x',row('x',3,'later remote'));finish(row('x',2,'sent'));await pending;
  assert.equal(store.value('x').revision,2);assert.equal(store.value('x').content,'sent');
  const entry=store.drafts.entries.get('x');
  assert.equal(entry.state,'conflict');assert.equal(entry.remote.revision,3);
  assert.equal(entry.remote.content.content,'later remote');
  assert.equal(store.unsaved,true);
  await assert.rejects(store.save('x','a',()=>assert.fail('must not auto-resend')),/冲突/);
  store.drafts.resolve('x',entry.remote,'discard');
  assert.equal(store.value('x').revision,3);assert.equal(store.value('x').content,'later remote');
});
test('scope switch is blocked with drafts; a late old-scope fetch cannot enter new scope',()=>{
  const store=setup(),gen=store.generation;store.patch('x',{title:'dirty'});
  assert.throws(()=>store.open('other'));
  store.drafts.resolve('x',store.row('x',row('x')),'discard');store.open('other');
  assert.equal(store.receive('x',row('x'), 'production',gen),false);assert.equal(store.value('x'),null);
});
test('reassigned content forbids manager save and ABA draft reuse',async()=>{
  const store=setup();store.patch('x',{content:'old'});
  await assert.rejects(store.save('x','manager',()=>{throw new Error('must not send');}),/负责人/);
  const latest=store.row('x',row('x',3,'new',3));
  store.receive('x',latest.value);assert.throws(()=>store.drafts.resolve('x',latest,'keep-draft'),/负责人/);
});
test('remotely deleted dirty chapter remains recoverable instead of disappearing',()=>{
  const store=setup();store.patch('x',{content:'recover me'});store.reconcileIds([]);
  assert.equal(store.value('x').content,'recover me');assert.equal(store.value('y'),null);
  assert.equal(store.drafts.entries.get('x').state,'conflict');
});
