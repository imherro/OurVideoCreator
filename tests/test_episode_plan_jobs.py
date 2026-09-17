import copy
import uuid
import pytest
from backend import store as s
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,create
from tests.test_p5_owned_content import create_chapter,base
from tests.test_p5_relation_candidates import extraction,candidate_path,expected,complete_without_network,approved_plan,EVENT
from tests.platform_model_helpers import publish_test_model


@pytest.mark.parametrize('change',['none','source','previous','video'])
def test_single_plan_candidate_is_explicit_and_dependency_checked(team,monkeypatch,change):
    root=base(team);client=team['admin'];chapter=create_chapter(team)
    model='ep-plan-'+uuid.uuid4().hex;publish_test_model(client,model)
    extracted=extraction(team,[chapter],model).json()['jobs'][0]
    complete_without_network(monkeypatch,extracted,{'events':[EVENT]})
    adopted=team['a'].post(candidate_path(team,extracted)+'/adopt',json=expected(chapter))
    assert adopted.status_code==200,adopted.text
    bundle=approved_plan(team,adopted.json()['target'])
    bundle['adaptationPlan']['format']['episodeCount']=2
    second=copy.deepcopy(bundle['episodePlans'][0]);second['episodeNo']=2
    bundle['episodePlans'].append(second)
    response=client.put(root+'/adaptation',json={key:bundle[key] for key in ('revision','adaptationPlan','episodePlans','monetizationPlan')})
    assert response.status_code==200,response.text
    episode=client.post(root+'/episodes',json={'title':'第二集'}).json()
    before=client.get(root+'/adaptation').json()
    body={'project_id':team['pid'],'model_id':model,'submission_id':'one-'+uuid.uuid4().hex}
    path=root+'/adaptation/episodes/2/generate'
    assert team['a'].post(path,json=body).status_code==403
    response=client.post(path,json=body);assert response.status_code==200,response.text
    job=response.json()
    assert job['input']['schema_version']=='episode-plan/v1'
    assert client.post(path,json=body).json()['id']==job['id']
    assert client.post(path,json={**body,'submission_id':'duplicate-'+uuid.uuid4().hex}).status_code==409
    generic={'node_id':job['node_id'],'kind':'text','submission_id':'generic-'+uuid.uuid4().hex,
        'input':{**job['input'],'prompt':'FORGED PROMPT','system_prompt':'FORGED SYSTEM','response_schema':{}}}
    assert client.post('/api/projects/'+team['pid']+'/jobs',json=generic).status_code==409
    if change=='none':
        with s.db() as c:
            c.execute('SELECT project_id FROM episode_scripts WHERE project_id=%s FOR UPDATE',(team['pid'],))
            busy=client.post(path,json={**body,'submission_id':'locked-'+uuid.uuid4().hex})
            assert busy.status_code==409 and '正在保存' in busy.text,busy.text
    generated={key:value for key,value in before['episodePlans'][1].items() if key!='status'}
    generated.update(logline='New single episode',emotionalBeat='Tension')
    result=complete_without_network(monkeypatch,job,generated)
    assert result['adaptation']['episodePlan']['status']=='draft'
    assert client.get(root+'/adaptation').json()==before
    if change=='none':
        generic_result=client.post('/api/projects/'+team['pid']+'/jobs',json=generic)
        assert generic_result.status_code==200,generic_result.text
        normalized=generic_result.json()
        assert 'FORGED' not in normalized['input']['prompt']
        assert 'FORGED' not in normalized['input']['system_prompt']
        assert normalized['input']['response_schema']['required']
        assert client.post('/api/jobs/'+normalized['id']+'/cancel').status_code==200
    if change=='source':
        with s.db() as c:c.execute('UPDATE source_events SET summary=%s WHERE chapter_id=%s',('changed source',chapter['id']))
    elif change=='previous':
        with s.db() as c:c.execute('UPDATE episode_scripts SET body=%s,revision=revision+1 WHERE project_id=%s',('previous episode new ending',team['pid']))
    elif change=='video':
        node=create({'pid':episode['id'],'a':client},kind='node',node={'id':'accepted-video','type':'video','data':{'kind':'video'}})
        with s.db() as c:
            content=node['content'];content['node']['data']['assetId']='isolated-accepted-video'
            c.execute('UPDATE collaboration_objects SET content=%s WHERE id=%s',(s.dumps(content),node['id']))
    latest=client.get(root+'/adaptation').json()
    adopted=client.post(candidate_path(team,job)+'/adopt',json=expected(latest,accept_stale=True))
    if change!='none':
        assert adopted.status_code==409,adopted.text
        assert client.get(root+'/adaptation').json()==latest
    else:
        assert adopted.status_code==200,adopted.text
        after=adopted.json()['target']
        assert after['episodePlans'][0]==before['episodePlans'][0]
        assert after['adaptationPlan']==before['adaptationPlan']
        assert after['episodePlans'][1]['logline']=='New single episode'
        assert after['episodePlans'][1]['status']=='draft'
