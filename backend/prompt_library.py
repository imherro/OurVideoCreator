"""Platform-owned prompt library with relational append-only revisions."""
import json
import time

from fastapi import HTTPException

from . import identity, store as s


def read(connection=None):
    if connection is None:
        with s.db() as c:
            return read(c)
    state = connection.execute('SELECT revision FROM prompt_library_state WHERE singleton=1').fetchone()
    templates = []
    for row in connection.execute('SELECT id,version FROM prompt_templates ORDER BY id').fetchall():
        versions = connection.execute('''SELECT snapshot FROM prompt_template_revisions
            WHERE template_id=%s ORDER BY version DESC LIMIT 21''', (row['id'],)).fetchall()
        if versions:
            current, *history = [json.loads(item['snapshot']) for item in versions]
            templates.append({**current, 'history': history})
    templates.sort(key=lambda item: (-item['updated'], item['id']))
    return {'revision': state['revision'] if state else 0, 'templates': templates}


def save(template_id, body):
    actor = identity.current()
    if not actor.is_admin:
        raise HTTPException(403, '需要平台管理员权限')
    if len(template_id) > 100 or body.kind not in ('text', 'storyboard', 'image', 'video'):
        raise ValueError('模板类型或编号无效')
    with s.db() as c:
        c.execute('INSERT INTO prompt_library_state(singleton,revision) VALUES(1,0) ON CONFLICT DO NOTHING')
        state = c.execute('SELECT revision FROM prompt_library_state WHERE singleton=1 FOR UPDATE').fetchone()
        if state['revision'] != body.revision:
            raise HTTPException(409, '模板库已在另一页面更新，请刷新后保存；当前草稿仍保留')
        old = c.execute('SELECT version FROM prompt_templates WHERE id=%s', (template_id,)).fetchone()
        version = old['version'] + 1 if old else 1
        if old is None and c.execute('SELECT count(*) n FROM prompt_templates').fetchone()['n'] >= 500:
            raise ValueError('模板库最多保存 500 个模板')
        now = time.time()
        snapshot = {'id': template_id, 'name': body.name, 'kind': body.kind, 'content': body.content,
                    'deleted': body.deleted, 'version': version, 'updated': now}
        c.execute('''INSERT INTO prompt_templates(id,version) VALUES(%s,%s)
            ON CONFLICT(id) DO UPDATE SET version=excluded.version''', (template_id, version))
        c.execute('''INSERT INTO prompt_template_revisions(template_id,version,snapshot,created,created_by)
            VALUES(%s,%s,%s,%s,%s)''', (template_id, version, s.dumps(snapshot), now, actor.user_id))
        c.execute('UPDATE prompt_library_state SET revision=revision+1 WHERE singleton=1')
        identity.audit(c, 'prompt_template.save', 'prompt_template', template_id,
                       payload={'version': version, 'deleted': body.deleted})
        return read(c)
