import time
import pytest
from PIL import Image
from backend import store as s
from backend import worker
from backend.providers import common

def test_cancel_during_media_probe_never_publishes_asset(monkeypatch,tmp_path):
    s.init();pid=s.uid();jid=s.uid();now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'race','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'n','video','running','{}',now,now))
    source=tmp_path/'result.mp4';source.write_bytes(b'test')
    existing=set(s.ASSETS.iterdir())
    def probe(path):
        s.job_update(jid,status='cancelled')
        return {'duration':1}
    monkeypatch.setattr(common,'probe',probe)
    with pytest.raises(InterruptedError):worker.register({'id':jid,'project_id':pid,'node_id':'n','input':{}},source)
    with s.db() as c:assert c.execute('SELECT count(*) count FROM assets WHERE project_id=%s',(pid,)).fetchone()['count']==0
    assert set(s.ASSETS.iterdir())==existing
    assert source.exists()

def test_generated_assets_record_semantic_category_and_source(tmp_path):
    s.init();pid=s.uid();jid=s.uid();now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'category','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'n','image','running',s.dumps({'asset_category':'prop'}),now,now))
    source=tmp_path/'prop.png';Image.new('RGB',(20,20),'red').save(source)
    result=common.register({'id':jid,'project_id':pid,'node_id':'n','input':{'asset_category':'prop'}},source)
    assert result['category']=='prop' and result['source']=='generated'
    with s.db() as c:
        row=c.execute('SELECT category,source FROM assets WHERE id=%s',(result['id'],)).fetchone()
    assert dict(row)=={'category':'prop','source':'generated'}

def test_generation_fingerprint_is_saved_with_actual_asset_result(tmp_path):
    s.init();pid=s.uid();jid=s.uid();now=time.time()
    fingerprint={'version':1,'algorithm':'sha256','hash':'a'*64,'inputs':{'providerId':'ark','modelId':'seedream'}}
    job_input={'generation_fingerprint':fingerprint}
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'fingerprint','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'shot-image','image','running',s.dumps(job_input),now,now))
    source=tmp_path/'shot.png';Image.new('RGB',(20,20),'blue').save(source)
    result=common.register({'id':jid,'project_id':pid,'node_id':'shot-image','input':job_input},source)
    assert result['generationFingerprint']==fingerprint
    with s.db() as c:
        metadata=s.unpack(c.execute('SELECT metadata FROM assets WHERE id=%s',(result['id'],)).fetchone())['metadata']
    assert metadata['generationFingerprint']==fingerprint
