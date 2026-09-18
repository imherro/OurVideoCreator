"""Small opt-in business-role layer over existing membership and object history.

Mutations use the existing identity barrier, so role changes and object writes serialize.
Role names intentionally differ from legacy Production editor/manager levels.
"""
import time

from fastapi import HTTPException
from psycopg import sql

from . import collaboration as collab, identity, owned_content as owned, store as s

ROLES = {'producer', 'writer', 'artist', 'generator', 'editor'}
CONTENT_ROLE = {'chapter': 'writer', 'script': 'writer', 'visual_card': 'artist',
                'shot': 'generator', 'node': 'generator', 'graph': 'generator',
                'director': 'generator', 'timeline': 'generator'}
DEFAULT_ROLES = {'writer', 'artist', 'editor'}


def require_content_role(c, row):
    if workflow(c, row['production_id']):
        require_role(c, row['production_id'], CONTENT_ROLE[row['kind']])


def require_writer(c, production_id, *, planning=False):
    if not workflow(c, production_id):
        identity.require_production(c, collab.live_principal(c), production_id, 'manager' if planning else 'editor')
        return
    require_role(c, production_id, 'writer')
    if planning and default_assignee(c, production_id, 'writer') != identity.current().user_id:
        raise HTTPException(403, '作品改编策划由默认编剧负责，请先明确分工')


def require_chapter_cleanup(c, production_id):
    """Writer-owned chapter cleanup; legacy projects retain manager restriction."""
    if workflow(c,production_id):
        require_role(c,production_id,'writer')
    else:
        identity.require_production(c,collab.live_principal(c),production_id,'manager')


def creation_assignee(c, production_id, project_id, kind, *, initialization=False):
    actor = collab.live_principal(c)
    if workflow(c, production_id) and not initialization:
        require_role(c, production_id, CONTENT_ROLE[kind])
        if CONTENT_ROLE[kind] == 'generator':
            assigned = default_assignee(c, production_id, 'generator', project_id=project_id)
            if assigned != actor.user_id:
                raise HTTPException(403, '请由本集制作负责人创建制作内容')
    return default_assignee(c, production_id, CONTENT_ROLE[kind], project_id=project_id, legacy_user_id=actor.user_id)


def workflow(c, production_id):
    return c.execute('SELECT * FROM production_workflows WHERE production_id=%s', (production_id,)).fetchone()


def planning_epoch(c, production_id):
    # The existing workflow revision fences all staffing changes, including ABA.
    # Legacy productions retain their historical zero epoch.
    state=workflow(c,production_id)
    return state['revision'] if state else 0


def permission_summary(c, production_id, principal):
    if not workflow(c,production_id):return {}
    business=roles(c,production_id,principal.user_id)
    return {'workflow_enabled':True,'business_roles':sorted(business),
            'can_manage':'producer' in business,'can_generate':bool(business & {'writer','artist','generator'}),
            'can_plan':'writer' in business and default_assignee(c,production_id,'writer')==principal.user_id,
            'legacy_document_write':False}


def roles(c, production_id, user_id):
    # Stored role rows never revive rights after team/production removal.
    return {row['role'] for row in c.execute('''SELECT r.role FROM production_business_roles r
        JOIN productions p ON p.id=r.production_id JOIN users u ON u.id=r.user_id AND u.is_active
        JOIN workspace_members wm ON wm.workspace_id=p.workspace_id AND wm.user_id=u.id
        JOIN production_members pm ON pm.production_id=p.id AND pm.user_id=u.id
        WHERE r.production_id=%s AND r.user_id=%s''', (production_id, user_id))}


def require_role(c, production_id, role, *, user_id=None):
    actor_id = user_id or collab.live_principal(c).user_id
    if role not in roles(c, production_id, actor_id):
        raise HTTPException(403, '当前作品业务角色无权执行此操作')


def _member(c, production_id, user_id):
    row = c.execute('''SELECT u.id FROM users u JOIN productions p ON p.id=%s
        JOIN workspace_members wm ON wm.workspace_id=p.workspace_id AND wm.user_id=u.id
        JOIN production_members pm ON pm.production_id=p.id AND pm.user_id=u.id
        WHERE u.id=%s AND u.is_active''', (production_id, user_id)).fetchone()
    if not row:
        raise HTTPException(422, '请先将有效账号加入本作品')


