"""Single-Worker handles and ownership-scoped subprocess/resource cleanup."""
import subprocess
import sys
import time

import pytest
from backend import store as s
from backend.worker import Worker
from tests.platform_model_helpers import admin


@pytest.fixture
def job(admin):
    pid=admin.post('/api/projects',json={'name':'SINGLE resources'}).json()['id']
    jid=s.uid('job-')
    with s.db() as c:
        c.execute('''INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated)
            VALUES(%s,%s,%s,'resource','export','running','{}',%s,%s)''',
            (jid,s.uid('submit-'),pid,time.time(),time.time()))
        return s.unpack(c.execute('SELECT * FROM jobs WHERE id=%s',(jid,)).fetchone())


def test_handle_is_monotonic_even_when_cancel_wins(job):
    jid=job['id']
    s.job_update(jid,provider_job_id='original')
    s.job_update(jid,provider_job_id=None)
    s.job_update(jid,provider_job_id='')
    with pytest.raises(ValueError,match='冲突'):s.job_update(jid,provider_job_id='different')
    s.job_update(jid,control=True,status='cancelled')
    assert not s.job_update(jid,status='succeeded',result={'late':'ignored'},provider_job_id='original')
    with s.db() as c:
        row=s.unpack(c.execute('SELECT * FROM jobs WHERE id=%s',(jid,)).fetchone())
    assert row['status']=='cancelled' and row['provider_job_id']=='original' and not row['result']


def test_handle_arriving_after_cancel_is_retained(job):
    s.job_update(job['id'],control=True,status='cancelled')
    assert not s.job_update(job['id'],provider_job_id='accepted-before-cancel')
    with s.db() as c:
        row=c.execute('SELECT * FROM jobs WHERE id=%s',(job['id'],)).fetchone()
    assert row['provider_job_id']=='accepted-before-cancel' and row['status']=='cancelled'


def test_cancel_command_cannot_write_results(job):
    with pytest.raises(ValueError,match='只能取消'):
        s.job_update(job['id'],control=True,status='cancelled',result={'bad':True})


def test_cancel_reaps_only_own_child_and_preserves_sentinel(job,tmp_path,monkeypatch):
    import backend.worker as module
    real_popen=subprocess.Popen
    sentinel=tmp_path/'other-task.txt';sentinel.write_text('keep',encoding='utf-8')
    other=real_popen([sys.executable,'-c','import time; time.sleep(120)'],
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    children=[]
    def start(*args,**kwargs):
        child=real_popen(*args,**kwargs);children.append(child)
        s.job_update(job['id'],status='cancelled')
        return child
    monkeypatch.setattr(module.subprocess,'Popen',start)
    try:
        with pytest.raises(InterruptedError):
            Worker().run_process(job,[sys.executable,'-c','import time; time.sleep(120)'],tmp_path/'child.log','render')
        assert len(children)==1 and children[0].poll() is not None
        assert other.poll() is None and sentinel.read_text(encoding='utf-8')=='keep'
    finally:
        for child in [*children,other]:
            if child.poll() is None:child.terminate()
            child.wait(timeout=10)


def test_failed_export_cleans_only_its_private_directory(job,tmp_path,monkeypatch):
    from PIL import Image
    from backend.providers.common import register
    picture=tmp_path/'source.png';Image.new('RGB',(16,16),'red').save(picture)
    asset=register(job,picture)
    job['input']={'timeline':[{'asset_id':asset['id'],'duration':.2,'start':0}],'resolution':'128x128'}
    other=s.DATA/(job['id']+'-other');other.mkdir()
    sentinel=other/'sentinel.txt';sentinel.write_text('keep',encoding='utf-8')
    owned=[]
    run_process=Worker.run_process
    def fail(self,current,args,log_path,phase):
        owned.append(log_path.parent)
        # Real FFmpeg child, deliberately invalid option; no provider/network.
        return run_process(self,current,[args[0],'-single-test-invalid-option'],log_path,phase)
    monkeypatch.setattr(Worker,'run_process',fail)
    with pytest.raises(ValueError,match='导出失败'):Worker().export(job)
    assert owned and all(not p.exists() for p in owned)
    assert sentinel.read_text(encoding='utf-8')=='keep'
    assert s.asset_path(asset['id'],'.png').exists()
