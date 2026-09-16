"""Atomic existing canvas/director actions, using real PostgreSQL and public ACLs."""
from copy import deepcopy
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image

from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,url,version
from tests.test_p5_canonical_integration import node,graph
from tests.test_p5_owned_content import content,base,endpoint,save as save_owned
from tests.test_p3_r2_interleavings import wait_for_db_waiters
from backend import store as s


def action(team,name):return '/api/projects/'+team['pid']+'/'+name
def ref(row):return {'id':row['id'],**version(row)}


def promotion(team):
    script=content(team,'script')
    source=node(team,team['a'],'promoted-text')
    return script,source,{'node':ref(source),'graph':ref(graph(team)),
        'script_revision':script['revision'],'script_assignment_epoch':script['assignment_epoch']}


def snapshot(team,script):
    return (team['a'].get(url(team)).json(),
        team['a'].get(endpoint(team,'script',script)+'/history').json())


def test_promote_own_node_replaces_free_source_atomically_preserves_outgoing(team):
    script,source,body=promotion(team)
    downstream=node(team,team['a'],'downstream')
    structure=graph(team);value=deepcopy(structure['content'])
    value['edges']=[{'id':'out','source':'promoted-text','target':'downstream'},
                    {'id':'in','source':'downstream','target':'promoted-text'}]
    value['nodeOrder']=['promoted-text','downstream']
    changed=team['a'].patch(url(team,structure),json={**version(structure),'content':value})
    assert changed.status_code==200,changed.text
    body['graph']=ref(changed.json())
    response=team['a'].post(action(team,'script-promotion'),json=body)
    assert response.status_code==200,response.text
    result=response.json()['script']
    assert result['body']=='draft' and result['revision']==script['revision']+1
    assert result['assignee_id']==team['aid']
    assert team['a'].get(url(team,source)).status_code==404
    assert team['a'].get(url(team,downstream)).json()['revision']==downstream['revision']
    aggregate=team['a'].get('/api/projects/'+team['pid']).json()['document']
    matches=[item for item in aggregate['nodes'] if item['id']=='promoted-text']
    assert len(matches)==1 and matches[0]['data']['canonicalScriptProjection']
    assert matches[0]['data']['text']=='draft'
    assert graph(team)['content']['edges']==[{'id':'out','source':'promoted-text','target':'downstream'}]
    again=team['a'].post(action(team,'script-promotion'),json=body)
    assert again.status_code in (404,409)


@pytest.mark.parametrize('stale',['node','graph','script','epoch'])
def test_promotion_stale_any_member_rolls_back_script_and_objects(team,stale):
    script,source,body=promotion(team)
    if stale in ('node','graph'):body[stale]['expected_revision']+=1
    elif stale=='script':body['script_revision']+=1
    else:body['node']['assignment_epoch']+=1
    before=snapshot(team,script)
    response=team['a'].post(action(team,'script-promotion'),json=body)
    assert response.status_code==409,response.text
    assert snapshot(team,script)==before


def test_promotion_no_manager_bypass_and_old_canvas_put_is_retired(team):
    script,source,body=promotion(team)
    before=snapshot(team,script)
    for actor in (team['b'],team['admin'],team['viewer']):
        assert actor.post(action(team,'script-promotion'),json=body).status_code==403
    assert save_owned(team,'script',script,canvasNodeId=source['content']['node']['id']).status_code==410
    assert snapshot(team,script)==before
    # Having the script is insufficient if the selected free node is someone else's.
    other=node(team,team['b'],'other-text');body['node']=ref(other)
    assert team['a'].post(action(team,'script-promotion'),json=body).status_code==403


def capture_body(team):
    director=next(row for row in team['a'].get(url(team)).json() if row['kind']=='director')
    assigned=team['admin'].post(url(team,director,'/assign'),json={**version(director),'assignee_id':team['aid']})
    assert assigned.status_code==200,assigned.text
    director=assigned.json()
    image=BytesIO();Image.new('RGB',(8,8),'red').save(image,format='PNG')
    asset=team['a'].post(action(team,'assets'),files={'file':('capture.png',image.getvalue(),'image/png')})
    assert asset.status_code==200,asset.text
    return {'director':ref(director),'graph':ref(graph(team)),'asset_id':asset.json()['id'],
        'node':{'id':'capture-node','type':'media','data':{'kind':'image','prompt':'test composition'}}}


def test_director_capture_checks_owner_versions_and_records_provenance(team):
    body=capture_body(team);before=team['a'].get(url(team)).json()
    for actor in (team['b'],team['admin'],team['viewer']):
        assert actor.post(action(team,'director-captures'),json=body).status_code==403
    for key,field in [('director','expected_revision'),('director','assignment_epoch'),('graph','expected_revision')]:
        stale=deepcopy(body);stale[key][field]+=1
        response=team['a'].post(action(team,'director-captures'),json=stale)
        assert response.status_code==409,response.text
        assert team['a'].get(url(team)).json()==before
    response=team['a'].post(action(team,'director-captures'),json=body)
    assert response.status_code==200,response.text
    created=response.json()['created'][0]
    assert created['assignee_id']==team['aid']
    data=created['content']['node']['data']
    assert data['asset_ids']==[body['asset_id']]
    assert data['director_capture']=={'object_id':body['director']['id'],
        'revision':body['director']['expected_revision'],'assignment_epoch':body['director']['assignment_epoch'],
        'asset_id':body['asset_id']}
    assert team['a'].get(action(team,'objects/'+body['director']['id'])).json()['revision']==body['director']['expected_revision']
    assert 'capture-node' in graph(team)['content']['nodeOrder']


def test_capture_invalid_node_or_foreign_asset_is_atomic(team):
    body=capture_body(team);before=team['a'].get(url(team)).json()
    for bad in ({**body,'node':{'data':{'kind':'image'}}},{**body,'asset_id':'missing'},
                {**body,'node':{'id':'invalid','data':{'kind':'text'}}}):
        response=team['a'].post(action(team,'director-captures'),json=bad)
        assert response.status_code==422,response.text
        assert team['a'].get(url(team)).json()==before
    # Same production is not enough: capture material must belong to this episode.
    second=team['admin'].post(base(team)+'/episodes',json={'title':'other episode'})
    assert second.status_code==200,second.text
    image=BytesIO();Image.new('RGB',(8,8)).save(image,format='PNG')
    other=team['a'].post('/api/projects/'+second.json()['id']+'/assets',files={'file':('other.png',image.getvalue(),'image/png')})
    assert other.status_code==200,other.text
    response=team['a'].post(action(team,'director-captures'),json={**body,'asset_id':other.json()['id']})
    assert response.status_code==422,response.text
    assert team['a'].get(url(team)).json()==before


def test_capture_rechecks_director_after_real_pg_wait(team):
    body=capture_body(team)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with s.db() as c:
            # Hold the real object row, then advance its generation before the
            # blocked HTTP request obtains it. No mock timing or SQL identity.
            c.execute('SELECT id FROM collaboration_objects WHERE id=%s FOR UPDATE',(body['director']['id'],))
            pending=pool.submit(team['a'].post,action(team,'director-captures'),json=body)
            trace=wait_for_db_waiters(1)
            assert any(row['blockers'] for row in trace)
            print('director capture PostgreSQL wait trace',trace)
            c.execute('UPDATE collaboration_objects SET revision=revision+1 WHERE id=%s',(body['director']['id'],))
        response=pending.result(15)
    assert response.status_code==409,response.text
    assert not any(row['kind']=='node' for row in team['a'].get(url(team)).json())
    assert graph(team)['revision']==body['graph']['expected_revision']
