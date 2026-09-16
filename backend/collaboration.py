"""Object-local editing transactions. No network or filesystem work here."""
from __future__ import annotations

import json
import re
import secrets
import time

from fastapi import HTTPException

from . import identity, model_validation, store as s
from . import collaboration_validation as validation

KINDS = {'shot', 'node', 'visual_card', 'graph', 'timeline', 'director'}
LEASE_SECONDS = 90


def public(row):
    value = {key: val for key, val in dict(row).items() if key not in {'lease_hash', 'workspace_id'}}
    if isinstance(value['content'], str):
        value['content'] = json.loads(value['content'])
    return value


def lock_identity(connection):
    # Shared mode allows unrelated objects to save concurrently. Membership
    # mutations already take this lock exclusively in P3.
    connection.execute('SELECT pg_advisory_xact_lock_shared(%s)', (identity.IDENTITY_INVARIANT_LOCK_KEY,))


def live_principal(connection):
    actor = identity.current()
    row = connection.execute('''SELECT u.is_active,se.expires,se.revoked_at
        FROM users u JOIN sessions se ON se.user_id=u.id
        WHERE u.id=%s AND se.token_hash=%s''', (actor.user_id, actor.session_hash)).fetchone()
    # Called AFTER object-lock wait, never with request-start time.
    if not row or not row['is_active'] or row['revoked_at'] is not None or row['expires'] <= time.time():
        raise HTTPException(401, '会话已失效，请重新登录')
    return actor


def project_scope(connection, project_id, needed='viewer'):
    row = connection.execute('''SELECT e.id,e.production_id,p.workspace_id FROM projects e
        JOIN productions p ON p.id=e.production_id WHERE e.id=%s AND NOT EXISTS(
        SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=e.id)''', (project_id,)).fetchone()
    if not row:
        raise HTTPException(404, '项目不存在')
    identity.require_production(connection, live_principal(connection), row['production_id'], needed)
    return row


def load(connection, project_id, object_id, *, write=False):
    if write:
        lock_identity(connection)
    scope = project_scope(connection, project_id)
    # Lock only the object; no Episode/Production-wide content lock.
    row = connection.execute('''SELECT o.*,p.workspace_id FROM collaboration_objects o
        JOIN productions p ON p.id=o.production_id
        WHERE o.id=%s AND o.production_id=%s AND (o.project_id=%s OR o.project_id IS NULL)
        AND NOT o.deleted''' + (' FOR UPDATE OF o' if write else ''),
        (object_id, scope['production_id'], project_id)).fetchone()
    live_principal(connection)
    if not row or row['production_id'] != scope['production_id'] or row['project_id'] not in (None, project_id):
        raise HTTPException(404, '对象不存在')
    return row


def conflict(row, kind='revision'):
    raise HTTPException(409, {'type': kind, 'object_id': row['id'], 'revision': row['revision'],
                             'assignment_epoch': row['assignment_epoch'], 'updated': row['updated']})


def expected(row, revision, assignment_epoch):
    if row['assignment_epoch'] != assignment_epoch:
        conflict(row, 'assignment')
    if row['revision'] != revision:
        conflict(row)


def editable(connection, row):
    actor = live_principal(connection)
    identity.require_production(connection, actor, row['production_id'], 'editor')
    if row['kind'] != 'graph' and row['assignee_id'] != actor.user_id:
        raise HTTPException(403, '仅对象负责人可编辑；管理者须先显式接管')
    return actor


def validate_lease(row, token, epoch):
    if (not token or row['lease_user_id'] != identity.current().user_id or
            row['lease_epoch'] != epoch or row['lease_hash'] != identity.digest(token) or
            (row['lease_expires'] or 0) <= time.time()):
        conflict(row, 'lease')


def record(connection, row, action, project_id):
    snapshot = public(row)
    connection.execute('''INSERT INTO collaboration_history(object_id,revision,snapshot,actor_user_id,action,created)
        VALUES(%s,%s,%s,%s,%s,%s)''', (row['id'], row['revision'], s.dumps(snapshot),
                                      identity.current().user_id, action, time.time()))
    notify(connection, row, action, project_id)


def notify(connection, row, action, project_id):
    identity.audit(connection, 'object.' + action, row['kind'], row['id'],
                   workspace_id=row.get('workspace_id'), production_id=row['production_id'],
                   payload={'revision': row['revision'], 'assignment_epoch': row['assignment_epoch']})
    targets = [project_id] if row['project_id'] else [r['id'] for r in connection.execute(
        'SELECT id FROM projects WHERE production_id=%s ORDER BY id', (row['production_id'],))]
    for target in targets:
        s.event(target, {'type': 'object', 'object_id': row['id'], 'kind': row['kind'],
                         'revision': row['revision'], 'assignment_epoch': row['assignment_epoch'],
                         'action': action}, connection=connection)


