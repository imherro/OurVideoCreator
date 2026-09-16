"""Read-only, explicitly scoped P5 browser DB/log evidence projection.

Usage: python scripts/collect_p5_browser_evidence.py MANIFEST_JSON OUTPUT_JSON
No credentials, provider bindings, cookies, phone numbers or asset bytes read.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

import psycopg
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url


def main():
    manifest_path, output = map(Path, sys.argv[1:3])
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    database = manifest['database_name']
    if not re.fullmatch(r'ovc_test_[a-z0-9_]{8,80}', database):
        raise SystemExit('Only explicitly named isolated test databases may be read')
    folder = manifest_path.resolve().parent
    if Path(manifest['directory']).resolve() != folder:
        raise SystemExit('Manifest directory does not match its actual location')
    configured = make_url(os.environ['OVC_TEST_ADMIN_URL'])
    dsn = configured.set(database=database, drivername='postgresql').render_as_string(hide_password=False)
    pid, production = manifest['project_id'], manifest['production_id']
    queries = {
        'objects': ('''SELECT id,kind,object_key,project_id,production_id,assignee_id,
            revision,assignment_epoch,status,content,deleted,lease_epoch,lease_expires
            FROM collaboration_objects WHERE production_id=%s ORDER BY kind,id''', (production,)),
        'history': ('''SELECT h.* FROM collaboration_history h JOIN collaboration_objects o ON o.id=h.object_id
            WHERE o.production_id=%s ORDER BY h.object_id,h.revision''', (production,)),
        'jobs': ('''SELECT id,project_id,node_id,kind,status,collaboration,result,created,updated
            FROM jobs WHERE project_id=%s ORDER BY created,id''', (pid,)),
        'assets': ('''SELECT id,project_id,name,kind,mime,metadata,created FROM assets
            WHERE project_id=%s ORDER BY created,id''', (pid,)),
        'audit': ('''SELECT id,action,target_type,target_id,actor_user_id,payload,created
            FROM audit_events WHERE production_id=%s ORDER BY created,id''', (production,)),
        'events': ('''SELECT id,project_id,payload,created FROM events WHERE project_id=%s ORDER BY id''', (pid,)),
    }
    result = {'utc': datetime.now(timezone.utc).isoformat(), 'business_sha': manifest.get('business_sha'),
              'project_id': pid, 'production_id': production, 'database_name': database,
              'scope': 'Exact synthetic project/production; explicit public object/job/history/audit columns only',
              'not_read': ['credentials', 'provider binding rows', 'sessions', 'phones', 'asset bytes',
                           'unrelated projects', 'browser cookies', 'SSE response bodies'], 'queries': {}}
    with psycopg.connect(dsn, row_factory=dict_row) as connection:
        connection.execute('SET TRANSACTION READ ONLY')
        result['postgres'] = connection.execute('SHOW server_version').fetchone()
        result['migration'] = connection.execute('SELECT version_num FROM alembic_version').fetchall()
        for name, (statement, parameters) in queries.items():
            result['queries'][name] = {'sql': statement, 'parameters': parameters,
                                      'rows': connection.execute(statement, parameters).fetchall()}
    result['fake_requests'] = [json.loads(path.read_text(encoding='utf-8'))
                               for path in sorted(folder.glob('fake-received-*.json'))]
    result['access_log_projection'] = {path.name: [line for line in path.read_text(encoding='utf-8').splitlines()
        if pid in line or production in line] for path in sorted(folder.glob('web-*.stdout.log'))}
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')
    print(json.dumps({'output': str(output), 'rows': {name: len(value['rows'])
        for name, value in result['queries'].items()}, 'fake_requests': len(result['fake_requests'])}))


if __name__ == '__main__':
    main()