def _lock(c, production_id, revision):
    identity.lock_identity_invariants(c)
    actor = collab.live_principal(c)
    identity.require_production(c, actor, production_id, 'viewer')
    row = c.execute('SELECT * FROM production_workflows WHERE production_id=%s FOR UPDATE', (production_id,)).fetchone()
    if not row:
        raise HTTPException(409, '作品尚未启用五角色流程')
    require_role(c, production_id, 'producer')
    if type(revision) is not int or row['revision'] != revision:
        raise HTTPException(409, '分工已更新，请刷新核对后重试')
    return row


def _changed(c, production_id, action, payload):
    c.execute('UPDATE production_workflows SET revision=revision+1,updated=%s WHERE production_id=%s',
              (time.time(), production_id))
    identity.audit(c, 'workflow.' + action, 'production', production_id,
                   production_id=production_id, payload=payload)
    for row in c.execute('SELECT id FROM projects WHERE production_id=%s ORDER BY id', (production_id,)):
        s.event(row['id'], {'type': 'workflow', 'action': action}, connection=c)
    return workflow(c, production_id)


def enable(c, production_id):
    """Explicit opt-in by a legacy manager; preserve every existing assignment."""
    identity.lock_identity_invariants(c)
    actor = collab.live_principal(c)
    identity.require_production(c, actor, production_id, 'manager')
    if workflow(c, production_id):
        raise HTTPException(409, '作品已启用五角色流程')
    now = time.time()
    # Workspace owner may not have an explicit Production membership yet.
    c.execute('''INSERT INTO production_members(production_id,user_id,role,created)
        VALUES(%s,%s,'manager',%s) ON CONFLICT(production_id,user_id) DO NOTHING''',
        (production_id, actor.user_id, now))
    c.execute('INSERT INTO production_workflows(production_id,created,updated) VALUES(%s,%s,%s)',
              (production_id, now, now))
    c.execute("INSERT INTO production_business_roles VALUES(%s,%s,'producer')", (production_id, actor.user_id))
    identity.audit(c, 'workflow.enable', 'production', production_id, production_id=production_id,
                   payload={'assignments_preserved': True})
    return workflow(c, production_id)


def _transfer_object(c, row, assignee_id):
    updated = c.execute('''UPDATE collaboration_objects SET assignee_id=%s,
        assignment_epoch=assignment_epoch+1,revision=revision+1,updated_by=%s,updated=%s,
        lease_hash=NULL,lease_user_id=NULL,lease_expires=NULL,lease_epoch=lease_epoch+1
        WHERE id=%s RETURNING *''', (assignee_id, identity.current().user_id, time.time(), row['id'])).fetchone()
    # Shared visual cards notify all episodes; project-local rows notify one.
    collab.record(c, updated, 'workflow.assign', updated['project_id'])


def _transfer_owned(c, production_id, kind, target_id, assignee_id):
    row = owned.load(c, production_id, kind, target_id, write=True)
    owned.history_before(c, row, 'workflow.assign')
    table, key = ('episode_scripts', 'project_id') if kind == 'script' else ('source_chapters', 'id')
    c.execute(sql.SQL('UPDATE {} SET assignee_id=%s,assignment_epoch=assignment_epoch+1,'
        'revision=revision+1,updated_by=%s,updated=%s WHERE {}=%s').format(sql.Identifier(table), sql.Identifier(key)),
        (assignee_id, identity.current().user_id, time.time(), target_id))
    owned.notify(c, owned.load(c, production_id, kind, target_id), 'workflow.assign')


def _release_lost_roles(c, production_id, user_id, lost):
    kinds = [kind for kind, role in CONTENT_ROLE.items() if role in lost and kind not in {'chapter', 'script'}]
    if kinds:
        for row in c.execute('''SELECT * FROM collaboration_objects WHERE production_id=%s
            AND assignee_id=%s AND kind=ANY(%s) ORDER BY id FOR UPDATE''', (production_id, user_id, kinds)).fetchall():
            _transfer_object(c, row, None)
    if 'writer' in lost:
        # Existing revoke includes trashed chapters/scripts and appends history.
        owned.revoke(c, user_id, production_id=production_id)
    for role in lost & DEFAULT_ROLES:
        c.execute(sql.SQL('UPDATE production_workflows SET {}=NULL WHERE production_id=%s AND {}=%s').format(
            sql.Identifier(role + '_id'), sql.Identifier(role + '_id')), (production_id, user_id))
    for role in lost & {'writer', 'generator', 'editor'}:
        c.execute(sql.SQL('UPDATE episode_staff SET {}=NULL WHERE {}=%s AND project_id IN '
            '(SELECT id FROM projects WHERE production_id=%s)').format(sql.Identifier(role + '_id'), sql.Identifier(role + '_id')),
            (user_id, production_id))


