import test from 'node:test';
import assert from 'node:assert/strict';
// Supplemental reproduction, outside the sole externally authorized P5-R1
// structure task. Run explicitly: node --test docs/multiuser-rollout/evidence/P5-R1/deferred/p5_late_ack.mjs.
// This is known red, not part of or counted as passing npm regression coverage.
import {CollaborationClient} from '../../../../../src/collaborationClient.ts';
import {splitCollaborationDocument} from '../../../../../src/collaborationDocument.ts';

test('a newer remote revision before an older save receipt cannot be silently overwritten', async () => {
  const copy = structuredClone;
  const document = {nodes: [], edges: [], shots: [{id: 'x', uid: 'x', action: 'v1', note: ''}],
    timeline: [], ratio: '16:9', style: 'film'};
  const rows = [...splitCollaborationDocument(document).parts.values()].map(part => ({
    id: `${part.kind}-${part.key}`, kind: part.kind, object_key: part.key,
    revision: 1, assignment_epoch: 1, assignee_id: 'editor-a', content: copy(part.content),
  }));
  const server = new Map(rows.map(row => [row.id, copy(row)]));
  let release;
  const gate = new Promise(resolve => {release = resolve;});
  let requests = 0;
  const sent = [];
  const client = new CollaborationClient(async (path, init) => {
    assert.ok(path.endsWith('/objects/commands'));
    const body = JSON.parse(init.body); sent.push(copy(body));
    const updated = body.updates.map(item => {
      assert.equal(item.expected_revision, server.get(item.id).revision);
      const row = {...server.get(item.id), revision: item.expected_revision + 1, content: copy(item.content)};
      server.set(row.id, copy(row)); return row;
    });
    if (++requests === 1) await gate;
    return {created: [], updated, deleted: []};
  }, 'editor-a');
  const project = {id: 'episode', name: 'Episode', revision: 1, production_revision: 1,
    object_collaboration: true, permissions: {can_manage: false}, document, objects: rows};
  client.open(project, []);
  let displayed = copy(document); displayed.shots[0].action = 'my saved v2';
  client.mark(displayed, []);
  const pending = client.save(displayed, project.name, []);
  const newer = copy(server.get('shot-x'));
  newer.revision = 3; newer.content.shot.action = 'other page v3';
  server.set(newer.id, copy(newer));
  displayed = client.mergeRemoteRows([newer], displayed, []);
  release(); await pending;
  displayed.shots[0].note = 'my subsequent note';
  client.mark(displayed, []);
  try { await client.save(displayed, project.name, []); } catch (error) {
    assert.equal(error.status, 409, 'only an explicit conflict is an acceptable rejection');
  }
  console.log('P5 late receipt:', JSON.stringify({
    sent: sent.map(body => body.updates.map(row => ({revision: row.expected_revision, content: row.content}))),
    final: server.get('shot-x'), state: client.drafts.entries.get('shot-x').state,
  }));
  assert.equal(server.get('shot-x').content.shot.action, 'other page v3');
});
