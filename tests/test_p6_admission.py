"""P6 admission checks through authenticated HTTP and real PostgreSQL."""
import uuid
import pytest
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from backend import store as s

from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits
from tests.test_p5_canonical_integration import node
from tests.test_p5_object_candidates import submit
from tests.platform_model_helpers import publish_test_model


def test_same_key_is_independent_for_two_actors_in_same_team(team):
    first_node=node(team,team['a'],'p6-a')
    second_node=node(team,team['b'],'p6-b')
    model=uuid.uuid4().hex
    publish_test_model(team['admin'],model)
    key=uuid.uuid4().hex
    first=submit(team,first_node,model,submission_id=key)
    second=submit(team,second_node,model,team['b'],submission_id=key)
    assert first.status_code==200,first.text
    assert second.status_code==200,second.text
    assert first.json()['id']!=second.json()['id']
    again=submit(team,second_node,model,team['b'],submission_id=key)
    assert again.status_code==200 and again.json()['id']==second.json()['id']


def test_idempotent_replay_rechecks_current_object_owner(team):
    from tests.test_p5_object_transactions import url,version
    row=node(team,team['a'],'p6-replay-owner')
    model=uuid.uuid4().hex
    publish_test_model(team['admin'],model)
    key=uuid.uuid4().hex
    first=submit(team,row,model,submission_id=key)
    assert first.status_code==200,first.text
    assigned=team['admin'].post(url(team,row,'/assign'),json={**version(row),'assignee_id':team['bid']})
    assert assigned.status_code==200,assigned.text
    replay=submit(team,row,model,submission_id=key)
    assert replay.status_code in (403,409),replay.text


def test_concurrent_same_key_same_input_creates_one_job(team):
    row=node(team,team['a'],'p6-concurrent')
    model=uuid.uuid4().hex;publish_test_model(team['admin'],model)
    key=uuid.uuid4().hex;barrier=threading.Barrier(2)
    def contender():
        barrier.wait(timeout=10)
        return submit(team,row,model,submission_id=key)
    with ThreadPoolExecutor(max_workers=2) as pool:
        from backend.job_admission import ADMISSION_LOCK
        from tests.test_p3_r2_interleavings import wait_for_db_waiters
        with s.db() as gate:
            gate.execute('SELECT pg_advisory_xact_lock(%s)',(ADMISSION_LOCK,))
            futures=[pool.submit(contender) for _ in range(2)]
            waits=wait_for_db_waiters(2)
            assert all(item['blockers'] for item in waits)
            print('SINGLE admission database wait trace:',waits)
        results=[future.result(20) for future in futures]
    assert [r.status_code for r in results]==[200,200],[r.text for r in results]
    assert results[0].json()['id']==results[1].json()['id']
    with s.db() as c:
        assert c.execute('SELECT COUNT(*) n FROM jobs WHERE submission_id=%s',(key,)).fetchone()['n']==1
    conflict=submit(team,row,model,submission_id=key,input={'model_id':model,'prompt':'changed'})
    assert conflict.status_code==409,conflict.text


def test_parameter_spellings_and_frozen_defaults_are_canonical(team):
    row=node(team,team['a'],'p6-canonical')
    model=uuid.uuid4().hex
    publish_test_model(team['admin'],model,rules={'temperature':{'type':'number','min':0,'max':1}},
                       defaults={'temperature':0.5})
    key=uuid.uuid4().hex
    first=submit(team,row,model,submission_id=key)
    assert first.status_code==200,first.text
    for params in ({'temperature':0.5},{'parameters':{'temperature':0.5}}):
        replay=submit(team,row,model,submission_id=key,input={'model_id':model,'prompt':'saved prompt',**params})
        assert replay.status_code==200,replay.text
        assert replay.json()['id']==first.json()['id']


def test_canvas_and_single_submit_have_separate_namespaces(team):
    from tests.test_p5_object_transactions import save
    row=node(team,team['a'],'p6-entrypoint')
    model=uuid.uuid4().hex;publish_test_model(team['admin'],model)
    content=deepcopy(row['content'])
    content['node']['data'].update(prompt='saved prompt',model_id=model)
    saved=save(team,row,content);assert saved.status_code==200,saved.text
    row=saved.json();group=uuid.uuid4().hex
    first=submit(team,row,model,submission_id=group+':p6-entrypoint')
    assert first.status_code==200,first.text
    batch=team['a'].post('/api/projects/'+team['pid']+'/run',json={
        'submission_id':group,'node_ids':['p6-entrypoint'],'exact':True})
    assert batch.status_code==200,batch.text
    assert batch.json()['count']==1
    assert batch.json()['job_ids']!=[first.json()['id']]
    replay=team['a'].post('/api/projects/'+team['pid']+'/run',json={
        'submission_id':group,'node_ids':['p6-entrypoint'],'exact':True})
    assert replay.status_code==200 and replay.json()['job_ids']==batch.json()['job_ids'],replay.text
    other=node(team,team['a'],'p6-added-member')
    content=deepcopy(other['content']);content['node']['data'].update(prompt='other',model_id=model)
    assert save(team,other,content).status_code==200
    changed=team['a'].post('/api/projects/'+team['pid']+'/run',json={
        'submission_id':group,'node_ids':['p6-entrypoint','p6-added-member'],'exact':True})
    assert changed.status_code==409,changed.text


