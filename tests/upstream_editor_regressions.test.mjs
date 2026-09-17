import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, mkdirSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, dirname} from 'node:path';
import {TimelineEditor} from '@twick/timeline';
import {planInitialTimeline} from '../src/editor/initialTimeline.ts';
import {patchedTwick, patchTwick} from '../scripts/patch-twick-video-editor.mjs';
import {readEditorTimeline} from '../src/editor/editorDocument.ts';
import {TimelineInputSync} from '../src/editor/timelineInputSync.ts';
import {legacyTimelineProjection, reconcileTimelineEdit} from '../src/editor/legacyTimeline.ts';
import {timelineWorkspaceDuration, withTimelineWorkspaceDuration} from '../src/editor/timelineDuration.ts';
import {clipSourceTime} from '../src/timeline.ts';

const resolution = {width: 1280, height: 720};
const input = {
  shots: [{id: 's1', videoNode: 'v1', duration: 3}, {id: 's2', videoNode: 'v2', duration: 2}],
  nodes: [{id: 'v1', data: {assetId: 'a1'}}, {id: 'v2', data: {assetId: 'a2'}}],
  assets: ['a1', 'a2'].map(id => ({id, name: id, kind: 'video', url: '/api/assets/' + id + '/file', metadata: {duration: 4}})),
  resolution,
};

test('preserve rough cut retains the complete source rather than planning-time trims', () => {
  let id = 0;
  const plan = planInitialTimeline(input, () => String(++id));
  assert.deepEqual(plan.issues, []);
  const videos = plan.timeline.tracks.flatMap(t => t.elements).filter(e => e.type === 'video');
  assert.deepEqual(videos.map(e => [e.s, e.e]), [[0, 4], [4, 8]]);
  assert.equal(plan.naturalDuration, 8);
});

test('installed Twick scissors split protected known-duration video without losing it', async () => {
  const editor = new TimelineEditor({contextId: 'upstream-split', setTotalDuration() {}, setPresent() {},
    handleUndo: () => null, handleRedo: () => null, handleResetHistory() {}, updateChangeLog() {}, setTimelineAction() {}});
  editor.loadProject({version: 1, tracks: [{id: 'v1', name: 'V1', type: 'element', elements: [{
    id: 'clip', trackId: 'v1', type: 'video', name: 'protected', s: 0, e: 4,
    props: {src: '/api/assets/a1/file', time: 0, playbackRate: 1, volume: 1, srcAssetId: 'a1'},
    frame: {x: 0, y: 0, size: [1280, 720]}, metadata: {assetId: 'a1'}, mediaDuration: 4,
  }]}]});
  const result = await editor.splitElement(editor.getTrackById('v1').getElements()[0], 2);
  const parts = editor.getTrackById('v1').getElements();
  assert.equal(result.success, true, `split must succeed; remaining clips: ${parts.length}`);
  assert.deepEqual(parts.map(e => [e.getStart(), e.getEnd(), e.getProps().time]), [[0, 2, 0], [2, 4, 2]]);
  assert.ok(parts.every(e => e.getMetadata().assetId === 'a1'));
});

test('actual Twick playback callback uses current full duration, not an old first-clip duration', () => {
  const source = readFileSync(new URL('../node_modules/@twick/video-editor/dist/index.mjs', import.meta.url), 'utf8');
  const start = source.indexOf('  const handleTimeUpdate = (time2) => {');
  const end = source.indexOf('\n  };', start);
  assert.ok(start >= 0 && end > start);
  let time = -1, state = 'playing';
  const update = new Function('durationRef', 'totalDuration', 'setCurrentTime', 'setPlayerState', 'PLAYER_STATE',
    source.slice(start, end + 5) + '\nreturn handleTimeUpdate;')(
      {current: 4}, 8, value => {time = value;}, value => {state = value;}, {PAUSED: 'paused'});
  update(6);
  assert.equal(time, 6);
  assert.equal(state, 'playing');
  update(8);
  assert.equal(time, 0);
  assert.equal(state, 'paused');
});

test('locked Twick patch is idempotent for ESM/CJS and fails closed on unknown builds', () => {
  for (const pkg of ['video-editor', 'timeline']) for (const file of ['index.mjs', 'index.js']) {
    const source = readFileSync(new URL(`../node_modules/@twick/${pkg}/dist/${file}`, import.meta.url), 'utf8');
    assert.equal(patchedTwick(source, pkg === 'timeline' ? 'timeline' : file), source);
  }
  assert.throws(() => patchedTwick('new unrecognized build', 'timeline'), /Unsupported/);
  assert.throws(() => patchedTwick('new unrecognized build', 'index.mjs'), /Unsupported/);
});

test('unknown last Twick artifact prevents partial patching of earlier artifacts', () => {
  const root = mkdtempSync(join(tmpdir(), 'ovc-twick-preflight-'));
  const snapshots = [];
  for (const pkg of ['video-editor', 'timeline']) for (const file of ['index.mjs', 'index.js']) {
    const path = join(root, 'node_modules', '@twick', pkg, 'dist', file);
    mkdirSync(dirname(path), {recursive: true});
    let source = readFileSync(new URL(`../node_modules/@twick/${pkg}/dist/${file}`, import.meta.url), 'utf8');
    if (pkg === 'video-editor') source = source.replace('const { changeLog, totalDuration }', 'const { changeLog }');
    if (pkg === 'timeline' && file === 'index.js') source = 'unsupported';
    writeFileSync(path, source);
    snapshots.push([path, source]);
  }
  assert.throws(() => patchTwick(root), /Unsupported/);
  for (const [path, before] of snapshots) assert.equal(readFileSync(path, 'utf8'), before);
});