def validate_content(kind, content):
    if kind not in KINDS or not isinstance(content, dict):
        raise HTTPException(422, '对象类型或内容无效')
    # These are server fields, never content fields or accepted aliases.
    if set(content) & {'assignee_id', 'created_by', 'updated_by', 'workspace_id', 'production_id',
                       'assignment_epoch', 'revision', 'lease_hash', 'lease_token'}:
        raise HTTPException(422, '不能在对象内容中伪造权限或版本字段')
    model_validation.reject_private_overrides(content)
    if len(s.dumps(content)) > 4_000_000:
        raise HTTPException(413, '对象内容过大，请先上传素材')
    validation.envelope(kind, content)


def validate_asset_references(connection, production_id, content):
    """All persisted media references, including nested Twick/voice payloads.

    A URL is not ownership evidence; the stable ID must resolve in this work.
    Never reveal which other Production owns a rejected asset.
    """
    references = set()

    def walk(value, key=''):
        normalized = key.replace('_', '').lower()
        if isinstance(value, dict):
            for child_key, child in value.items():
                walk(child, child_key)
        elif isinstance(value, list):
            for child in value:
                walk(child, key)
        elif isinstance(value, str) and value:
            if normalized.endswith(('assetid', 'assetids')) or normalized == 'audioid':
                references.add(value)
            elif re.fullmatch(r'asset-[0-9a-f]{32}', value):
                references.add(value)
            else:
                match = re.search(r'/api/assets/([^/?#]+)/file(?:[?#]|$)', value)
                if match:
                    references.add(match.group(1))

    walk(content)
    for asset_id in sorted(references):
        if not connection.execute('''SELECT 1 FROM assets a WHERE a.id=%s AND a.production_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='asset' AND d.item_id=a.id)''',
            (asset_id, production_id)).fetchone():
            raise HTTPException(422, '素材不存在或不属于当前作品')


def create(connection, project_id, kind, content, *, validated=False):
    validate_content(kind, content)
    lock_identity(connection)
    scope = project_scope(connection, project_id, 'editor')
    validate_asset_references(connection, scope['production_id'], content)
    if not validated:
        validation.ownership(connection, {**scope, 'project_id': project_id}, kind, content)
        validation.visual_transition(connection, scope['production_id'], kind, content)
    key = validation.envelope(kind, content)
    connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                       ('object-key:' + scope['production_id'] + ':' + ('' if kind == 'visual_card' else project_id) + ':' + kind + ':' + key,))
    if connection.execute('''SELECT 1 FROM collaboration_objects WHERE production_id=%s
        AND project_id IS NOT DISTINCT FROM %s AND kind=%s AND object_key=%s''',
        (scope['production_id'], None if kind == 'visual_card' else project_id, kind, key)).fetchone():
        raise HTTPException(409, '该对象编号已存在；请读取当前对象而不是重新创建')
    # Singleton uniqueness is serialized without locking unrelated objects.
    if kind in {'graph', 'timeline', 'director'}:
        connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                           ('collaboration:' + project_id + ':' + kind,))
        if connection.execute('SELECT 1 FROM collaboration_objects WHERE project_id=%s AND kind=%s AND NOT deleted',
                              (project_id, kind)).fetchone():
            raise HTTPException(409, '该分集对象已存在')
    actor = live_principal(connection)
    now = time.time()
    row = connection.execute('''INSERT INTO collaboration_objects
        (id,production_id,project_id,kind,object_key,content,assignee_id,created_by,updated_by,created,updated)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *''',
        (s.uid('object-'), scope['production_id'], None if kind == 'visual_card' else project_id,
         kind, key, s.dumps(content), actor.user_id, actor.user_id, actor.user_id, now, now)).fetchone()
    row['workspace_id'] = scope['workspace_id']
    record(connection, row, 'create', project_id)
    return public(row)


