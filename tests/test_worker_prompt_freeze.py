import time

from backend import store as s
from backend.worker import Worker


def _job(compiled):
    s.init()
    pid=s.uid('prompt-project-')
    upstream_id=s.uid('prompt-upstream-')
    job_id=s.uid('prompt-image-')
    now=time.time()
    provider={
        'id':'prompt-maestro','name':'Prompt Maestro','type':'maestro',
        'kind':'image','url':'http://127.0.0.1:7870','local':True,
    }
    input_value={
        'provider':'prompt-maestro','model':'image-model','prompt':'冻结后的最终提示词',
        'upstream_job_ids':[upstream_id],'asset_ids':[],
    }
    if compiled:
        input_value.update(reference_compiler={'version':1},image_reference_sources=[])
    with s.db() as db:
        db.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'Prompt freeze','{}',now,now))
        db.execute(
            'INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,result,created,updated) '
            'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (upstream_id,s.uid(),pid,'storyboard','storyboard','succeeded',s.dumps({'prompt':'story'}),
             s.dumps({'text':'任意上游剧本文本'}),now,now),
        )
        db.execute(
            'INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) '
            'VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (job_id,s.uid(),pid,'image','image','running',s.dumps(input_value),now,now),
        )
        db.execute('INSERT INTO job_private VALUES(%s,%s)',(job_id,s.dumps(provider)))
        return s.unpack(db.execute('SELECT * FROM jobs WHERE id=%s',(job_id,)).fetchone())


def test_film_bible_compiled_prompt_is_the_exact_provider_facing_prompt(monkeypatch):
    worker=Worker();captured={}
    monkeypatch.setattr(worker,'maestro',lambda job,provider:captured.setdefault('prompt',job['input']['prompt']))
    job=_job(True)
    assert worker.execute(job)=='冻结后的最终提示词'
    assert captured['prompt']==job['input']['prompt']
    assert '上游创作内容' not in captured['prompt']


def test_legacy_job_still_appends_upstream_text(monkeypatch):
    worker=Worker();captured={}
    monkeypatch.setattr(worker,'maestro',lambda job,provider:captured.setdefault('prompt',job['input']['prompt']))
    worker.execute(_job(False))
    assert '上游创作内容：\n任意上游剧本文本' in captured['prompt']
