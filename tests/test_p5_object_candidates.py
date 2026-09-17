"""Object candidate boundaries: ordinary editors, real PG and blocked fake HTTP."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import uuid
import pytest

from backend import store as s
from backend.worker import Worker
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,url,version,save,create
from tests.test_p5_canonical_integration import node,graph
from tests.platform_model_helpers import publish_test_model


def submit(team,row,model,actor=None,**changes):
    value={'node_id':row['content']['node']['id'],'kind':'text','submission_id':uuid.uuid4().hex,
           'input':{'model_id':model,'prompt':'saved prompt'}}
    value.update(changes)
    return (actor or team['a']).post('/api/projects/'+team['pid']+'/jobs',json=value)


def candidate(team,job):return '/api/projects/'+team['pid']+'/candidates/'+job['id']


@pytest.mark.parametrize('change',['edit','reassign'])
def test_late_text_http_result_only_candidate_then_explicit_authorized_adoption(team,monkeypatch,change):
    row=node(team,team['a'],'candidate-text')
    value=deepcopy(row['content']);value['node']['data']['prompt']='saved prompt'
    saved=save(team,row,value);assert saved.status_code==200,saved.text
    row=saved.json();entered=threading.Event();release=threading.Event();requests=[]
    class Fake(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))));entered.set()
            if not release.wait(15):self.send_error(504);return
            stream='data: '+json.dumps({'choices':[{'delta':{'content':'candidate text'}}]})+'\n\ndata: [DONE]\n\n'
            payload=stream.encode();self.send_response(200);self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Fake);port=server.server_address[1]
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('OVC_PROVIDER_EGRESS_EXCEPTIONS',json.dumps([{'scheme':'http','host':'127.0.0.1','ip':'127.0.0.1','port':port}]))
    model=uuid.uuid4().hex;publish_test_model(team['admin'],model,url=f'http://127.0.0.1:{port}/v1')
    try:
        response=submit(team,row,model);assert response.status_code==200,response.text
        job=response.json();binding=job['collaboration']
        assert binding['target']=={'kind':'node','id':row['id'],'revision':row['revision'],'assignment_epoch':row['assignment_epoch']}
        assert binding['mode']=='node'
        assert s.job_update(job['id'],status='running')
        with ThreadPoolExecutor(max_workers=1) as pool:
            running=pool.submit(Worker().execute,job)
            try:
                assert entered.wait(10)
                if change=='edit':
                    value=deepcopy(row['content']);value['node']['data'].update(text='human v2',prompt='new prompt')
                    changed=save(team,row,value);actor=team['a']
                else:
                    changed=team['admin'].post(url(team,row,'/assign'),json={**version(row),'assignee_id':team['bid']});actor=team['b']
                assert changed.status_code==200,changed.text
                current=changed.json()
            finally:release.set()
            result=running.result(15)
        assert len(requests)==1 and result['text']=='candidate text'
        assert s.job_update(job['id'],status='succeeded',result=result)
        assert actor.get(url(team,row)).json()==current
        path=candidate(team,job);compared=actor.get(path)
        assert compared.status_code==200,compared.text
        assert compared.json()['can_adopt'] is True
        for other in (team['viewer'],team['admin']):
            assert other.post(path+'/adopt',json={**version(current),'accept_stale':True}).status_code==403
        assert actor.post(path+'/adopt',json=version(row)).status_code==409
        assert actor.post(path+'/adopt',json=version(current)).status_code==409
        adopted=actor.post(path+'/adopt',json={**version(current),'accept_stale':True})
        assert adopted.status_code==200,adopted.text
        latest=adopted.json()['target'];data=latest['content']['node']['data']
        assert data['text']=='candidate text' and data['resultJob']==job['id']
        assert data['stale'] is (change=='edit')
        assert latest['revision']==current['revision']+1 and latest['assignee_id']==current['assignee_id']
        assert actor.post(path+'/adopt',json=version(latest)).status_code==409
    finally:release.set();server.shutdown();server.server_close();thread.join(5)


def test_generation_denies_nonowner_unknown_target_and_conflicting_markers_without_jobs(team):
    row=node(team,team['a'],'owned-target');model=uuid.uuid4().hex;publish_test_model(team['admin'],model)
    path='/api/projects/'+team['pid']+'/jobs';before=team['a'].get(path).json()
    for actor in (team['b'],team['admin'],team['viewer']):
        response=submit(team,row,model,actor);assert response.status_code==403,response.text
    assert submit(team,row,model,node_id='not-a-real-node').status_code==404
    response=submit(team,row,model,input={'model_id':model,'prompt':'x','voice_profile':{},'dialogue':{}})
    assert response.status_code==422,response.text
    assert team['a'].get(path).json()==before


def test_changed_upstream_dependency_blocks_candidate_without_partial_target_write(team):
    upstream=node(team,team['b'],'upstream');target=node(team,team['a'],'downstream')
    structure=graph(team);value=deepcopy(structure['content'])
    value['edges']=[{'id':'link','source':'upstream','target':'downstream'}]
    response=save(team,structure,value);assert response.status_code==200,response.text
    model=uuid.uuid4().hex;publish_test_model(team['admin'],model)
    response=submit(team,target,model);assert response.status_code==200,response.text
    job=response.json();assert upstream['id'] in {r['id'] for r in job['collaboration']['references']}
    s.job_update(job['id'],status='running');s.job_update(job['id'],status='succeeded',result={'text':'candidate'})
    value=deepcopy(upstream['content']);value['node']['data']['text']='changed dependency'
    assert save(team,upstream,value,client=team['b']).status_code==200
    before=team['a'].get(url(team,target)).json()
    response=team['a'].post(candidate(team,job)+'/adopt',json={**version(before),'accept_stale':True})
    assert response.status_code==409,response.text
    assert team['a'].get(url(team,target)).json()==before
    assert 'adopted' not in team['a'].get(candidate(team,job)).json()['job']['collaboration']


def voice_card(team,model,locked=False):
    content={'card':{'id':'hero','name':'Hero','kind':'character','currentVersionId':'hero-v1','parentCardId':None,'status':'active'},
        'versions':{'hero-v1':{'id':'hero-v1','cardId':'hero','version':1,'parentVersionId':None,'status':'draft',
            'spec':{'description':'hero','attributes':[]},'invariants':[],'references':[],'createdAt':1,'provenance':{}}},
        'voice_profile':{'cardId':'hero','version':1,'status':'locked' if locked else 'draft',
            'voiceType':'test-voice','model_id':model,'previewText':'preview words'}}
    response=team['a'].post(url(team),json={'kind':'visual_card','content':content})
    assert response.status_code==201,response.text
    return response.json()


def audio_model(team):
    model=uuid.uuid4().hex
    publish_test_model(team['admin'],model,kind='audio',provider_type='volcengine_speech',
        rules={'voice_type':{'type':'string','enum':['test-voice']}},defaults={'voice_type':'test-voice'})
    return model


def audio_result(job,tmp_path):
    # Register real temporary PCM media via the existing provider result path;
    # no model request, fabricated database asset, or real-provider charge.
    import wave
    from backend.providers.common import register
    path=tmp_path/'candidate.wav'
    with wave.open(str(path),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(8000);stream.writeframes(b'\0\0'*800)
    s.job_update(job['id'],status='running')
    asset=register(job,path)
    assert s.job_update(job['id'],status='succeeded',result={'assets':[asset]})
    return asset


def test_voice_preview_is_candidate_only_and_card_owner_explicitly_adopts(team,tmp_path):
    model=audio_model(team);card=voice_card(team,model)
    body={'node_id':'voice-profile:hero','kind':'audio','submission_id':uuid.uuid4().hex,
        'input':{'model_id':model,'prompt':'preview words','voice_type':'test-voice','voice_profile':{'cardId':'hero','version':1}}}
    response=team['a'].post('/api/projects/'+team['pid']+'/jobs',json=body)
    assert response.status_code==200,response.text
    job=response.json();assert job['collaboration']['target']['id']==card['id']
    assert job['collaboration']['mode']=='voice'
    asset=audio_result(job,tmp_path)
    assert team['a'].get(url(team,card)).json()==card
    response=team['a'].post(candidate(team,job)+'/adopt',json=version(card))
    assert response.status_code==200,response.text
    profile=response.json()['target']['content']['voice_profile']
    assert profile['previewAssetId']==asset['id'] and profile['generationJobId']==job['id']


def test_dialogue_candidate_binds_shot_owner_and_mixed_owner_batch_rolls_back(team,tmp_path):
    model=audio_model(team);card=voice_card(team,model,locked=True)
    dialogue={'id':'line-a','characterCardId':'hero','text':'saved dialogue'}
    a=create(team,dialogues=[dialogue]);b=create(team,team['b'],dialogues=[{**dialogue,'id':'line-b'}])
    def body(row):
        shot=row['content']['shot'];line=shot['dialogues'][0]
        return {'node_id':'dialogue:'+line['id'],'kind':'audio','submission_id':uuid.uuid4().hex,
            'input':{'model_id':model,'prompt':line['text'],'voice_type':'test-voice',
                'dialogue':{**line,'shotUid':shot['uid'],'voiceVersion':1}}}
    path='/api/projects/'+team['pid'];before=team['a'].get(path+'/jobs').json()
    response=team['a'].post(path+'/audio-jobs',json={'jobs':[body(a),body(b)]})
    assert response.status_code==403,response.text
    assert team['a'].get(path+'/jobs').json()==before
    response=team['a'].post(path+'/audio-jobs',json={'jobs':[body(a)]})
    assert response.status_code==200,response.text
    job=response.json()['jobs'][0];assert job['collaboration']['target']['id']==a['id']
    assert card['id'] in {r['id'] for r in job['collaboration']['references']}
    asset=audio_result(job,tmp_path)
    assert team['a'].get(url(team,a)).json()==a
    response=team['a'].post(candidate(team,job)+'/adopt',json=version(a))
    assert response.status_code==200,response.text
    line=response.json()['target']['content']['shot']['dialogues'][0]
    assert line['audioAssetId']==asset['id'] and line['audioVoiceVersion']==1 and line['audioJobId']==job['id']


def test_visual_submission_never_mutates_card_and_explicit_adoption_records_reference(team,tmp_path):
    from PIL import Image
    from backend.providers.common import register
    model=uuid.uuid4().hex;publish_test_model(team['admin'],model,kind='image')
    card=voice_card(team,model);value=deepcopy(card['content'])
    value['voice_profile']=None;value['card']['generation']={'image':{'mode':'override','model_id':model}}
    response=save(team,card,value);assert response.status_code==200,response.text
    card=response.json()
    body={'node_id':'visual-version:hero-v1','kind':'image','submission_id':uuid.uuid4().hex,
        'input':{'model_id':model,'prompt':'hero portrait','asset_category':'character',
            'output_name':'主角 · 主参考图 · V1.png',
            'visual_reference':{'versionId':'hero-v1','targetSource':'override'}}}
    response=team['a'].post('/api/projects/'+team['pid']+'/jobs',json=body)
    assert response.status_code==200,response.text
    job=response.json();assert job['collaboration']['mode']=='visual'
    assert 'project_document' not in job
    assert team['a'].get(url(team,card)).json()==card
    path=tmp_path/'portrait.png';Image.new('RGB',(8,8),'red').save(path)
    s.job_update(job['id'],status='running');asset=register(job,path)
    assert asset['name']=='主角 · 主参考图 · V1.png'
    with s.db() as c:
        stored=c.execute('SELECT name,path FROM assets WHERE id=%s',(asset['id'],)).fetchone()
    assert stored['name']==asset['name'] and stored['path']==asset['id']+'.png'
    s.job_update(job['id'],status='succeeded',result={'assets':[asset]})
    assert team['a'].get(url(team,card)).json()==card
    response=team['a'].post(candidate(team,job)+'/adopt',json=version(card))
    assert response.status_code==200,response.text
    value=response.json()['target']['content']['versions']['hero-v1']
    assert value['status']=='pending_reference'
    assert value['references'][0]['assetId']==asset['id']
    assert value['provenance']['referenceGeneration']['jobId']==job['id']
