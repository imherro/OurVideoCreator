import test from 'node:test';
import assert from 'node:assert/strict';
import {ObjectDrafts, equalContent} from '../src/objectDrafts.ts';

const row = (id, revision=1, text='v1', epoch=1) => ({id,kind:'shot',revision,
  assignment_epoch:epoch,assignee_id:'editor-a',content:{text}});

test('remote shot Y updates while local shot X remains dirty', () => {
  const drafts = new ObjectDrafts();
  drafts.open('episode', [row('x'),row('y')]);
  drafts.edit('x',{text:'local x'});
  assert.equal(drafts.remote('episode',drafts.generation,row('y',2,'remote y')),true);
  assert.equal(drafts.remote('episode',drafts.generation,row('x',2,'remote x')),false);
  assert.equal(drafts.entries.get('x').content.text,'local x');
  assert.equal(drafts.entries.get('x').base.revision,1);
  assert.equal(drafts.entries.get('y').content.text,'remote y');
});

test('409 preserves local draft, blocks timer retries and never says saved', () => {
  const drafts = new ObjectDrafts();
  drafts.open('episode',[row('x')]);
  drafts.edit('x',{text:'local'});
  const ticket=drafts.begin('x');
  assert.equal(drafts.entries.get('x').state,'saving');
  drafts.reject(ticket,409,'版本冲突');
  drafts.remote('episode',drafts.generation,row('x',2,'remote'));
  assert.equal(drafts.entries.get('x').content.text,'local');
  assert.equal(drafts.entries.get('x').state,'conflict');
  assert.equal(drafts.begin('x'),null);
  drafts.edit('x',{text:'local further change'});
  assert.equal(drafts.begin('x'),null);
  drafts.resolve('x',row('x',2,'remote'),'keep-draft');
  const explicit=drafts.begin('x');
  assert.equal(explicit.expected_revision,2);
  assert.equal(explicit.content.text,'local further change');
});

test('edits during save survive acknowledgement and require a second save', () => {
  const drafts = new ObjectDrafts();
  drafts.open('episode',[row('x')]);
  drafts.edit('x',{text:'first'});
  const first=drafts.begin('x');
  drafts.edit('x',{text:'second'});
  assert.equal(drafts.begin('x'),null);
  drafts.acknowledge(first,row('x',2,'first'));
  assert.equal(drafts.entries.get('x').state,'dirty');
  assert.equal(drafts.entries.get('x').content.text,'second');
  const second=drafts.begin('x');
  assert.equal(second.expected_revision,2);
  drafts.acknowledge(second,row('x',3,'second'));
  assert.equal(drafts.entries.get('x').state,'saved');
});

test('switch refuses unsaved data and old responses cannot write another Episode', () => {
  const drafts = new ObjectDrafts();
  drafts.open('A',[row('x')]);
  const generation=drafts.generation;
  drafts.edit('x',{text:'private draft'});
  const ticket=drafts.begin('x');
  assert.throws(()=>drafts.open('B',[row('x')]),/未保存/);
  drafts.open('B',[row('x')],true);
  assert.equal(drafts.acknowledge(ticket,row('x',2,'A late response')),false);
  assert.equal(drafts.remote('A',generation,row('x',2,'A late event')),false);
  assert.equal(drafts.entries.get('x').content.text,'v1');
});

test('assignment A to B to A cannot be auto-resolved with old draft credentials', () => {
  const drafts = new ObjectDrafts();
  drafts.open('episode',[row('x')]);
  drafts.edit('x',{text:'old draft'});
  drafts.reject(drafts.begin('x'),409,'负责人已变更');
  assert.throws(()=>drafts.resolve('x',row('x',4,'current',3),'keep-draft'),/负责人/);
  drafts.resolve('x',row('x',4,'current',3),'discard');
  assert.equal(drafts.entries.get('x').content.text,'current');
});

test('object equality ignores property order, not array order or content', () => {
  assert.ok(equalContent({a:1,b:{x:2,y:3}},{b:{y:3,x:2},a:1}));
  assert.ok(!equalContent([1,2],[2,1]));
  assert.ok(!equalContent({a:1},{a:2}));
});
