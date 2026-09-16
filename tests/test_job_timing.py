import time
from backend import store as s

def test_telemetry_and_terminal_time_persist_and_late_events_do_not_overwrite():
    s.init();pid=s.uid();jid=s.uid();now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'Timing','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'n','video','running','{}',now,now))
    s.job_update(jid,telemetry={'step':4,'total_steps':20,'generation_eta_seconds':600})
    s.job_update(jid,status='succeeded',result={'assets':[]})
    with s.db() as c:job=s.unpack(c.execute('SELECT * FROM jobs WHERE id=%s',(jid,)).fetchone())
    assert job['finished']>=now
    assert job['telemetry']['step']==4
    assert not s.job_update(jid,telemetry={'step':3})
    s.init()  # Existing databases remain readable after repeated migration.
    with s.db() as c:assert s.unpack(c.execute('SELECT * FROM jobs WHERE id=%s',(jid,)).fetchone())['finished']==job['finished']
