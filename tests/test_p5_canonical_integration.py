from copy import deepcopy as copy
import threading
from concurrent.futures import ThreadPoolExecutor

from backend import collaboration, store as s
from tests.test_p5_object_transactions import (team,admin,clients,clear_auth_rate_limits,create,save,url,version)
from tests.test_p3_r2_interleavings import wait_for_db_waiters


def test_real_aggregate_reads_objects_and_legacy_put_is_gone_even_for_owner(team):
    shot=create(team)
    assert save(team,shot).status_code==200
    project=team['a'].get('/api/projects/'+team['pid']).json()
    assert project['object_collaboration'] is True
    assert project['document']['shots'][0]['description']=='v2'
    assert project['permissions']['legacy_document_write'] is False
    stale=copy(project['document']);stale['shots']=[]
    response=team['admin'].put('/api/projects/'+team['pid'],json={'name':project['name'],
        'revision':project['revision'],'production_revision':project['production_revision'],'document':stale})
    assert response.status_code==410
    assert team['a'].get('/api/projects/'+team['pid']).json()['document']['shots'][0]['description']=='v2'
    with s.db() as c:
        c.execute("UPDATE projects SET document=jsonb_set(document,'{shots}','[{\"id\":\"poison-old-copy\"}]'::jsonb) WHERE id=%s",(team['pid'],))
    assert team['a'].get('/api/projects/'+team['pid']).json()['document']['shots'][0]['description']=='v2'


def test_generic_timeline_round_trip_keeps_speed_and_requires_lease_and_assignment(team):
    import io
    from PIL import Image
    image = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(image, format='PNG')
    upload = team['a'].post(f"/api/projects/{team['pid']}/assets",
                           files={'file': ('frame.png', image.getvalue(), 'image/png')})
    assert upload.status_code == 200, upload.text
    asset = upload.json()['id']
    row = create(team, kind='timeline')
    timeline = {'version': 2, 'metadata': {'custom': {'timelineDuration': 20}}, 'tracks': [
        {'id': 'v1', 'type': 'element', 'elements': [{'id': 'clip', 'trackId': 'v1', 'type': 'image',
          's': 0, 'e': 8, 'props': {'srcAssetId': asset, 'time': 0, 'playbackRate': .5, 'volume': .4},
          'metadata': {'assetId': asset}}]}]}
    content = {'timeline': timeline}
    assert save(team, row, content).status_code == 409
    response = team['a'].post(url(team, row, '/lease'), json={'action': 'acquire', 'assignment_epoch': row['assignment_epoch']})
    assert response.status_code == 200, response.text
    lease = response.json()
    auth = {'lease_token': lease['token'], 'lease_epoch': lease['lease_epoch']}
    assert save(team, row, content, client=team['b'], **auth).status_code == 403
    saved = save(team, row, content, **auth)
    assert saved.status_code == 200, saved.text
    reread = team['viewer'].get('/api/projects/' + team['pid']).json()['document']
    assert reread['editor']['timeline'] == timeline
    assert reread['timeline'] == [{'id': 'clip', 'asset_id': asset, 'start': 0, 'duration': 8, 'volume': .4, 'playbackRate': .5}]
    assert team['a'].get(url(team, row)).json()['revision'] == saved.json()['revision']


def test_visual_version_and_voice_immutability_survive_new_card_version(team):
    content={'card':{'id':'card-test','name':'Actor','kind':'character','currentVersionId':'v1','parentCardId':None,'status':'active'},
        'versions':{'v1':{'id':'v1','cardId':'card-test','version':1,'parentVersionId':None,'status':'locked',
            'spec':{'description':'v1 face','attributes':[]},'invariants':[],'references':[],'createdAt':1,'provenance':{}}},
        'voice_profile':{'cardId':'card-test','version':1,'status':'locked','voiceType':'test-voice'}}
    response=team['a'].post(url(team),json={'kind':'visual_card','content':content})
    assert response.status_code==201,response.text
    card=response.json()
    broken=copy(content);broken['versions']['v1']['spec']['description']='overwritten'
    assert save(team,card,broken).status_code==400
    broken=copy(content);broken['voice_profile']['voiceType']='different'
    assert save(team,card,broken).status_code==422
    shot=create(team,assetBindings={'characters':[{'role':'Actor','versionId':'v1'}],'scene':None,'props':[]})
    fork=copy(content);fork['versions']['v2']={**copy(content['versions']['v1']),'id':'v2','version':2,
        'parentVersionId':'v1','status':'draft'};fork['card']['currentVersionId']='v2'
    result=save(team,card,fork)
    assert result.status_code==200,result.text
    doc=team['a'].get('/api/projects/'+team['pid']).json()['document']
    assert doc['filmBible']['visual']['cards']['card-test']['currentVersionId']=='v2'
    assert doc['shots'][0]['assetBindings']['characters'][0]['versionId']=='v1'
    assert doc['filmBible']['visual']['versions']['v1']==content['versions']['v1']