def test_audio_batch_replay_and_invalid_member_roll_back(team):
    from tests.collaboration_helpers import create_node
    mid=s.uid('single-audio-')
    publish_test_model(team['admin'],mid,kind='audio',provider_type='volcengine_speech',
        rules={'voice_type':{'type':'string','enum':['voice']}},defaults={'voice_type':'voice'})
    for nid in ('audio-a','audio-b'):create_node(team['a'],team['pid'],nid,'audio')
    body={'jobs':[{'node_id':nid,'kind':'audio','submission_id':s.uid('audio-'),
        'input':{'model_id':mid,'prompt':'test','voice_type':'voice'}} for nid in ('audio-a','audio-b')]}
    path='/api/projects/'+team['pid']+'/audio-jobs'
    bad=deepcopy(body);bad['jobs'][1]['input']['voice_type']='invalid'
    assert team['a'].post(path,json=bad).status_code==400
    assert team['a'].get('/api/projects/'+team['pid']+'/jobs').json()==[]
    first=team['a'].post(path,json=body);assert first.status_code==200,first.text
    replay=team['a'].post(path,json=body);assert replay.status_code==200,replay.text
    assert [j['id'] for j in first.json()['jobs']]==[j['id'] for j in replay.json()['jobs']]
    changed=deepcopy(body);changed['jobs'][0]['input']['prompt']='changed'
    assert team['a'].post(path,json=changed).status_code==409
    assert team['viewer'].post(path,json=body).status_code==403


@pytest.mark.parametrize('entrypoint',['source-extractions','script-generations','adaptation/generate'])
def test_relation_entrypoints_replay_and_reject_current_owner_loss(team,entrypoint,monkeypatch):
    from tests.test_p5_owned_content import create_chapter,content,assign,base
    from tests.test_p5_relation_candidates import approved_plan
    chapter=create_chapter(team);mid=s.uid('single-relation-')
    publish_test_model(team['admin'],mid)
    body={'model_id':mid,'submission_id':s.uid('batch-')}
    actor=team['a']
    if entrypoint=='source-extractions':body.update(project_id=team['pid'],chapter_ids=[chapter['id']])
    elif entrypoint=='script-generations':
        approved_plan(team,chapter);script=content(team,'script');body['episode_nos']=[1]
    else:
        body['project_id']=team['pid'];actor=team['admin']
        from tests.test_p5_relation_candidates import extraction,complete_without_network,EVENT,candidate_path,expected
        extracted=extraction(team,[chapter],mid).json()['jobs'][0]
        complete_without_network(monkeypatch,extracted,{'events':[EVENT]})
        adopted=team['a'].post(candidate_path(team,extracted)+'/adopt',json=expected(chapter))
        assert adopted.status_code==200,adopted.text
    path=base(team)+'/'+entrypoint
    barrier=threading.Barrier(2)
    def concurrent_submit():
        barrier.wait(10)
        return actor.post(path,json=body)
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses=[future.result(20) for future in [pool.submit(concurrent_submit) for _ in range(2)]]
    first=responses[0];assert first.status_code==200,first.text
    assert responses[1].status_code==200,responses[1].text
    replay=actor.post(path,json=body);assert replay.status_code==200,replay.text
    def ids(response):
        value=response.json();return [v['id'] for v in value['jobs']] if 'jobs' in value else [value['id']]
    assert ids(first)==ids(replay)
    assert ids(first)==ids(responses[1])
    if entrypoint=='source-extractions':
        second=create_chapter(team)
        assert actor.post(path,json={**body,'chapter_ids':[chapter['id'],second['id']]}).status_code==409
        assign(team,'chapter',chapter,team['bid'])
        assert actor.post(path,json=body).status_code==403
    elif entrypoint=='script-generations':
        assign(team,'script',script,team['bid'])
        assert actor.post(path,json=body).status_code==403
    else:
        assert team['a'].post(path,json=body).status_code==403


def test_same_actor_same_raw_key_different_workspaces_isolated(team):
    from tests.test_p3_identity_acl import add_workspace,create_project
    workspace=add_workspace(team['admin'],team['aid'],'SINGLE other team')
    project=create_project(team['a'],workspace,'SINGLE other project')
    other={**team,'pid':project['id'],'production':project['production_id'],'workspace':workspace}
    first=node(team,team['a'],'same-node');second=node(other,team['a'],'same-node')
    mid=s.uid('model-');publish_test_model(team['admin'],mid);key=s.uid('key-')
    a=submit(team,first,mid,submission_id=key);b=submit(other,second,mid,submission_id=key)
    assert a.status_code==b.status_code==200,(a.text,b.text)
    assert a.json()['id']!=b.json()['id']
    assert submit(other,second,mid,submission_id=key).json()['id']==b.json()['id']


def test_replay_keeps_original_model_and_credential_versions(team):
    row=node(team,team['a'],'single-frozen')
    mid=s.uid('frozen-model-');key=s.uid('key-')
    publish_test_model(team['admin'],mid,rules={'temperature':{'type':'number','min':0,'max':1}},defaults={'temperature':.4})
    first=submit(team,row,mid,submission_id=key);assert first.status_code==200,first.text
    jid=first.json()['id']
    with s.db() as c:before=c.execute('SELECT * FROM job_private WHERE job_id=%s',(jid,)).fetchone()
    publish_test_model(team['admin'],mid,rules={'temperature':{'type':'number','min':0,'max':1}},defaults={'temperature':.8})
    replay=submit(team,row,mid,submission_id=key)
    assert replay.status_code==200 and replay.json()['id']==jid,replay.text
    with s.db() as c:after=c.execute('SELECT * FROM job_private WHERE job_id=%s',(jid,)).fetchone()
    assert after==before