def revoke_membership(c, user_id, *, production_id=None, workspace_id=None, lost_access_only=False):
    """Called inside the existing identity-revocation transaction, before object locks."""
    rows = c.execute('''SELECT DISTINCT r.production_id FROM production_business_roles r
        JOIN productions p ON p.id=r.production_id WHERE r.user_id=%s
        AND (%s::text IS NULL OR p.id=%s) AND (%s::text IS NULL OR p.workspace_id=%s)
        ORDER BY r.production_id''', (user_id, production_id, production_id, workspace_id, workspace_id)).fetchall()
    for row in rows:
        pid = row['production_id']
        # A workspace owner demotion need not revoke explicit business roles.
        if lost_access_only and roles(c, pid, user_id):
            continue
        stored = {r['role'] for r in c.execute('SELECT role FROM production_business_roles WHERE production_id=%s AND user_id=%s', (pid,user_id))}
        if 'producer' in stored:
            others = c.execute("SELECT user_id FROM production_business_roles WHERE production_id=%s AND role='producer' AND user_id<>%s", (pid,user_id))
            if not any('producer' in roles(c,pid,r['user_id']) for r in others):
                raise HTTPException(409, '该账号仍是作品唯一制片人，请先转交作品职责')
        c.execute('DELETE FROM production_business_roles WHERE production_id=%s AND user_id=%s', (pid,user_id))
        _release_lost_roles(c,pid,user_id,stored)
        _changed(c,pid,'member.revoke',{'user_id':user_id})


def assign_business_items(c, production_id, kind, items, user_id, revision):
    """Business-list bulk assignment, with per-row concurrency checks, all or nothing."""
    _lock(c,production_id,revision)
    if kind not in {'chapter','visual_card'} or not isinstance(items,list) or not 1 <= len(items) <= 200:
        raise HTTPException(422,'请选择 1–200 个章节或共享资产')
    ids=[v.get('id') for v in items if isinstance(v,dict)]
    if len(ids)!=len(items) or any(not isinstance(v,str) or not v for v in ids) or len(set(ids))!=len(ids):
        raise HTTPException(422,'分工清单无效或重复')
    if user_id is not None:
        require_role(c,production_id,CONTENT_ROLE[kind],user_id=user_id)
    for item in sorted(items,key=lambda v:v['id']):
        if kind=='chapter':
            row=owned.load(c,production_id,'chapter',item['id'],write=True)
        else:
            row=c.execute("SELECT * FROM collaboration_objects WHERE id=%s AND production_id=%s AND kind='visual_card' AND NOT deleted FOR UPDATE",
                          (item['id'],production_id)).fetchone()
            if not row:raise HTTPException(404,'共享资产不存在')
        collab.expected(row,item.get('revision'),item.get('assignment_epoch'))
        if kind=='chapter':_transfer_owned(c,production_id,kind,item['id'],user_id)
        else:_transfer_object(c,row,user_id)
    return _changed(c,production_id,'business.assign',{'kind':kind,'count':len(items),'user_id':user_id})


def set_roles(c, production_id, user_id, selected, revision):
    _lock(c, production_id, revision)
    _member(c, production_id, user_id)
    if not isinstance(selected, list) or any(not isinstance(v, str) or v not in ROLES for v in selected):
        raise HTTPException(422, '业务角色只能从固定五种角色选择')
    selected = set(selected)
    old = roles(c, production_id, user_id)
    if 'producer' in old and 'producer' not in selected:
        others = c.execute("SELECT user_id FROM production_business_roles WHERE production_id=%s AND role='producer' AND user_id<>%s",
                           (production_id, user_id)).fetchall()
        if not any('producer' in roles(c, production_id, r['user_id']) for r in others):
            raise HTTPException(409, '至少保留一名有效制片人，请先转交')
    c.execute('DELETE FROM production_business_roles WHERE production_id=%s AND user_id=%s', (production_id, user_id))
    for role in sorted(selected):
        c.execute('INSERT INTO production_business_roles VALUES(%s,%s,%s)', (production_id, user_id, role))
    _release_lost_roles(c, production_id, user_id, old - selected)
    return _changed(c, production_id, 'roles', {'user_id': user_id, 'roles': sorted(selected)})