def initialize_episode(connection, project_id):
    """Called only when creating a new Episode, never while reading old data."""
    existing = connection.execute('SELECT object_collaboration FROM projects WHERE id=%s', (project_id,)).fetchone()
    if not existing or existing['object_collaboration']:
        return
    create(connection, project_id, 'graph', {'edges': [], 'positions': {}, 'nodeOrder': [], 'shotOrder': []})
    create(connection, project_id, 'timeline', {'timeline': {'version': 2, 'backgroundColor': '#000000', 'tracks': []}})
    create(connection, project_id, 'director', {'stage': {'objects': [], 'views': [], 'camera': {
        'yaw': 25, 'pitch': 12, 'distance': 8, 'fov': 45, 'targetHeight': 1}}})
    connection.execute('UPDATE projects SET object_collaboration=TRUE WHERE id=%s', (project_id,))


def save(connection, project_id, object_id, *, expected_revision, assignment_epoch,
         content, lease_token=None, lease_epoch=None):
    return commands(connection, project_id, creates=[], deletes=[], updates=[{
        'id': object_id, 'expected_revision': expected_revision, 'assignment_epoch': assignment_epoch,
        'content': content, 'lease_token': lease_token, 'lease_epoch': lease_epoch}])['updated'][0]


def replace_content(connection, row, content, project_id, action):
    updated = connection.execute('''UPDATE collaboration_objects SET content=%s,revision=revision+1,
        status='in_progress',updated_by=%s,updated=%s WHERE id=%s AND revision=%s RETURNING *''',
        (s.dumps(content), identity.current().user_id, time.time(), row['id'], row['revision'])).fetchone()
    if not updated:
        conflict(row)
    updated['workspace_id'] = row['workspace_id']
    record(connection, updated, action, project_id)
    return public(updated)


def assign(connection, project_id, object_id, *, expected_revision, assignment_epoch, assignee_id):
    row = load(connection, project_id, object_id, write=True)
    actor = live_principal(connection)
    identity.require_production(connection, actor, row['production_id'], 'manager')
    expected(row, expected_revision, assignment_epoch)
    if assignee_id is not None:
        target = connection.execute('SELECT * FROM users WHERE id=%s AND is_active', (assignee_id,)).fetchone()
        if not target:
            raise HTTPException(422, '负责人必须是有效作品编辑成员')
        target_actor = identity.Principal(target['id'], target['phone'], target['nickname'], target['platform_role'], '', 0)
        if not identity.can_production(connection, target_actor, row['production_id'], 'editor'):
            raise HTTPException(422, '负责人必须是有效作品编辑成员')
    updated = connection.execute('''UPDATE collaboration_objects SET assignee_id=%s,
        assignment_epoch=assignment_epoch+1,revision=revision+1,updated_by=%s,updated=%s,
        lease_hash=NULL,lease_user_id=NULL,lease_expires=NULL,lease_epoch=lease_epoch+1
        WHERE id=%s RETURNING *''', (assignee_id, actor.user_id, time.time(), object_id)).fetchone()
    updated['workspace_id'] = row['workspace_id']
    record(connection, updated, 'assign', project_id)
    return public(updated)


def lease(connection, project_id, object_id, *, action, assignment_epoch, token=None, lease_epoch=None):
    row = load(connection, project_id, object_id, write=True)
    editable(connection, row)
    if row['kind'] != 'timeline':
        raise HTTPException(422, '只有剪辑时间线需要独占租约')
    if row['assignment_epoch'] != assignment_epoch:
        conflict(row, 'assignment')
    if action == 'acquire':
        if (row['lease_expires'] or 0) > time.time():
            conflict(row, 'lease_busy')
        token = secrets.token_urlsafe(32)
        lease_epoch = row['lease_epoch'] + 1
    elif action in {'renew', 'release'}:
        validate_lease(row, token, lease_epoch)
    else:
        raise HTTPException(422, '租约动作无效')
    expiry = None if action == 'release' else time.time() + LEASE_SECONDS
    connection.execute('''UPDATE collaboration_objects SET lease_hash=%s,lease_user_id=%s,
        lease_epoch=%s,lease_expires=%s WHERE id=%s''',
        (None if action == 'release' else identity.digest(token),
         None if action == 'release' else identity.current().user_id, lease_epoch, expiry, object_id))
    notify(connection, row, 'lease.' + action, project_id)
    return {'object_id': object_id, 'token': None if action == 'release' else token,
            'lease_epoch': lease_epoch, 'expires': expiry, 'assignment_epoch': assignment_epoch}


