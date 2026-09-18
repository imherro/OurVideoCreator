"""Relation candidates: real HTTP fake, PostgreSQL, and explicit public adoption."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import threading
import uuid
import pytest

from backend import store as s
from backend.worker import Worker
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits
from tests.test_p5_owned_content import create_chapter,save,assign,base,endpoint
from tests.platform_model_helpers import publish_test_model
from tests.test_p3_r2_interleavings import wait_for_db_waiters

EVENT={'characters':['A'],'summary':'candidate event','importance':'high','emotion':'surprise','continuity':{}}
SCRIPT={'title':'Generated title','synopsis':'Generated summary','body':'Generated body',
        'estimatedDuration':15,'characters':['A'],'scenes':['room'],'props':[]}


def publish_candidate_model(team, model, **kwargs):
    """Publish after fixture creation, then explicitly add to its frozen model pool."""
    result=publish_test_model(team['admin'],model,**kwargs)
    production=team['admin'].get(base(team)).json()
    pool=production['context']['modelPool']
    kind=kwargs.get('kind','text')
    pool[kind]=[*pool[kind],{'model_id':model}]
    response=team['admin'].patch(base(team)+'/context',json={
        'expected_revision':production['revision'],'patch':{'modelPool':pool}})
    assert response.status_code==200,response.text
    return result


def extraction(team,chapters,model,actor=None):
    return (actor or team['a']).post(base(team)+'/source-extractions',json={
        'project_id':team['pid'],'chapter_ids':[row['id'] for row in chapters],
        'model_id':model,'submission_id':'candidate-'+uuid.uuid4().hex})


def candidate_path(team,job):return '/api/projects/'+team['pid']+'/candidates/'+job['id']
def expected(row,**extra):return {'expected_revision':row['revision'],'assignment_epoch':row.get('assignment_epoch',0),**extra}


@pytest.mark.parametrize('change',['edit','reassign'])
def test_late_chapter_http_result_stays_candidate_until_explicit_current_owner_adopts(team,monkeypatch,change):
    chapter=create_chapter(team);entered=threading.Event();release=threading.Event();requests=[]
    class Fake(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            entered.set()
            if not release.wait(15):self.send_error(504);return
            value=json.dumps({'events':[EVENT]})
            stream='data: '+json.dumps({'choices':[{'delta':{'content':value}}]})+'\n\ndata: [DONE]\n\n'
            payload=stream.encode();self.send_response(200);self.send_header('Content-Type','text/event-stream')
            self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
    server=ThreadingHTTPServer(('127.0.0.1',0),Fake);port=server.server_address[1]
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    monkeypatch.setenv('OVC_PROVIDER_EGRESS_EXCEPTIONS',json.dumps([{'scheme':'http','host':'127.0.0.1','ip':'127.0.0.1','port':port}]))
    model='candidate-'+uuid.uuid4().hex
    publish_candidate_model(team,model,url=f'http://127.0.0.1:{port}/v1')
    try:
        submitted=extraction(team,[chapter],model);assert submitted.status_code==200,submitted.text
        job=submitted.json()['jobs'][0]
        assert job['collaboration']['target']=={'kind':'chapter','id':chapter['id'],
            'revision':chapter['revision'],'assignment_epoch':chapter['assignment_epoch']}
        s.job_update(job['id'],status='running')
        with ThreadPoolExecutor(max_workers=1) as pool:
            running=pool.submit(Worker().execute,job)
            try:
                assert entered.wait(10)
                if change=='edit':
                    response=save(team,'chapter',chapter,content='human v2 must survive')
                    assert response.status_code==200,response.text
                    current=response.json();actor=team['a']
                else:
                    current=assign(team,'chapter',chapter,team['bid']);actor=team['b']
                current=actor.get(endpoint(team,'chapter',current)).json()
            finally:release.set()
            result=running.result(15)
        assert len(requests)==1
        assert 'retained text' in requests[0]['messages'][1]['content']
        assert result['events']==[EVENT]
        assert s.job_update(job['id'],status='succeeded',result=result)
        assert actor.get(endpoint(team,'chapter',current)).json()==current
        assert actor.get(base(team)+'/source-events',params={'chapter_id':chapter['id']}).json()==[]
        path=candidate_path(team,job)
        compared=actor.get(path);assert compared.status_code==200,compared.text
        assert compared.json()['current']['revision']==current['revision']
        assert compared.json()['can_adopt'] is True
        for other in (team['viewer'],team['admin']):
            assert other.post(path+'/adopt',json=expected(current,accept_stale=True)).status_code==403
        assert actor.post(path+'/adopt',json=expected(chapter)).status_code==409
        assert actor.post(path+'/adopt',json=expected(current)).status_code==409
        adopted=actor.post(path+'/adopt',json=expected(current,accept_stale=True))
        assert adopted.status_code==200,adopted.text
        latest=adopted.json()['target']
        assert latest['revision']==current['revision']+1 and latest['content']==current['content']
        assert latest['assignee_id']==current['assignee_id']
        events=actor.get(base(team)+'/source-events',params={'chapter_id':chapter['id']}).json()
        assert len(events)==1 and events[0]['summary']==EVENT['summary']
        assert actor.post(path+'/adopt',json=expected(latest,accept_stale=True)).status_code==409
        receipt=actor.get(path).json()['job']['collaboration']['adopted']
        assert receipt['revision']==latest['revision'] and receipt['accepted_stale'] is True
    finally:release.set();server.shutdown();server.server_close();thread.join(5)


def test_source_batch_mixed_owner_creates_no_jobs(team):
    a=create_chapter(team);b=create_chapter(team,team['b'])
    model='candidate-'+uuid.uuid4().hex;publish_candidate_model(team,model)
    before=team['a'].get('/api/projects/'+team['pid']+'/jobs').json()
    response=extraction(team,[a,b],model)
    assert response.status_code==403,response.text
    assert team['a'].get('/api/projects/'+team['pid']+'/jobs').json()==before


def approved_plan(team,chapter):
    from tests.test_adaptation import save_and_approve
    value=team['admin'].get(base(team)+'/adaptation').json()
    value['adaptationPlan'].update(storyCore={'premise':'story','theme':'trust','protagonist':'A','goal':'find','stakes':'life'},
        storyArc={'opening':'open','development':'grow','turningPoint':'turn','climax':'peak','ending':'end'},
        adaptationStrategy={'audience':'all','tone':'warm','changes':'none','constraints':'source'})
    plan=value['episodePlans'][0]
    plan.update(sourceChapterRefs=[chapter['id']],logline='logline',coreConflict='conflict',hook='hook',cliffhanger='cliff')
    return save_and_approve(team['admin'],{'id':team['production']},value)


def complete_without_network(monkeypatch,job,value):
    # Worker computation contract only. The late-result cases above use actual
    # blocked loopback HTTP through frozen P4 binding and egress protection.
    monkeypatch.setattr(Worker,'_chat_text',lambda *args,**kwargs:json.dumps(value))
    s.job_update(job['id'],status='running')
    result=Worker().execute(job)
    assert s.job_update(job['id'],status='succeeded',result=result)
    return result


def test_script_generation_freezes_owner_and_sources_then_adopts_without_auto_write(team,monkeypatch):
    from tests.test_p5_owned_content import content
    chapter=create_chapter(team);approved_plan(team,chapter);script=content(team,'script')
    model='candidate-'+uuid.uuid4().hex;publish_candidate_model(team,model)
    body={'episode_nos':[1],'model_id':model,'submission_id':'script-'+uuid.uuid4().hex}
    assert team['admin'].post(base(team)+'/script-generations',json=body).status_code==403
    response=team['a'].post(base(team)+'/script-generations',json=body)
    assert response.status_code==200,response.text
    job=response.json()['jobs'][0]
    assert job['collaboration']['references']==[{'id':chapter['id'],'revision':chapter['revision'],'assignment_epoch':chapter['assignment_epoch']}]
    result=complete_without_network(monkeypatch,job,SCRIPT)
    assert result['script']['body']==SCRIPT['body']
    assert team['a'].get(endpoint(team,'script',script)).json()['body']==script['body']
    adopted=team['a'].post(candidate_path(team,job)+'/adopt',json=expected(script))
    assert adopted.status_code==200,adopted.text
    latest=adopted.json()['target']
    assert latest['body']==SCRIPT['body'] and latest['status']=='draft'
    assert latest['sourceChapterRefs']==[chapter['id']]
    assert latest['revision']==script['revision']+1 and latest['assignee_id']==team['aid']


@pytest.mark.parametrize('accepted_video',[False,True])
def test_adaptation_worker_keeps_candidate_and_editor_cannot_generate_or_adopt(team,monkeypatch,accepted_video):
    chapter=create_chapter(team)
    model='candidate-'+uuid.uuid4().hex;publish_candidate_model(team,model)
    extracted=extraction(team,[chapter],model).json()['jobs'][0]
    complete_without_network(monkeypatch,extracted,{'events':[EVENT]})
    accepted=team['a'].post(candidate_path(team,extracted)+'/adopt',json=expected(chapter))
    assert accepted.status_code==200,accepted.text
    plan=approved_plan(team,accepted.json()['target'])
    body={'project_id':team['pid'],'model_id':model,'submission_id':'plan-'+uuid.uuid4().hex}
    assert team['a'].post(base(team)+'/adaptation/generate',json=body).status_code==403
    response=team['admin'].post(base(team)+'/adaptation/generate',json=body)
    assert response.status_code==200,response.text
    job=response.json();before=team['admin'].get(base(team)+'/adaptation').json()
    generated={k:plan[k] for k in ('adaptationPlan','episodePlans','monetizationPlan')}
    generated['adaptationPlan']={k:v for k,v in generated['adaptationPlan'].items() if k!='status'}
    generated['adaptationPlan']['storyCore']['premise']='candidate new premise'
    generated['episodePlans']=[{k:v for k,v in p.items() if k!='status'} for p in generated['episodePlans']]
    complete_without_network(monkeypatch,job,generated)
    assert team['admin'].get(base(team)+'/adaptation').json()==before
    path=candidate_path(team,job)
    assert team['a'].post(path+'/adopt',json=expected(before)).status_code==403
    if accepted_video:
        from tests.test_p5_object_transactions import create
        node=create(team,kind='node',node={'id':'finished-video','type':'video','data':{'kind':'video'}})
        with s.db() as c:
            content=node['content'];content['node']['data']['assetId']='isolated-accepted-video'
            c.execute('UPDATE collaboration_objects SET content=%s WHERE id=%s',(s.dumps(content),node['id']))
        response=team['admin'].post(path+'/adopt',json=expected(before,accept_stale=True))
        assert response.status_code==409,response.text
        assert team['admin'].get(base(team)+'/adaptation').json()==before
        assert team['admin'].post(base(team)+'/adaptation/generate',json={**body,'submission_id':'new-'+uuid.uuid4().hex}).status_code==409
        return
    adopted=team['admin'].post(path+'/adopt',json=expected(before))
    assert adopted.status_code==200,adopted.text
    assert adopted.json()['target']['adaptationPlan']['storyCore']['premise']=='candidate new premise'
    assert adopted.json()['target']['adaptationPlan']['status']=='draft'
    assert adopted.json()['target']['revision']==before['revision']+1


def test_two_candidates_same_revision_pg_waiters_only_one_adoption(team,monkeypatch):
    chapter=create_chapter(team)
    model='candidate-'+uuid.uuid4().hex;publish_candidate_model(team,model)
    jobs=[]
    # Generate sequentially without adopting: completed candidates may coexist
    # at one revision, but a second active extraction is now rejected.
    for _ in range(2):
        response=extraction(team,[chapter],model)
        assert response.status_code==200,response.text
        job=response.json()['jobs'][0]
        complete_without_network(monkeypatch,job,{'events':[EVENT]})
        jobs.append(job)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM source_chapters WHERE id=%s FOR UPDATE',(chapter['id'],))
            pending=[pool.submit(team['a'].post,candidate_path(team,job)+'/adopt',json=expected(chapter)) for job in jobs]
            trace=wait_for_db_waiters(2)
            assert all(row['blockers'] for row in trace)
            print('candidate adoption PostgreSQL wait trace',trace)
        responses=[future.result(15) for future in pending]
    assert sorted(response.status_code for response in responses)==[200,409]
    current=team['a'].get(endpoint(team,'chapter',chapter)).json()
    assert current['revision']==chapter['revision']+1
    assert len(team['a'].get(base(team)+'/source-events',params={'chapter_id':chapter['id']}).json())==1
    receipts=[team['a'].get(candidate_path(team,job)).json()['job']['collaboration'].get('adopted') for job in jobs]
    assert sum(bool(receipt) for receipt in receipts)==1


@pytest.mark.parametrize('change',['content','assignment'])
def test_script_candidate_rejects_changed_source_snapshot_without_partial_adoption(team,monkeypatch,change):
    from tests.test_p5_owned_content import content
    chapter=create_chapter(team);approved_plan(team,chapter);script=content(team,'script')
    model='candidate-'+uuid.uuid4().hex;publish_candidate_model(team,model)
    response=team['a'].post(base(team)+'/script-generations',json={
        'episode_nos':[1],'model_id':model,'submission_id':'script-'+uuid.uuid4().hex})
    assert response.status_code==200,response.text
    job=response.json()['jobs'][0];complete_without_network(monkeypatch,job,SCRIPT)
    if change=='content':assert save(team,'chapter',chapter,content='new source').status_code==200
    else:assign(team,'chapter',chapter,team['bid'])
    before=team['a'].get(endpoint(team,'script',script)+'/history').json()
    result=team['a'].post(candidate_path(team,job)+'/adopt',json=expected(script,accept_stale=True))
    assert result.status_code==409,result.text
    assert team['a'].get(endpoint(team,'script',script)+'/history').json()==before
    assert 'adopted' not in team['a'].get(candidate_path(team,job)).json()['job']['collaboration']