def node(team,actor,nid):
    result=actor.post(url(team),json={'kind':'node','content':{'node':{'id':nid,'type':'media','data':{'kind':'text','text':'draft'}}}})
    assert result.status_code==201,result.text
    return result.json()


def graph(team):
    return next(row for row in team['a'].get(url(team)).json() if row['kind']=='graph')


def test_mixed_structural_import_validates_other_target_before_any_insert(team):
    a=node(team,team['a'],'a-node');b=node(team,team['b'],'b-node');structure=graph(team)
    content=copy(structure['content']);content['edges'].append({'id':'bad-edge','source':'a-node','target':'b-node'})
    content['shotOrder'].append('new-shot')
    before=team['a'].get(url(team)).json()
    response=team['a'].post(url(team)+'/commands',json={
        'creates':[{'kind':'shot','content':{'shot':{'id':'new-shot','uid':'new-shot'},'nodes':[]}}],
        'updates':[{'id':structure['id'],**version(structure),'content':content}]})
    assert response.status_code==403,response.text
    assert team['a'].get(url(team)).json()==before
    duplicate=team['a'].post(url(team),json={'kind':'shot','content':{
        'shot':{'id':'borrowed','uid':'borrowed','imageNode':'b-node'},'nodes':[b['content']['node']]}})
    assert duplicate.status_code==422,duplicate.text


def test_dependency_edit_locks_target_and_rechecks_assignment_after_wait(team,monkeypatch):
    a=node(team,team['a'],'owner-node');b=node(team,team['b'],'reference-node');structure=graph(team)
    content=copy(structure['content']);content['edges'].append({'id':'ref','source':'reference-node','target':'owner-node'})
    entered,release=threading.Event(),threading.Event();record=collaboration.record
    def paused(c,row,action,pid):
        record(c,row,action,pid)
        if action=='assign' and row['id']==a['id']:
            entered.set()
            assert release.wait(10)
    monkeypatch.setattr(collaboration,'record',paused)
    with ThreadPoolExecutor(max_workers=2) as pool:
        takeover=pool.submit(team['admin'].post,url(team,a,'/assign'),json={**version(a),'assignee_id':team['bid']})
        assert entered.wait(5)
        editing=pool.submit(team['a'].patch,url(team,structure),json={**version(structure),'content':content})
        try:
            waits=wait_for_db_waiters(1)
            assert any(row['blockers'] for row in waits)
        finally:
            release.set()
        assert takeover.result(10).status_code==200
        assert editing.result(10).status_code==403
    assert graph(team)['content']['edges']==[]


def test_metadata_whitelist_cannot_smuggle_visual_or_shots(team):
    project=team['admin'].get('/api/projects/'+team['pid']).json()
    endpoint='/api/projects/'+team['pid']+'/metadata'
    assert team['admin'].patch(endpoint,json={'expected_revision':project['revision'],'patch':{'shots':[]}}).status_code==422
    assert team['a'].patch(endpoint,json={'expected_revision':project['revision'],'patch':{'brief':'bypass'}}).status_code==403
    response=team['admin'].patch(endpoint,json={'expected_revision':project['revision'],'patch':{'brief':'kept','name':'New title'}})
    assert response.status_code==200,response.text
    reread=team['a'].get('/api/projects/'+team['pid']).json()
    assert reread['name']=='New title' and reread['document']['brief']=='kept'
    assert team['admin'].patch('/api/productions/'+team['production']+'/context',json={
        'expected_revision':reread['production_revision'],'patch':{'filmBible':{'visual':{'cards':{}}}}}).status_code==422
    for patch in [{'filmBible':{'story':'wrong-type'}},{'filmBible':{'styleVersion':True}},
                  {'filmBible':{'continuity':{'asset_id':'asset-unowned'}}}]:
        assert team['admin'].patch('/api/productions/'+team['production']+'/context',json={
            'expected_revision':reread['production_revision'],'patch':patch}).status_code==422
    assert team['admin'].patch(endpoint,json={'expected_revision':reread['revision'],
        'patch':{'characters':[{'asset_id':'asset-unowned'}]}}).status_code==422
    unchanged=team['a'].get('/api/projects/'+team['pid']).json()
    assert unchanged['revision']==reread['revision'] and unchanged['production_revision']==reread['production_revision']


def test_style_changes_advance_fingerprint_version_without_writing_other_assignees(team):
    shot=create(team,client=team['b'])
    project=team['admin'].get('/api/projects/'+team['pid']).json()
    endpoint='/api/productions/'+team['production']+'/context'
    old_style_version=project['document']['filmBible']['styleVersion']
    result=team['admin'].patch(endpoint,json={'expected_revision':project['production_revision'],'patch':{'style':'new test style'}})
    assert result.status_code==200,result.text
    refreshed=team['a'].get('/api/projects/'+team['pid']).json()
    assert refreshed['document']['filmBible']['styleVersion']==old_style_version+1
    assert team['b'].get(url(team,shot)).json()['revision']==shot['revision']
    assert team['admin'].patch(endpoint,json={'expected_revision':refreshed['production_revision'],
        'patch':{'filmBible':{'styleVersion':old_style_version}}}).status_code==422