def review(connection, project_id, object_id, *, expected_revision, assignment_epoch, action):
    row = load(connection, project_id, object_id, write=True)
    if action == 'submit':
        editable(connection, row)
        target = 'pending_review'
        if row['status'] not in {'in_progress', 'returned'}:
            conflict(row, 'review_state')
    elif action in {'approve', 'return'}:
        identity.require_production(connection, live_principal(connection), row['production_id'], 'manager')
        if row['status'] != 'pending_review':
            conflict(row, 'review_state')
        target = 'completed' if action == 'approve' else 'returned'
    else:
        raise HTTPException(422, '审核动作无效')
    expected(row, expected_revision, assignment_epoch)
    updated = connection.execute('''UPDATE collaboration_objects SET status=%s,revision=revision+1,
        updated_by=%s,updated=%s WHERE id=%s RETURNING *''',
        (target, identity.current().user_id, time.time(), object_id)).fetchone()
    updated['workspace_id'] = row['workspace_id']
    record(connection, updated, 'review.' + action, project_id)
    return public(updated)


def restore(connection, project_id, object_id, *, expected_revision, assignment_epoch, revision,
            lease_token=None, lease_epoch=None):
    # Read immutable history first, then use the SAME ordered dependency locks
    # and prospective validation as save. Prelocking only the graph here could
    # invert the dependency object's lock order during concurrent reassignment.
    load(connection, project_id, object_id)
    historical = connection.execute('SELECT snapshot FROM collaboration_history WHERE object_id=%s AND revision=%s',
                                    (object_id, revision)).fetchone()
    if not historical:
        raise HTTPException(404, '历史版本不存在')
    content = json.loads(historical['snapshot'])['content']
    return commands(connection, project_id, creates=[], deletes=[], updates=[{
        'id': object_id, 'expected_revision': expected_revision, 'assignment_epoch': assignment_epoch,
        'content': content, 'lease_token': lease_token, 'lease_epoch': lease_epoch}], _action='restore')['updated'][0]


def comment(connection, project_id, object_id, body):
    row = load(connection, project_id, object_id, write=True)
    if not body.strip() or len(body) > 8000:
        raise HTTPException(422, '评论必须为 1–8000 个字符')
    result = connection.execute('''INSERT INTO collaboration_comments(id,object_id,actor_user_id,body,created)
        VALUES(%s,%s,%s,%s,%s) RETURNING *''',
        (s.uid('comment-'), object_id, identity.current().user_id, body.strip(), time.time())).fetchone()
    notify(connection, row, 'comment', project_id)
    return dict(result)


def batch_save(connection, project_id, operations):
    return commands(connection, project_id, creates=[], updates=operations, deletes=[])['updated']


def revoke_assignments(connection, user_id, *, production_id=None, workspace_id=None, lost_access_only=False):
    """Called under P3's EXCLUSIVE identity lock, in the membership transaction.

    Content is retained. Epoch increments even when a later rejoin restores the
    very same membership/assignee. No old page or lease can revive itself.
    """
    from .owned_content import revoke
    revoke(connection,user_id,production_id=production_id,workspace_id=workspace_id,lost_access_only=lost_access_only)
    rows = connection.execute('''SELECT o.*,p.workspace_id FROM collaboration_objects o
        JOIN productions p ON p.id=o.production_id WHERE o.assignee_id=%s AND NOT o.deleted
        AND (%s::text IS NULL OR o.production_id=%s)
        AND (%s::text IS NULL OR p.workspace_id=%s) ORDER BY o.id FOR UPDATE OF o''',
        (user_id, production_id, production_id, workspace_id, workspace_id)).fetchall()
    target = identity.Principal(user_id, '', '', 'user', '', 0)
    for row in rows:
        if lost_access_only and identity.can_production(connection, target, row['production_id'], 'editor'):
            continue
        updated = connection.execute('''UPDATE collaboration_objects SET assignee_id=NULL,
            assignment_epoch=assignment_epoch+1,revision=revision+1,updated_by=%s,updated=%s,
            lease_hash=NULL,lease_user_id=NULL,lease_expires=NULL,lease_epoch=lease_epoch+1
            WHERE id=%s RETURNING *''', (identity.current().user_id, time.time(), row['id'])).fetchone()
        updated['workspace_id'] = row['workspace_id']
        record(connection, updated, 'revoke', row['project_id'])