def set_default(c, production_id, role, user_id, revision):
    _lock(c, production_id, revision)
    if role not in DEFAULT_ROLES:
        raise HTTPException(422, '只有编剧、资产师、剪辑师设置作品默认负责人')
    if user_id is not None:
        require_role(c, production_id, role, user_id=user_id)
    c.execute(sql.SQL('UPDATE production_workflows SET {}=%s WHERE production_id=%s').format(sql.Identifier(role + '_id')),
              (user_id, production_id))
    return _changed(c, production_id, 'default', {'role': role, 'user_id': user_id})


def default_assignee(c, production_id, role, *, project_id=None, legacy_user_id=None):
    config = workflow(c, production_id)
    if not config:
        return legacy_user_id
    candidate = None
    if project_id and role in {'writer', 'generator', 'editor'}:
        row = c.execute('SELECT es.* FROM episode_staff es JOIN projects p ON p.id=es.project_id '
                        'WHERE es.project_id=%s AND p.production_id=%s', (project_id, production_id)).fetchone()
        candidate = row[role + '_id'] if row else None
    if not candidate and role in DEFAULT_ROLES:
        candidate = config[role + '_id']
    if candidate:
        return candidate if role in roles(c, production_id, candidate) else None
    # A generator must always be explicitly assigned to the episode.
    if role == 'generator':
        return None
    candidates = [r['user_id'] for r in c.execute('SELECT user_id FROM production_business_roles WHERE production_id=%s AND role=%s',
                                                (production_id, role)) if role in roles(c, production_id, r['user_id'])]
    return candidates[0] if len(candidates) == 1 else None


def assign_episode(c, production_id, project_id, role, user_id, revision, *, confirm_special=False):
    _lock(c, production_id, revision)
    if role not in {'writer', 'generator', 'editor'}:
        raise HTTPException(422, '分集只分配编剧、抽卡师或剪辑师')
    project = c.execute('''SELECT id FROM projects WHERE id=%s AND production_id=%s AND NOT EXISTS
        (SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=projects.id)''', (project_id, production_id)).fetchone()
    if not project:
        raise HTTPException(404, '分集不存在')
    if user_id is not None:
        require_role(c, production_id, role, user_id=user_id)
    previous = c.execute('SELECT * FROM episode_staff WHERE project_id=%s', (project_id,)).fetchone()
    if role == 'generator':
        rows = c.execute('''SELECT * FROM collaboration_objects WHERE project_id=%s AND production_id=%s
            AND kind IN ('shot','node','graph','director','timeline') ORDER BY id FOR UPDATE''', (project_id, production_id)).fetchall()
        usual = previous['generator_id'] if previous else None
        special = [r for r in rows if r['assignee_id'] not in (None, usual, user_id)]
        if special and not confirm_special:
            raise HTTPException(409, {'type': 'special_assignments', 'count': len(special),
                                      'message': '整集转交将覆盖已有特殊分配，请确认'})
        for row in rows:
            _transfer_object(c, row, user_id)
    if role == 'writer' and c.execute('SELECT 1 FROM episode_scripts WHERE project_id=%s', (project_id,)).fetchone():
        script_owner = user_id or default_assignee(c, production_id, 'writer')
        _transfer_owned(c, production_id, 'script', project_id, script_owner)
    c.execute('INSERT INTO episode_staff(project_id) VALUES(%s) ON CONFLICT DO NOTHING', (project_id,))
    c.execute(sql.SQL('UPDATE episode_staff SET {}=%s WHERE project_id=%s').format(sql.Identifier(role + '_id')), (user_id, project_id))
    return _changed(c, production_id, 'episode.assign', {'project_id': project_id, 'role': role, 'user_id': user_id})
