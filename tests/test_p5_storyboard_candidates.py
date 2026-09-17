"""Actual storyboard computation -> candidate -> atomic owned-object import."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import uuid
import pytest
from backend import store as s
from backend.worker import Worker
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,url,version,create,save
from tests.test_p5_canonical_integration import graph
from tests.test_p5_object_candidates import candidate,voice_card
from tests.platform_model_helpers import publish_test_model
from tests.test_film_bible import visual_input,storyboard_input
from backend.film_bible.validate import normalize_visual_bible
from tests.test_p3_r2_interleavings import wait_for_db_waiters


def storyboard(team,monkeypatch,actor=None,dual=True,input_extra=None):
    actor=actor or team['a']
    root=next((r for r in actor.get(url(team)).json() if r['kind']=='node' and r['content']['node']['id']=='storyboard-source'),None)
    if not root:
        response=actor.post(url(team),json={'kind':'node','content':{'node':{'id':'storyboard-source','type':'media',
            'data':{'kind':'storyboard','prompt':'a five second story'}}}})
        assert response.status_code==201,response.text
        root=response.json()
    model=uuid.uuid4().hex;publish_test_model(team['admin'],model)
    job_input={'model_id':model,'prompt':'a five second story','target_duration':5,'film_bible':dual}
    job_input.update(input_extra or {})
    response=actor.post('/api/projects/'+team['pid']+'/jobs',json={
        'node_id':'storyboard-source','kind':'storyboard','submission_id':uuid.uuid4().hex,
        'input':job_input})
    assert response.status_code==200,response.text
    job=response.json();requests=[]
    def answer(*args,**kwargs):
        requests.append(args)
        if dual:return json.dumps(visual_input() if len(requests)==1 else storyboard_input())
        return json.dumps({'title':'New story','shots':[{'id':'shot-001','duration':5,
            **{field:'new '+field for field in ('scene','characters','action','camera','audio','image_prompt','video_prompt')}}]})
    monkeypatch.setattr(Worker,'_chat_text',answer)
    assert s.job_update(job['id'],status='running')
    result=Worker().execute(job)
    assert len(requests)==(2 if dual else 1)
    assert s.job_update(job['id'],status='succeeded',result=result)
    return root,job,result


def objects(team):return team['a'].get(url(team)).json()


def shared_visual(team):
    visual,keys=normalize_visual_bible(visual_input())
    for value in visual['versions'].values():value['status']='locked'
    rows=[]
    for card_id,card in visual['cards'].items():
        versions={vid:deepcopy(value) for vid,value in visual['versions'].items() if value['cardId']==card_id}
        response=team['a'].post(url(team),json={'kind':'visual_card','content':{
            'card':deepcopy(card),'versions':versions,'voice_profile':None}})
        assert response.status_code==201,response.text
        rows.append(response.json())
    return visual,keys,rows


def test_two_pass_candidate_imports_nodes_bindings_and_keeps_existing_locked_card_and_voice(team,monkeypatch):
    kept=voice_card(team,'saved-voice',locked=True)
    value=deepcopy(kept['content']);value['versions']['hero-v1']['status']='locked'
    response=save(team,kept,value);assert response.status_code==200,response.text
    kept=response.json()
    root,job,result=storyboard(team,monkeypatch)
    before=objects(team)
    assert not any(r['kind']=='shot' for r in before)
    assert team['a'].get(url(team,kept)).json()==kept
    compared=team['a'].get(candidate(team,job)).json()
    assert compared['can_adopt'] is True and compared['impact']['candidate_shot_count']==1
    # The model explicitly reused the existing semantic key ``hero``. Its
    # generated description cannot overwrite that locked card or voice.
    assert compared['impact']['new_card_count']==3 and compared['impact']['shots']==[]
    response=team['a'].post(candidate(team,job)+'/adopt',json=version(root))
    assert response.status_code==200,response.text
    latest=objects(team);shots=[r for r in latest if r['kind']=='shot']
    assert [r for r in latest if r['kind'] in ('timeline','director')]==[r for r in before if r['kind'] in ('timeline','director')]
    assert len(shots)==1 and shots[0]['assignee_id']==team['aid']
    assert len(shots[0]['content']['nodes'])==2
    shot=shots[0]['content']['shot']
    assert shot['assetBindings']==result['shots'][0]['assetBindings'] and shot['dialogues']==result['shots'][0]['dialogues']
    assert shot['pipeline']=={'imageNodeId':shot['imageNode'],'videoNodeId':shot['videoNode']}
    assert team['a'].get(url(team,kept)).json()==kept
    assert len([r for r in latest if r['kind']=='visual_card'])==4
    structure=graph(team)['content']
    assert structure['shotOrder']==[shot['uid']]
    assert {(e['source'],e['target']) for e in structure['edges']}=={
        ('storyboard-source',shot['imageNode']),(shot['imageNode'],shot['videoNode'])}
    aggregate=team['a'].get('/api/projects/'+team['pid']).json()['document']
    assert aggregate['shots'][0]['uid']==shot['uid']
    assert aggregate['filmBible']['voices']['profiles']['hero']==kept['content']['voice_profile']
    assert team['a'].post(candidate(team,job)+'/adopt',json=version(response.json()['target'])).status_code==409


def test_two_pass_reuses_shared_visual_objects_and_freezes_server_catalog(team,monkeypatch):
    visual,keys,rows=shared_visual(team);before={row['id']:row for row in rows}
    root,job,result=storyboard(team,monkeypatch,input_extra={'storyboard_visual_context':{
        'version':'forged','production_id':'other','visual':{'cards':{'forged':{}},'versions':{}}}})
    context=job['input']['storyboard_visual_context']
    assert context['version']=='production-visual-reuse/v1'
    assert context['production_id']==team['production'] and context['visual']==visual
    assert job['input']['schema_version']=='film-bible-storyboard/v2'
    assert job['input']['prompt_stages'][0]['schema_version']=='visual-bible/v2'
    assert '不得仅因换集而重建卡片' in job['input']['prompt_stages'][0]['user_prompt']
    assert set(job['collaboration']['visual_catalog_objects'])==set(before)
    assert set(before)<=set(ref['id'] for ref in job['collaboration']['references'])
    assert result['filmBible']['visual']==visual
    compared=team['a'].get(candidate(team,job)).json()
    assert compared['impact']['new_card_count']==0
    response=team['a'].post(candidate(team,job)+'/adopt',json=version(root))
    assert response.status_code==200,response.text
    latest={row['id']:row for row in objects(team) if row['kind']=='visual_card'}
    assert latest==before
    shot=next(row for row in objects(team) if row['kind']=='shot')['content']['shot']
    assert shot['assetBindings']['characters'][0]['versionId']==keys['hero_wet'][1]
    assert shot['dialogues'][0]['characterCardId']==keys['hero'][0]


def test_other_episode_reuses_production_visuals_as_read_only_dependencies(team,monkeypatch):
    visual,keys,rows=shared_visual(team);before={row['id']:row for row in rows}
    response=team['admin'].post('/api/productions/'+team['production']+'/episodes',json={
        'title':'跨集视觉复用','creation_mode':'direct'})
    assert response.status_code==200,response.text
    second={**team,'pid':response.json()['id']}
    root,job,result=storyboard(second,monkeypatch,actor=team['admin'])
    assert job['input']['storyboard_visual_context']['visual']==visual
    assert set(before)<=set(ref['id'] for ref in job['collaboration']['references'])
    response=team['admin'].post(candidate(second,job)+'/adopt',json=version(root))
    assert response.status_code==200,response.text
    latest={row['id']:row for row in team['admin'].get(url(second)).json() if row['kind']=='visual_card'}
    assert latest==before
    shot=next(row for row in team['admin'].get(url(second)).json() if row['kind']=='shot')['content']['shot']
    assert shot['assetBindings']['characters'][0]['versionId']==keys['hero_wet'][1]
    assert shot['dialogues'][0]['characterCardId']==keys['hero'][0]


@pytest.mark.parametrize('change',['edit_existing','create_card'])
def test_visual_catalog_change_blocks_storyboard_adoption_without_partial_writes(team,monkeypatch,change):
    _,_,rows=shared_visual(team)
    root,job,_=storyboard(team,monkeypatch)
    if change=='edit_existing':
        row=rows[0];content=deepcopy(row['content']);content['card']['aliases']=['新的确认别名']
        response=save(team,row,content);assert response.status_code==200,response.text
    else:
        card_id='late-'+uuid.uuid4().hex;version_id=card_id+'-v1'
        response=team['a'].post(url(team),json={'kind':'visual_card','content':{
            'card':{'id':card_id,'kind':'prop','name':'迟到道具','parentCardId':None,
                    'currentVersionId':version_id,'status':'active','source':{'type':'script_extraction'}},
            'versions':{version_id:{'id':version_id,'cardId':card_id,'version':1,'parentVersionId':None,
                'status':'draft','spec':{'description':'迟到道具','attributes':[]},'invariants':[],
                'references':[],'createdAt':1,'provenance':{}}},'voice_profile':None}})
        assert response.status_code==201,response.text
    before=objects(team)
    response=team['a'].post(candidate(team,job)+'/adopt',json={**version(root),'accept_stale':True})
    assert response.status_code==409,response.text
    assert objects(team)==before
    assert 'adopted' not in team['a'].get(candidate(team,job)).json()['job']['collaboration']


@pytest.mark.parametrize('reason',['other_owner','edited_after_submission'])
def test_replacing_shots_checks_every_owner_and_frozen_version_with_no_partial_import(team,monkeypatch,reason):
    old=create(team,team['b'] if reason=='other_owner' else team['a'],id='shot-001')
    root,job,result=storyboard(team,monkeypatch)
    assert old['id'] in job['collaboration']['replacement_shots']
    if reason=='edited_after_submission':
        assert save(team,old,{'description':'new human edit'}).status_code==200
    before=objects(team)
    response=team['a'].post(candidate(team,job)+'/adopt',json={**version(root),'accept_stale':True})
    assert response.status_code==(403 if reason=='other_owner' else 409),response.text
    assert objects(team)==before
    assert 'adopted' not in team['a'].get(candidate(team,job)).json()['job']['collaboration']


def test_matching_shot_preserves_object_uid_children_and_marks_previous_media_stale(team,monkeypatch):
    from io import BytesIO
    from PIL import Image
    root,first,_=storyboard(team,monkeypatch,dual=False)
    response=team['a'].post(candidate(team,first)+'/adopt',json=version(root));assert response.status_code==200,response.text
    old=next(r for r in objects(team) if r['kind']=='shot');content=deepcopy(old['content'])
    buffer=BytesIO();Image.new('RGB',(8,8),'blue').save(buffer,format='PNG')
    response=team['a'].post('/api/projects/'+team['pid']+'/assets',files={'file':('old-frame.png',buffer.getvalue(),'image/png')})
    assert response.status_code==200,response.text
    asset=response.json();content['nodes'][0]['data']['assetId']=asset['id']
    # Existing result identity is preserved; no media is deleted by regeneration.
    for child in content['nodes']:child['data'].update(resultJob='previous-result',state_reviewed=True,prompt='manual node override')
    response=save(team,old,content);assert response.status_code==200,response.text
    old=response.json()
    root,job,_=storyboard(team,monkeypatch,dual=False)
    response=team['a'].post(candidate(team,job)+'/adopt',json=version(root));assert response.status_code==200,response.text
    new=next(r for r in objects(team) if r['kind']=='shot')
    assert (new['id'],new['content']['shot']['uid'])==(old['id'],old['content']['shot']['uid'])
    assert [n['id'] for n in new['content']['nodes']]==[n['id'] for n in old['content']['nodes']]
    assert new['revision']==old['revision']+1
    assert all(n['data']['stale'] and n['data']['resultJob']=='previous-result' for n in new['content']['nodes'])
    assert all(n['data']['prompt']=='manual node override' for n in new['content']['nodes'])
    assert new['content']['nodes'][0]['data']['state_reviewed'] is False
    assert new['content']['nodes'][0]['data']['assetId']==asset['id']
    assert asset['id'] in {a['id'] for a in team['a'].get('/api/projects/'+team['pid']+'/assets').json()}


def test_removing_old_shot_requires_manager_as_well_as_object_ownership(team,monkeypatch):
    create(team,id='old-extra')
    root,job,_=storyboard(team,monkeypatch,dual=False);before=objects(team)
    compared=team['a'].get(candidate(team,job)).json()
    assert compared['can_adopt'] is False and len(compared['impact']['removed_ids'])==1
    response=team['a'].post(candidate(team,job)+'/adopt',json=version(root))
    assert response.status_code==403,response.text
    assert objects(team)==before
    # Explicit management takeover invalidates the old candidate. Submit anew.
    for row in before:
        if row['kind'] in ('shot','node'):
            response=team['admin'].post(url(team,row,'/assign'),json={**version(row),
                'assignee_id':team['admin'].get('/api/auth/status').json()['user']['id']})
            assert response.status_code==200,response.text
    root,job,_=storyboard(team,monkeypatch,actor=team['admin'],dual=False)
    response=team['admin'].post(candidate(team,job)+'/adopt',json=version(root))
    assert response.status_code==200,response.text
    assert [r['content']['shot']['id'] for r in objects(team) if r['kind']=='shot']==['shot-001']


def test_two_storyboard_candidates_compete_through_real_pg_graph_lock(team,monkeypatch):
    root,first,_=storyboard(team,monkeypatch,dual=False)
    _,second,_=storyboard(team,monkeypatch,dual=False)
    structure=graph(team)
    with ThreadPoolExecutor(max_workers=2) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM collaboration_objects WHERE id=%s FOR UPDATE',(structure['id'],))
            futures=[pool.submit(team['a'].post,candidate(team,job)+'/adopt',json=version(root)) for job in (first,second)]
            waits=wait_for_db_waiters(2);assert all(row['blockers'] for row in waits)
            print('P5 storyboard import wait trace:',waits)
        responses=[f.result(15) for f in futures]
    assert sorted(r.status_code for r in responses)==[200,409],[r.text for r in responses]
    assert len([r for r in objects(team) if r['kind']=='shot'])==1
    assert sum(bool(team['a'].get(candidate(team,job)).json()['job']['collaboration'].get('adopted')) for job in (first,second))==1


def test_new_candidate_nodes_derive_published_controls_without_picking_another_model():
    from backend.storyboard_candidates import new_node
    from backend.model_validation import parameters
    image={'id':'image','capabilities':{},'rules':{'resolution':{'type':'string'}},'defaults':{'resolution':'2048x1152'}}
    video={'id':'video','capabilities':{'fps':24,'min_frames':124,'frame_step':17,'max_frames':345},
        'rules':{'frames':{'type':'integer','min':124,'max':345},'seed':{'type':'integer'}},'defaults':{'frames':124}}
    document={'ratio':'9:16','generationPolicy':{'image':{'model_id':'image'},'video':{'model_id':'video'}}}
    shot={'id':'s','duration':8,'image_prompt':'frame','video_prompt':'motion'}
    assert new_node('image',shot,document,[image,video])['data']['parameters']['resolution']=='1152x2048'
    data=new_node('video',shot,document,[image,video])['data']
    assert data['parameters']['frames']==192 and 'seed' not in data['parameters']
    # Editable node creation may leave an unchosen seed; actual submission must
    # still reject missing published restricted parameters (P4 unchanged).
    with pytest.raises(ValueError,match='缺少平台受限参数'):parameters(video,data['parameters'])
    assert new_node('image',shot,{'generationPolicy':{}},[image])['data']['model_id']==''