def commands(connection, project_id, *, creates, updates, deletes, _action='save', _promote_node_id=None):
    """Atomic structural import/edit. Validate the prospective state FIRST.

    Only caller-selected objects are written; the rest are read for reference
    integrity, never replaced by a stale aggregate snapshot.
    """
    # The internal storyboard importer can replace 100 shots, add 100 cards,
    # and delete 100 old shots, plus its source and graph. Public commands stay
    # at their existing 200-object bound.
    limit=302 if _action=='storyboard.adopt' else 200
    if not 1 <= len(creates) + len(updates) + len(deletes) <= limit:
        raise HTTPException(422, f'命令必须包含 1–{limit} 个对象')
    lock_identity(connection)
    scope = project_scope(connection, project_id, 'editor')
    actor = live_principal(connection)
    modifications = updates + deletes
    if len({item['id'] for item in modifications}) != len(modifications):
        raise HTTPException(422, '命令不能重复操作同一对象')
    requested={item['id']:item for item in modifications}
    lock_ids=set(requested)
    dependency_targets=set()
    for item in creates:
        validate_content(item['kind'],item['content'])
    for item in updates:
        prior=connection.execute('''SELECT kind,content FROM collaboration_objects WHERE id=%s
            AND production_id=%s AND (project_id=%s OR project_id IS NULL) AND NOT deleted''',
            (item['id'],scope['production_id'],project_id)).fetchone()
        if prior:
            validate_content(prior['kind'],item['content'])
        if not prior or prior['kind']!='graph':
            continue
        old_edges={edge['id']:edge for edge in validation.object_content(prior)['edges']}
        new_edges={edge['id']:edge for edge in item['content'].get('edges',[]) if isinstance(edge,dict) and 'id' in edge}
        for edge_id in old_edges.keys()|new_edges.keys():
            if old_edges.get(edge_id)!=new_edges.get(edge_id):
                for edge in (old_edges.get(edge_id),new_edges.get(edge_id)):
                    if edge and isinstance(edge.get('target'),str):
                        dependency_targets.add(edge['target'])
    if dependency_targets:
        for row in connection.execute('''SELECT * FROM collaboration_objects WHERE production_id=%s
            AND (project_id=%s OR project_id IS NULL) AND NOT deleted''',(scope['production_id'],project_id)):
            value=validation.object_content(row)
            owned=validation.node_ids(row['kind'],value)
            if row['kind']=='visual_card':
                owned={'visual-version:'+vid for vid in value['versions']}
            if owned & dependency_targets:
                lock_ids.add(row['id'])
    locked = {}
    for object_id in sorted(lock_ids):
        row = load(connection, project_id, object_id, write=True)
        if object_id in requested:
            item=requested[object_id]
            editable(connection, row)
            expected(row, item['expected_revision'], item['assignment_epoch'])
        locked[row['id']] = row
    for item in deletes:
        row = locked[item['id']]
        if not (_action=='script_promote' and row['kind']=='node' and row['id']==_promote_node_id):
            identity.require_production(connection, actor, row['production_id'], 'manager')
        if row['kind'] in {'graph', 'timeline', 'director', 'visual_card'}:
            raise HTTPException(422, '固定对象不可删除；视觉卡请保留版本并标记弃用')
    structural = bool(creates or deletes) or any(
        validation.node_ids(locked[item['id']]['kind'], item['content']) !=
        validation.node_ids(locked[item['id']]['kind'], validation.object_content(locked[item['id']]))
        for item in updates if locked[item['id']]['kind'] in {'shot','node'}
    )
    if structural:
        validation.structure_lock(connection, project_id)
    visual_changed = any(item['kind'] == 'visual_card' or (
        item['kind'] == 'shot' and item['content'].get('shot', {}).get('assetBindings')) for item in creates)
    visual_changed |= any(locked[item['id']]['kind'] in {'shot','visual_card'} for item in updates + deletes)
    if visual_changed:
        connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', ('visual-bindings:' + scope['production_id'],))
    for item in creates:
        validate_content(item['kind'], item['content'])
        validate_asset_references(connection, scope['production_id'], item['content'])
    for item in updates:
        row = locked[item['id']]
        validate_content(row['kind'], item['content'])
        validate_asset_references(connection, row['production_id'], item['content'])
        if validation.object_key(row) != validation.envelope(row['kind'], item['content']):
            raise HTTPException(422, '对象语义编号不可修改')
        if row['kind'] == 'timeline':
            validate_lease(row, item.get('lease_token'), item.get('lease_epoch'))
    all_before = list(connection.execute('SELECT * FROM collaboration_objects WHERE production_id=%s AND NOT deleted',
                                         (scope['production_id'],)))
    proposed = {row['id']: dict(row) for row in all_before}
    for item in deletes:
        proposed.pop(item['id'])
    for item in updates:
        proposed[item['id']]['content'] = item['content']
    for index, item in enumerate(creates):
        proposed['new:' + str(index)] = {'id':'new:' + str(index), 'kind':item['kind'], 'content':item['content'],
            'project_id':None if item['kind']=='visual_card' else project_id,
            'production_id':scope['production_id'], 'assignee_id':actor.user_id}
    identities, nodes = set(), set()
    for row in proposed.values():
        content = validation.object_content(row)
        key = (row['project_id'], row['kind'], validation.object_key(row))
        if key in identities:
            raise HTTPException(409, '对象编号已存在')
        identities.add(key)
        for nid in validation.node_ids(row['kind'],content):
            nid_key = (row['project_id'],nid)
            if nid_key in nodes:
                raise HTTPException(422, '节点不能同时属于自由对象和镜头，或属于两个镜头')
            nodes.add(nid_key)
    scoped = [row for row in proposed.values() if row['project_id'] in (None, project_id)]
    script = connection.execute('SELECT metadata FROM episode_scripts WHERE project_id=%s',(project_id,)).fetchone()
    if script and (project_id,json.loads(script['metadata']).get('projectionNodeId')) in nodes:
        raise HTTPException(422,'正式剧本投影不能声明为独立可写节点')
    if structural and (any(item['kind'] in {'shot','node'} for item in creates) or deletes):
        if not any(locked[item['id']]['kind']=='graph' for item in updates):
            raise HTTPException(422, '节点或镜头增删必须携带同一原子命令的结构版本')
    for item in updates:
        validation.graph_transition(connection, locked[item['id']], item['content'], scoped)
    if visual_changed:
        def visual_document(rows):
            result={'filmBible':{'visual':{'cards':{},'versions':{}}},'shots':[]}
            for row in rows:
                value=validation.object_content(row)
                if row['kind']=='shot':
                    result['shots'].append(value['shot'])
                elif row['kind']=='visual_card':
                    visual=result['filmBible']['visual']
                    visual['cards'][value['card']['id']]=value['card']
                    for vid, version in value['versions'].items():
                        if vid in visual['versions']:
                            raise HTTPException(422,'视觉版本编号不能属于多张卡片')
                        visual['versions'][vid]=version
            return result
        from .film_bible.versioning import validate_film_bible_transition
        validate_film_bible_transition(visual_document(all_before),visual_document(proposed.values()))
        for item in updates:
            if locked[item['id']]['kind']=='visual_card':
                previous=validation.object_content(locked[item['id']]).get('voice_profile')
                voice=item['content']['voice_profile']
                if previous and previous.get('status')=='locked' and voice!=previous:
                    if not voice or voice.get('status')!='draft' or voice.get('version',0)<=previous.get('version',0):
                        raise HTTPException(422,'已锁定音色不可原地修改；须派生新版本')
    # Acquire creation identity locks before the final lease clock check. A
    # uniqueness contender must not make an expired timeline token valid again.
    for item in sorted(creates, key=lambda value:(value['kind'],validation.envelope(value['kind'],value['content']))):
        key=validation.envelope(item['kind'],item['content'])
        connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
            ('object-key:'+scope['production_id']+':'+('' if item['kind']=='visual_card' else project_id)+':'+item['kind']+':'+key,))
        if item['kind'] in {'graph','timeline','director'}:
            connection.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                ('collaboration:'+project_id+':'+item['kind'],))
    live_principal(connection)
    for item in updates:
        if locked[item['id']]['kind']=='timeline':
            validate_lease(locked[item['id']],item.get('lease_token'),item.get('lease_epoch'))
    # No mutations above this line. Locks, ACL, all versions and references
    # have passed. The following writes/history/audit/events commit together.
    created = [create(connection, project_id, item['kind'], item['content'], validated=True) for item in creates]
    updated = [replace_content(connection, locked[item['id']], item['content'], project_id, _action) for item in updates]
    for item in deletes:
        row=locked[item['id']]
        removed=connection.execute('''UPDATE collaboration_objects SET deleted=TRUE,revision=revision+1,
            assignment_epoch=assignment_epoch+1,updated=%s,updated_by=%s,
            lease_hash=NULL,lease_user_id=NULL,lease_expires=NULL,lease_epoch=lease_epoch+1
            WHERE id=%s RETURNING *''',(time.time(),actor.user_id,row['id'])).fetchone()
        removed['workspace_id']=scope['workspace_id']
        record(connection,removed,'delete',project_id)
    return {'created':created,'updated':updated,'deleted':[item['id'] for item in deletes]}
