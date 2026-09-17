import copy
from tests.test_adaptation import adaptation_client, setup_production, save_and_approve, owned_revision


def save_bundle(client,root,value):
    return client.put(root+'/adaptation',json={key:value[key] for key in
        ('revision','adaptationPlan','episodePlans','monetizationPlan')})


def approved_script(client,root,number,chapter):
    path=root+f'/episode-scripts/{number}'
    row=client.get(path).json()
    response=client.put(path,json={**owned_revision(row),'title':f'EP{number}','synopsis':'正文概要',
        'body':'室内。阿青读信。','estimatedDuration':60,'sourceChapterRefs':[chapter['id']],
        'storyGoal':'查明真相','paywallBeat':{},'characters':['阿青'],'scenes':['旧屋'],'props':['密信']})
    assert response.status_code==200,response.text
    review=client.post(path+'/review',json=owned_revision(response.json()))
    assert review.status_code==200,review.text
    approved=client.post(path+'/approve',json=owned_revision(review.json()))
    assert approved.status_code==200,approved.text
    return approved.json()


def test_append_and_edit_only_stale_affected_episode(adaptation_client):
    client=adaptation_client
    production,_,chapter,bundle=setup_production(client,count=2)
    root='/api/productions/'+production['id']
    bundle=save_and_approve(client,production,bundle)
    first=approved_script(client,root,1,chapter)
    second=approved_script(client,root,2,chapter)
    bundle=client.get(root+'/adaptation').json()
    bundle['adaptationPlan']['format']['episodeCount']=3
    new=copy.deepcopy(bundle['episodePlans'][-1]);new.update(episodeNo=3,status='approved')
    bundle['episodePlans'].append(new)
    result=save_bundle(client,root,bundle)
    assert result.status_code==200,result.text
    saved=result.json()
    assert saved['adaptationPlan']['status']=='approved'
    assert [p['status'] for p in saved['episodePlans']]==['approved','approved','draft']
    assert client.get(root+'/episode-scripts/1').json()==first
    assert client.get(root+'/episode-scripts/2').json()==second
    saved['episodePlans'][1]['logline']='只修改第二集'
    result=save_bundle(client,root,saved)
    assert result.status_code==200,result.text
    assert result.json()['adaptationPlan']['status']=='approved'
    assert client.get(root+'/episode-scripts/1').json()==first
    assert client.get(root+'/episode-scripts/2').json()['status']=='stale'
    global_change=result.json()
    global_change['adaptationPlan']['storyCore']['premise']='新的全局前提'
    result=save_bundle(client,root,global_change)
    assert result.status_code==200,result.text
    assert result.json()['adaptationPlan']['status']=='draft'
    assert client.get(root+'/episode-scripts/1').json()['status']=='stale'


def test_scope_ignores_status_forgery_but_tracks_shared_changes(adaptation_client):
    from backend.adaptation import prepare_manual_adaptation
    client=adaptation_client
    production,_,_,bundle=setup_production(client,count=2)
    approved=save_and_approve(client,production,bundle)
    current={key:approved[key] for key in ('adaptationPlan','episodePlans','monetizationPlan')}
    submitted=copy.deepcopy(current)
    submitted['adaptationPlan']['status']='draft'
    submitted['episodePlans'][0]['status']='draft'
    result,changed,shared,episodes=prepare_manual_adaptation(current,submitted)
    assert not changed and not shared and not episodes
    assert result['adaptationPlan']['status']=='approved'
    assert result['episodePlans'][0]['status']=='approved'
    for key,value in [('ratio','16:9'),('targetDuration',90),('platform','另一平台')]:
        submitted=copy.deepcopy(current);submitted['adaptationPlan']['format'][key]=value
        result,changed,shared,episodes=prepare_manual_adaptation(current,submitted)
        assert changed and shared and result['adaptationPlan']['status']=='draft'
    expanded=copy.deepcopy(current);expanded['adaptationPlan']['format']['episodeCount']=3
    extra=copy.deepcopy(expanded['episodePlans'][-1]);extra['episodeNo']=3
    expanded['episodePlans'].append(extra)
    _,changed,shared,episodes=prepare_manual_adaptation(expanded,current)
    assert changed and shared and episodes=={3}


def test_manual_plans_preserve_episode_with_accepted_canonical_video(adaptation_client):
    from tests.test_p5_object_transactions import create
    from backend import store as s
    client=adaptation_client
    production,episode,_,bundle=setup_production(client,count=2)
    current=save_and_approve(client,production,bundle)
    node=create({'pid':episode['id'],'a':client},kind='node',node={'id':'finished-video','type':'video','data':{'kind':'video'}})
    with s.db() as c:
        content=node['content'];content['node']['data']['assetId']='isolated-accepted-video'
        c.execute('UPDATE collaboration_objects SET content=%s WHERE id=%s',(s.dumps(content),node['id']))
    root='/api/productions/'+production['id']
    current=client.get(root+'/adaptation').json()
    for global_edit in (False,True):
        patch=copy.deepcopy(current)
        if global_edit:patch['adaptationPlan']['storyCore']['premise']='changed'
        else:patch['episodePlans'][0]['logline']='changed'
        response=save_bundle(client,root,patch)
        assert response.status_code==409,response.text
        assert client.get(root+'/adaptation').json()==current
    patch=copy.deepcopy(current);patch['episodePlans'][1]['logline']='safe sibling'
    assert save_bundle(client,root,patch).status_code==200
    current=client.get(root+'/adaptation').json()
    assert client.post(root+'/adaptation/review',json={'revision':current['revision']}).status_code==409
    with s.db() as c:
        c.execute('SELECT id FROM projects WHERE id=%s FOR UPDATE',(episode['id'],))
        result=save_bundle(client,root,current)
        assert result.status_code==409,result.text
    assert client.get(root+'/adaptation').json()==current
