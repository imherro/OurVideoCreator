"""Read-only, secret-free projection from the explicit P4 browser fixture."""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from sqlalchemy.engine import make_url

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.p4_browser_harness import CANARY
from tests.postgres_test_db import _assert_safe_target


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--manifest',type=Path,required=True)
    args=parser.parse_args()
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'))
    name=manifest['database_name']; _assert_safe_target(name)
    folder=args.manifest.resolve().parent
    if not folder.name.startswith('ovc-p4-browser-'):
        raise ValueError('Only an explicit P4 browser fixture is accepted')
    url=make_url(os.environ['OVC_TEST_ADMIN_URL']).set(database=name,drivername='postgresql')
    with psycopg.connect(url.render_as_string(hide_password=False),row_factory=dict_row) as c:
        scans=[]
        for item in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall():
            table=item['tablename']
            rows=c.execute(sql.SQL('SELECT * FROM {}').format(sql.Identifier(table))).fetchall()
            scans.append({'table':table,'rows':len(rows),'canary_hits':sum(CANARY in str(row) for row in rows)})
        jobs=c.execute('''SELECT j.id,j.kind,j.status,j.provider_job_id,j.created,j.finished,j.actor_user_id,
            v.model_id,p.model_version_id,p.config_version_id,p.credential_version_id,p.parameters
            FROM jobs j LEFT JOIN job_private p ON p.job_id=j.id
            LEFT JOIN model_versions v ON v.id=p.model_version_id WHERE j.project_id=%s ORDER BY j.created''',
            (manifest['project_id'],)).fetchall()
        audit=c.execute('''SELECT id,action,target_type,target_id,actor_user_id,created,payload
            FROM audit_events WHERE action LIKE 'model%%' OR action='platform_model.save' OR action='job.submit'
            ORDER BY created,id''').fetchall()
        ordinary=c.execute('''SELECT u.id,u.platform_role,wm.role workspace_role,pm.role production_role
            FROM users u JOIN workspace_members wm ON wm.user_id=u.id
            JOIN production_members pm ON pm.user_id=u.id WHERE pm.production_id=%s AND u.platform_role='user' ''',
            (manifest['production_id'],)).fetchall()
        encryption=c.execute('''SELECT id,provider_id,key_id,state,length(ciphertext) ciphertext_length
            FROM provider_credential_versions ORDER BY created''').fetchall()
        version=c.execute('SHOW server_version').fetchone()
    files=[]
    for file in folder.glob('*.log'):
        files.append({'file':file.name,'canary_hit':CANARY.encode() in file.read_bytes(),'bytes':file.stat().st_size})
    payload={'utc':datetime.now(timezone.utc).isoformat(),'projection':'No credentials, auth headers, cookies, password hashes, DSN or ciphertext values',
        'database_name':name,'postgres_version':version,'project_id':manifest['project_id'],
        'processes':manifest['pids'],'web_url':manifest['web_url'], 'ordinary':ordinary,
        'jobs':jobs,'audit':audit,'credentials_metadata':encryption,'table_scan':scans,'log_scan':files,
        'fake_counts':json.loads((folder/'counts.json').read_text()),
        'fake_calls':[json.loads(line) for line in (folder/'fake-calls.jsonl').read_text().splitlines()]}
    assert CANARY not in str(payload)
    print(json.dumps(payload,ensure_ascii=False,indent=2,default=str))
    return int(any(row['canary_hits'] for row in scans) or any(item['canary_hit'] for item in files))


if __name__=='__main__': raise SystemExit(main())
