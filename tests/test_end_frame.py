from tests.egress_helpers import mock_egress
import time
import httpx,pytest
from PIL import Image
from backend import store as s
from backend.worker import Worker
from backend.capabilities import maestro_model,validate_media

def test_tail_frame_upload_and_provider_flags(monkeypatch):
    s.init();pid=s.uid();jid=s.uid();now=time.time();ids=[]
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'tail','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'n','video','running','{}',now,now))
        for color in ('red','blue'):
            aid=s.uid();path=s.ASSETS/(aid+'.png');Image.new('RGB',(16,16),color).save(path);ids.append(aid)
            c.execute('INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(aid,pid,color+'.png','image',path.name,'image/png','{}',now))
    captured=[];uploads=[]
    def handle(request):
        if request.url.path=='/api/v1/models':return httpx.Response(200,json={'models':[{'model_type':'h3','supports_end_frame':True,'is_downloaded':True,'director':{'video':{'story':{'compatible':True}},'clip_min_frames':124,'clip_frame_step':17}}]})
        if request.url.path.startswith('/api/v1/defaults'):return httpx.Response(200,json={'image_end':'stale-path'})
        if request.url.path=='/api/v1/upload':
            uploads.append(request.content);return httpx.Response(200,json={'path':f'upload-{len(uploads)}'})
        if request.url.path=='/api/v1/generate':
            import json
            captured.append(json_load:=json.loads(request.content));return httpx.Response(200,json={'job_id':'remote'})
        if request.url.path=='/api/v1/status/remote':return httpx.Response(200,json={'status':'failed','error':'test-stop'})
        raise AssertionError(request.url)
    original=httpx.Client;mock_egress(monkeypatch,handle)
    worker=Worker()
    class NoWait:
        def wait(self,seconds):return False
        def is_set(self):return False
    worker.halt=NoWait()
    job={'id':jid,'submission_id':jid,'project_id':pid,'node_id':'n','kind':'video','input':{'model':'h3','prompt':'转头','frames':124,'asset_ids':[ids[0]],'end_asset_id':ids[1]}}
    with pytest.raises(ValueError,match='test-stop'):worker.maestro(job,{'url':'http://engine','model':job['input']['model'],'local':True})
    assert len(uploads)==2
    assert captured[0]['image_start']=='upload-1'
    assert captured[0]['image_end']=='upload-2'
    assert captured[0]['image_prompt_type']=='SE'
    assert captured[0]['video_prompt_type']==''

def test_unsupported_model_rejects_tail():
    model=maestro_model({'model_type':'video','is_t2v':True})
    with pytest.raises(ValueError,match='不支持尾帧'):validate_media(model,'video',{'end_asset_id':'tail'})


def test_flux_image_reference_is_uploaded_and_sent_in_native_reference_mode(monkeypatch):
    s.init();pid=s.uid();jid=s.uid();now=time.time();aid=s.uid()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'reference','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'image','image','running','{}',now,now))
        path=s.ASSETS/(aid+'.png');Image.new('RGB',(32,16),'orange').save(path)
        c.execute('INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(aid,pid,'character.png','image',path.name,'image/png','{}',now))
    captured=[]
    def handle(request):
        if request.url.path=='/api/v1/models':
            return httpx.Response(200,json={'models':[{'model_type':'flux','is_downloaded':True,'supports_ref_images':True,'director':{'image':{'compatible':True}}}]})
        if request.url.path.startswith('/api/v1/defaults'):return httpx.Response(200,json={})
        if request.url.path=='/api/v1/upload':return httpx.Response(200,json={'path':'uploaded-character'})
        if request.url.path=='/api/v1/generate':
            import json
            captured.append(json.loads(request.content));return httpx.Response(200,json={'job_id':'remote'})
        if request.url.path=='/api/v1/status/remote':return httpx.Response(200,json={'status':'failed','error':'test-stop'})
        raise AssertionError(request.url)
    original=httpx.Client;mock_egress(monkeypatch,handle)
    worker=Worker()
    class NoWait:
        def wait(self,seconds):return False
        def is_set(self):return False
    worker.halt=NoWait()
    job={'id':jid,'submission_id':jid,'project_id':pid,'node_id':'image','kind':'image','input':{'model':'flux','prompt':'角色参考图中的人物站在雨巷','asset_ids':[aid]}}
    with pytest.raises(ValueError,match='test-stop'):worker.maestro(job,{'url':'http://engine','model':job['input']['model'],'local':True})
    assert captured[0]['image_mode']==1
    assert captured[0]['image_refs']==['uploaded-character']
    assert captured[0]['video_prompt_type']=='KI'
    assert 'image_start' not in captured[0]