test('fit mode scales full video and explicitly adopted dialogue together, but not looping BGM', () => {
  const copy = structuredClone(input);
  copy.shots[1].dialogues = [{id: 'd', text: 'hello', audioAssetId: 'voice', audioVoiceVersion: 2}];
  copy.assets.push({id: 'voice', name: 'voice', kind: 'audio', url: '/voice', metadata: {duration: 2,
    input: {dialogue: {id: 'd', text: 'hello', shotUid: 's2', voiceVersion: 2}}}},
    {id: 'music', name: 'music', kind: 'audio', url: '/music', metadata: {duration: 3}});
  let id = 0;
  const plan = planInitialTimeline({...copy, durationMode: 'fit', targetDuration: 4, audioId: 'music'}, () => String(++id));
  assert.deepEqual(plan.issues, []);
  assert.equal(plan.naturalDuration, 8);
  assert.equal(plan.outputDuration, 4);
  const [visual, dialogue, music] = plan.timeline.tracks;
  assert.deepEqual(visual.elements.map(e => [e.s, e.e, e.props.playbackRate, e.props.volume]), [[0, 2, 2, 1], [2, 4, 2, 0]]);
  assert.deepEqual(dialogue.elements.map(e => [e.s, e.e, e.props.playbackRate, e.metadata.assetId]), [[2, 3, 2, 'voice']]);
  assert.deepEqual([music.elements[0].e, music.elements[0].props.playbackRate], [4, 1]);
  assert.ok(visual.elements.every(e => Math.abs((e.e - e.s) * e.props.playbackRate - e.mediaDuration) < 0.001));
});

test('fit duration rejects unsupported rates and invalid targets instead of silently trimming', () => {
  for (const targetDuration of [0, -1, NaN, Infinity, 1, 40]) {
    const plan = planInitialTimeline({...input, durationMode: 'fit', targetDuration}, () => 'id');
    assert.equal(plan.issues.length, 1, String(targetDuration));
    assert.equal(plan.playbackRate, 1);
  }
  for (const targetDuration of [2, 32]) assert.deepEqual(
    planInitialTimeline({...input, durationMode: 'fit', targetDuration}, () => 'id').issues, []);
});

test('legacy video normalization is read-only and never echoes a remote timeline write', () => {
  const plan = planInitialTimeline(input, () => 'id').timeline;
  plan.tracks[0].type = 'video';
  const original = structuredClone(plan);
  const normalized = readEditorTimeline({version: 1, timeline: plan});
  assert.equal(normalized.tracks[0].type, 'element');
  assert.deepEqual(plan, original);
  const sync = new TimelineInputSync(normalized, normalized);
  assert.equal(sync.update(normalized, () => normalized, () => assert.fail('unexpected load')), null);
  assert.equal(legacyTimelineProjection(normalized).length, 2);
});

test('generic visual tracks and slow full clips survive legacy volume edit without reset or duplication', () => {
  let id = 0;
  const timeline = planInitialTimeline({...input, durationMode: 'fit', targetDuration: 16}, () => String(++id)).timeline;
  timeline.tracks.unshift({id: 'title', type: 'element', elements: [{id: 'title-e', type: 'text', s: 0, e: 2, props: {text: 'keep'}}]});
  const before = {editor: {version: 1, timeline}, timeline: legacyTimelineProjection(timeline)};
  const after = structuredClone(before);
  after.timeline[0].volume = 0.4;
  const next = reconcileTimelineEdit(before, after, input.assets);
  assert.equal(next.editor.timeline.tracks.length, 2);
  assert.equal(next.editor.timeline.tracks[0].elements[0].props.text, 'keep');
  assert.deepEqual(next.editor.timeline.tracks[1].elements.map(e => [e.s, e.e, e.props.playbackRate]), [[0, 8, 0.5], [8, 16, 0.5]]);
  assert.equal(next.timeline[0].volume, 0.4);
  assert.equal(clipSourceTime(next.timeline[1], 4), 2);
  const invalid = structuredClone(next); invalid.timeline[0].duration = 10;
  assert.throws(() => reconcileTimelineEdit(next, invalid, input.assets), /超出/);
});

test('workspace length retains metadata without truncating content and can shrink on remote refresh', () => {
  const timeline = planInitialTimeline(input, () => 'id').timeline;
  const before = structuredClone(timeline);
  const extended = withTimelineWorkspaceDuration(timeline, 40, 12);
  assert.equal(timelineWorkspaceDuration(extended, 12), 40);
  assert.equal(timelineWorkspaceDuration(timeline, 12), 12);
  assert.equal(timelineWorkspaceDuration(withTimelineWorkspaceDuration(extended, 3, 6), 6), 8);
  assert.equal(timelineWorkspaceDuration(withTimelineWorkspaceDuration(timeline, Infinity, 0), 0), 8);
  assert.deepEqual(timeline, before);
  assert.equal(extended.metadata.custom.schema, 'mvc-editor-v1');
});
