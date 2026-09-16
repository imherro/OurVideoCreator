"""PostgreSQL-backed studio storage. Model workers never own browser state."""
import json
import os
import time
import uuid
from pathlib import Path

from . import database
from .provider_redaction import scrub
from .storage import LocalStorageBackend

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('MVC_DATA_DIR', ROOT / 'data')).resolve()
ASSETS = DATA / 'assets'
STORAGE = LocalStorageBackend(ASSETS)
EVENT_RETENTION = 2000
JOB_EVENT_INTERVAL = 5.0
# Serializing publication until transaction end makes an event id a safe SSE
# cursor: a later id cannot commit before an earlier id.
EVENT_PUBLISH_LOCK_KEY = 0x4F56435F45565431  # "OVC_EVT1"
for folder in (DATA, ASSETS, DATA / 'logs'):
    folder.mkdir(parents=True, exist_ok=True)

def uid(prefix=''):
    return prefix + uuid.uuid4().hex


def asset_path(asset_id, suffix=''):
    return STORAGE.path_for(asset_id, suffix)


def stored_asset_path(stored_name):
    return STORAGE.resolve(stored_name)

def dumps(value):
    return json.dumps(scrub(value), ensure_ascii=False)

def db():
    return database.transaction()

def init():
    return database.check_ready()

def get_setting(key, default=None):
    with db() as c:
        row = c.execute('SELECT value FROM settings WHERE key=%s', (key,)).fetchone()
    return json.loads(row['value']) if row else default

def set_setting(key, value):
    with db() as c:
        c.execute('INSERT INTO settings VALUES(%s,%s) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,dumps(value)))

def _event(connection, project_id, payload):
    connection.execute('SELECT pg_advisory_xact_lock(%s)', (EVENT_PUBLISH_LOCK_KEY,))
    scope = connection.execute('''SELECT p.production_id,pr.workspace_id
        FROM projects p LEFT JOIN productions pr ON pr.id=p.production_id WHERE p.id=%s''',(project_id,)).fetchone() if project_id else None
    inserted = connection.execute(
        '''INSERT INTO events(project_id,payload,created,workspace_id,production_id)
           VALUES(%s,%s,%s,%s,%s) RETURNING id''',
        (project_id,dumps(payload),time.time(),
         scope['workspace_id'] if scope else None,scope['production_id'] if scope else None),
    ).fetchone()['id']
    connection.execute('''DELETE FROM events WHERE id < COALESCE((
        SELECT MIN(id) FROM (SELECT id FROM events ORDER BY id DESC LIMIT %s) retained
    ),0)''', (EVENT_RETENTION,))


def event(project_id, payload, *, connection=None):
    if connection is not None:
        _event(connection, project_id, payload)
        return
    with db() as current:
        _event(current, project_id, payload)

def _notify_job(connection, project_id, job_id, *, force=False):
    if not force:
        recent = connection.execute("""SELECT 1 FROM events
            WHERE project_id=%s AND payload::jsonb->>'type'='job'
            AND payload::jsonb->>'id'=%s AND created>%s LIMIT 1""",
            (project_id, job_id, time.time() - JOB_EVENT_INTERVAL),
        ).fetchone()
        if recent:
            return False
    _event(connection, project_id, {'type':'job','id':job_id})
    return True

def unpack(row):
    if row is None:
        return None
    data = dict(row)
    for key in ('document','input','result','metadata','payload','telemetry','collaboration'):
        if key in data and data[key] is not None:
            data[key] = json.loads(data[key])
    return data

def job_update(job_id, **fields):
    fields = scrub(fields)
    allowed = {'status','result','provider_job_id','error','phase','progress','telemetry'}
    assert fields.keys() <= allowed
    if 'result' in fields:
        fields['result'] = dumps(fields['result'])
    if 'telemetry' in fields:fields['telemetry']=dumps(fields['telemetry'])
    if fields.get('status') in ('succeeded','failed','cancelled'):fields['finished']=time.time()
    fields['updated'] = time.time()
    with db() as c:
        # Cancellation wins over late provider completions.
        current = c.execute('SELECT * FROM jobs WHERE id=%s FOR UPDATE',(job_id,)).fetchone()
        if not current or current['status'] in ('cancelled','succeeded'):
            return False
        c.execute('UPDATE jobs SET '+','.join(f'{k}=%s' for k in fields)+' WHERE id=%s',(*fields.values(),job_id))
        force = bool(fields.keys() & {'status','error','provider_job_id'})
        _notify_job(c, current['project_id'], job_id, force=force)
    return True

def attach_provider_job_id(job_id, provider_job_id):
    """Persist a paid upstream handle even if cancellation raced its response."""
    if scrub(provider_job_id) != provider_job_id:
        raise ValueError("供应商返回了不安全的任务编号，已阻止持久化，请人工核对远端状态")
    with db() as c:
        current=c.execute('SELECT project_id,status,provider_job_id FROM jobs WHERE id=%s FOR UPDATE',(job_id,)).fetchone()
        if not current:raise ValueError('任务不存在，无法保存供应商任务编号')
        existing=current['provider_job_id']
        if existing and existing!=provider_job_id:raise ValueError('供应商任务编号冲突，请人工核对')
        if not existing:
            c.execute('UPDATE jobs SET provider_job_id=%s,updated=%s WHERE id=%s',(provider_job_id,time.time(),job_id))
        _event(c,current['project_id'],{'type':'job','id':job_id})
    return current['status']

def cancelled_phase(job_id, phase):
    phase = scrub(phase)
    with db() as c:
        current=c.execute("SELECT project_id FROM jobs WHERE id=%s AND status='cancelled'",(job_id,)).fetchone()
        if not current:return False
        c.execute('UPDATE jobs SET phase=%s,updated=%s WHERE id=%s',(phase,time.time(),job_id))
        _event(c,current['project_id'],{'type':'job','id':job_id})
    return True
