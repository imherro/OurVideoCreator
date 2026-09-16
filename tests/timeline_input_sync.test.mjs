import test from 'node:test';
import assert from 'node:assert/strict';
import { TimelineInputSync } from '../src/editor/timelineInputSync.ts';

const copy = structuredClone;
const empty = {version: 1, tracks: [], backgroundColor: '#000000'};
const title = {version: 2, tracks: [{id: 't-title', name: 'Title', type: 'text', elements: [
  {id: 'e-title', type: 'text', s: 0, e: 3, props: {text: 'Remote title'}}]}], backgroundColor: '#000000'};

function setup() {
  let current = copy(empty);
  const loads = [], sync = new TimelineInputSync(empty);
  return {sync, loads, read: () => copy(current), edit: value => {current = copy(value);},
    load: value => {loads.push(copy(value)); current = {...copy(value), metadata: {normalized: true}};}};
}

test('an already open empty timeline consumes a remote title without echoing a save', () => {
  const s = setup();
  assert.equal(s.sync.update(empty, s.read, s.load), null);
  assert.equal(s.sync.update(title, s.read, s.load), null);
  assert.equal(s.read().tracks[0].elements[0].props.text, 'Remote title');
  assert.equal(s.loads.length, 1);
  assert.equal(s.sync.update(title, s.read, s.load), null);
  assert.equal(s.loads.length, 1);
});

test('first mount normalization is a baseline and never publishes a read-only edit', () => {
  const normalized = {...copy(title), version: 9};
  normalized.tracks[0].type = 'element';
  const sync = new TimelineInputSync(title, normalized);
  assert.equal(sync.update(title, () => normalized, () => assert.fail('unexpected load')), null);
  const edited = copy(normalized);
  edited.tracks[0].elements[0].props.text = 'Actual user edit';
  assert.deepEqual(sync.update(title, () => edited, () => assert.fail('unexpected load')), edited);
});

test('local publication and JSONB key-order acknowledgement never reload the live editor', () => {
  const s = setup(); s.edit(title);
  assert.deepEqual(s.sync.update(empty, s.read, s.load), title);
  const ack = {backgroundColor: title.backgroundColor, tracks: copy(title.tracks), version: title.version};
  assert.equal(s.sync.update(ack, s.read, s.load), null);
  assert.equal(s.sync.update(ack, s.read, s.load), null);
  assert.equal(s.loads.length, 0);
});

test('draft retained by the object client stays local when unrelated remote objects change', () => {
  const s = setup(); const draft = copy(title);
  draft.tracks[0].elements[0].props.text = 'Unresolved local draft'; s.edit(draft);
  assert.deepEqual(s.sync.update(empty, s.read, s.load), draft);
  assert.equal(s.sync.update(copy(draft), s.read, s.load), null);
  assert.equal(s.sync.update(copy(draft), s.read, s.load), null);
  assert.equal(s.read().tracks[0].elements[0].props.text, 'Unresolved local draft');
  assert.equal(s.loads.length, 0);
});

test('explicit discard or restore applies a new host timeline without publishing normalized JSON', () => {
  const s = setup(); s.edit(title); s.sync.update(empty, s.read, s.load);
  s.sync.update(title, s.read, s.load);
  assert.equal(s.sync.update(empty, s.read, s.load), null);
  assert.deepEqual(s.read().tracks, []);
  assert.equal(s.sync.update(empty, s.read, s.load), null);
  assert.equal(s.loads.length, 1);
});
