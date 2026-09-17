"""Short trash/restore transactions fence pre-trash editing credentials.

Container lifecycle uses the existing exclusive identity barrier BEFORE any row
locks. Ordinary independent object writes still share that barrier concurrently.
Content, assignees and stable asset IDs are never replaced by restoration.
"""
import json
import time

from fastapi import HTTPException

from . import collaboration as collab, identity, owned_content as owned, store as s


def authorize(c, kind, item_id):
    identity.lock_identity_invariants(c)
    actor = collab.live_principal(c)
    production_id = identity.production_for_resource(c, kind, item_id)
    if not production_id:
        raise HTTPException(404, '内容不存在')
    identity.require_production(c, actor, production_id, 'manager')
    return production_id


def protect_referenced_asset(c, production_id, asset_id):
    """Caller holds the exclusive lifecycle barrier against object writes.

    Check current objects, not immutable history. This also retains references
    in recoverable episodes until those references are explicitly removed.
    """
    rows = c.execute('''SELECT content FROM collaboration_objects
        WHERE production_id=%s AND NOT deleted''', (production_id,))
    for row in rows:
        content = json.loads(row['content'])
        if asset_id in collab.asset_references(content):
            raise HTTPException(409, '素材仍被作品内容引用，请先移除引用后再移入回收站。')


def fence_owned(c, kind, rows, action):
    table, key = ('episode_scripts', 'project_id') if kind == 'script' else ('source_chapters', 'id')
    for value in rows:
        row = {**dict(value), 'id': value[key], 'kind': kind}
        owned.history_before(c, row, action)
        updated = c.execute(f'''UPDATE {table} SET revision=revision+1,
            assignment_epoch=assignment_epoch+1,updated_by=%s,updated=%s
            WHERE {key}=%s RETURNING *''',
            (identity.current().user_id, time.time(), row['id'])).fetchone()
        owned.notify(c, {**row, **dict(updated), 'id': row['id']}, action)


def fence(c, kind, item_id, action):
    """Caller holds authorize's exclusive lock; history/events share the txn."""
    if kind == 'project':
        project = c.execute('''SELECT e.*,p.workspace_id FROM projects e
            JOIN productions p ON p.id=e.production_id WHERE e.id=%s FOR UPDATE OF e''',
            (item_id,)).fetchone()
        rows = c.execute('''SELECT * FROM collaboration_objects WHERE project_id=%s
            AND NOT deleted ORDER BY id FOR UPDATE''', (item_id,)).fetchall()
        # Production-wide visual cards remain usable in other episodes.
        for row in rows:
            updated = c.execute('''UPDATE collaboration_objects SET revision=revision+1,
                assignment_epoch=assignment_epoch+1,updated_by=%s,updated=%s,
                lease_hash=NULL,lease_user_id=NULL,lease_expires=NULL,lease_epoch=lease_epoch+1
                WHERE id=%s RETURNING *''',
                (identity.current().user_id, time.time(), row['id'])).fetchone()
            collab.record(c, {**dict(updated), 'workspace_id': project['workspace_id']}, action, item_id)
        scripts = c.execute('''SELECT sc.*,p.production_id,pr.workspace_id FROM episode_scripts sc
            JOIN projects p ON p.id=sc.project_id JOIN productions pr ON pr.id=p.production_id
            WHERE sc.project_id=%s FOR UPDATE OF sc''', (item_id,)).fetchall()
        fence_owned(c, 'script', scripts, action)
        c.execute('INSERT INTO revisions VALUES(%s,%s,%s,%s,%s)',
            (s.uid(), item_id, project['revision'], project['document'], time.time()))
        updated = c.execute('UPDATE projects SET revision=revision+1,updated=%s WHERE id=%s RETURNING revision',
            (time.time(), item_id)).fetchone()
        s.event(item_id, {'type': 'project', 'revision': updated['revision']}, connection=c)
    elif kind in ('source', 'chapter'):
        clause = 'sd.id=%s' if kind == 'source' else 'sc.id=%s'
        chapters = c.execute(f'''SELECT sc.*,sd.production_id,p.workspace_id FROM source_chapters sc
            JOIN source_documents sd ON sd.id=sc.source_id JOIN productions p ON p.id=sd.production_id
            WHERE {clause} ORDER BY sc.id FOR UPDATE OF sc''', (item_id,)).fetchall()
        fence_owned(c, 'chapter', chapters, action)
    # A session may expire while this transaction waits for a row lock. Any
    # changes above roll back together if it is no longer live at this point.
    collab.live_principal(c)
