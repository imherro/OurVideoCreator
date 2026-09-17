import os
import json
import tempfile
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.app import app
from backend import store as s
from backend.worker import Worker
from tests.auth_helpers import login_admin
from tests.platform_model_helpers import publish_test_model, bind_adapter_job, CANARY
from tests.egress_helpers import mock_egress, public_test_dns
from tests.collaboration_helpers import create_object, patch_object, create_visual_cards, object_version, create_node, set_edges

@pytest.fixture(scope='module')
def client():
    with TestClient(app) as c:
        yield c

@pytest.fixture(scope='module')
def authenticated(client):
    assert client.get('/api/projects').status_code==401
    login_admin(client)
    return client

def project(c):
    response=c.post('/api/projects',json={'name':'测试短片'})
    assert response.status_code==200,response.text
    return response.json()

def test_public_setup_is_retired_for_remote_browsers(client):
    with TestClient(app,client=('192.0.2.10',43120)) as remote:
        assert remote.get('/api/auth/status').json()['can_setup'] is False
        assert remote.post('/api/auth/setup').status_code == 410

def test_production_can_own_multiple_episode_projects(authenticated):
    c=authenticated
    created=c.post('/api/productions',json={'name':'六十集测试剧'})
    assert created.status_code==200,created.text
    production=created.json()
    first=c.post(f'/api/productions/{production["id"]}/episodes',json={'title':'觉醒'}).json()
    second=c.post(f'/api/productions/{production["id"]}/episodes',json={}).json()
    assert first['id']!=second['id']
    assert first['production_id']==second['production_id']==production['id']
    assert first['episode_no']==1 and first['episode_title']=='觉醒'
    assert second['episode_no']==2 and second['episode_title']=='第 02 集'
    assert first['revision']==second['revision']==1
    episodes=c.get(f'/api/productions/{production["id"]}/episodes').json()
    assert [item['id'] for item in episodes]==[first['id'],second['id']]


def test_production_context_is_shared_versioned_and_episode_documents_stay_local(authenticated):
    import copy
    import io
    from PIL import Image
    from backend.app import reference_asset
    from backend.film_bible import normalize_visual_bible

    c=authenticated
    production=c.post('/api/productions',json={'name':'共享资料测试剧'}).json()
    first=c.post(f'/api/productions/{production["id"]}/episodes',json={'title':'第一集'}).json()
    second=c.post(f'/api/productions/{production["id"]}/episodes',json={'title':'第二集'}).json()
    stale_second=copy.deepcopy(second)

    stream=io.BytesIO();Image.new('RGB',(16,16),'#26384a').save(stream,format='PNG')
    reference=c.post(
        f'/api/projects/{first["id"]}/assets?category=character',
        files={'file':('shared-hero.png',stream.getvalue(),'image/png')},
    ).json()
    assert reference['production_id']==production['id']
    assert reference['project_id']==first['id']
    visual,ids=normalize_visual_bible({'cards':[{
        'key':'hero','kind':'character','name':'共享主角','parent_key':'',
        'description':'固定深蓝外套','attributes':[],'invariants':['服装不变'],
    }]})
    version_id=ids['hero'][1]
    visual['versions'][version_id]['status']='locked'
    visual['versions'][version_id]['references']=[{'role':'primary','assetId':reference['id']}]
    card_id=ids['hero'][0]
    card=c.post(f'/api/projects/{first["id"]}/objects',json={'kind':'visual_card','content':{
        'card':visual['cards'][card_id],'versions':visual['versions'],'voice_profile':None}})
    assert card.status_code==201,card.text
    saved=c.patch(f'/api/productions/{production["id"]}/context',json={
        'expected_revision':first['production_revision'],'patch':{'style':'shared updated style'}})
    assert saved.status_code==200,saved.text
    assert saved.json()['revision']==first['production_revision']+1

    inherited=c.get(f'/api/projects/{second["id"]}').json()
    assert inherited['production_revision']==saved.json()['revision']
    assert inherited['document']['filmBible']['visual']['versions'][version_id]['references'][0]['assetId']==reference['id']
    assert reference_asset(second['id'],reference['id'])['id']==reference['id']

    conflict=c.patch(f'/api/productions/{production["id"]}/context',json={
        'expected_revision':stale_second['production_revision'],'patch':{'style':'冲突风格'}})
    assert conflict.status_code==409

    inherited['document']['shots']=[{
        'id':'shared-shot','uid':'shared-shot','order':1,
        'assetBindings':{'characters':[{'role':'主角','versionId':version_id}],'scene':None,'props':[]},
        'pipeline':{},
    }]
    episode_save=c.post(f'/api/projects/{second["id"]}/objects',json={'kind':'shot',
        'content':{'shot':inherited['document']['shots'][0],'nodes':[]}})
    assert episode_save.status_code==201,episode_save.text
    assert c.get(f'/api/projects/{second["id"]}').json()['production_revision']==inherited['production_revision']
    production_assets=c.get(f'/api/productions/{production["id"]}/assets').json()
    inherited_assets=c.get(f'/api/projects/{second["id"]}/assets?scope=production').json()
    assert [item['id'] for item in production_assets]==[reference['id']]
    assert [item['id'] for item in inherited_assets]==[reference['id']]
    assert inherited_assets[0]['origin_episode_no']==1
    with s.db() as db:
        stored_asset=db.execute('SELECT id,project_id,production_id,path,metadata,category,source FROM assets WHERE id=%s',(reference['id'],)).fetchone()
        assert db.execute('SELECT COUNT(*) count FROM assets WHERE id=%s',(reference['id'],)).fetchone()['count']==1
    assert stored_asset['project_id']==first['id'] and stored_asset['production_id']==production['id']
    assert (s.ASSETS/stored_asset['path']).read_bytes()==stream.getvalue()
    usage=c.get(f'/api/productions/{production["id"]}/visual-usage').json()
    assert usage==[{
        'version_id':version_id,
        'episodes':[{'project_id':second['id'],'episode_no':2,'episode_title':'第二集'}],
        'shots':[{'project_id':second['id'],'episode_no':2,'shot_uid':'shared-shot','shot_id':'shared-shot'}],
    }]
    with s.db() as db:
        rows=db.execute(
            'SELECT id,document FROM projects WHERE production_id=%s ORDER BY episode_no',
            (production['id'],),
        ).fetchall()
        assert len(db.execute(
            'SELECT id FROM production_revisions WHERE production_id=%s',
            (production['id'],),
        ).fetchall())==1
    for row in rows:
        persisted=json.loads(row['document'])
        assert 'filmBible' not in persisted
        assert 'generationPolicy' not in persisted
        assert 'style' not in persisted
    assert c.get(f'/api/productions/{production["id"]}').json()['episode_count']==2
    listed={item['id']:item for item in c.get('/api/projects').json()}
    assert listed[first['id']]['production_id']==production['id']

    other=c.post('/api/projects',json={'name':'另一个 Production'}).json()
    reference_provider=publish_test_model(c,'reference-test-api',kind='image',provider_type='volcengine_ark',
        capabilities={'image_reference':True,'max_references':10})
    for target,nid in [(second,'same-production-reference'),(other,'cross-production-reference')]:
        created=c.post(f'/api/projects/{target["id"]}/objects',json={'kind':'node',
            'content':{'node':{'id':nid,'type':'media','data':{'kind':'image'}}}})
        assert created.status_code==201,created.text
    accepted_job=c.post(f'/api/projects/{second["id"]}/jobs',json={
        'node_id':'same-production-reference','kind':'image','submission_id':'same-production-reference-1',
        'input':{'prompt':'只验证引用边界','model_id':reference_provider['id'],'asset_ids':[reference['id']]},
    })
    assert accepted_job.status_code==200,accepted_job.text
    rejected_job=c.post(f'/api/projects/{other["id"]}/jobs',json={
        'node_id':'cross-production-reference','kind':'image','submission_id':'cross-production-reference-1',
        'input':{'prompt':'只验证引用边界','model_id':reference_provider['id'],'asset_ids':[reference['id']]},
    })
    assert rejected_job.status_code==400
    assert '其他 Production' in rejected_job.json()['detail']
    rejected=c.patch(
        f'/api/projects/{other["id"]}/assets/{reference["id"]}',
        json={'category':'reference'},
    )
    # Cross-production nested IDs are deliberately concealed by the P3 ACL.
    assert rejected.status_code==404

    # FINAL-FUNC-01: a live visual reference must survive attempted deletion.
    assert c.delete(f'/api/projects/{second["id"]}/assets/{reference["id"]}').status_code==409
    assert c.get(f'/api/assets/{reference["id"]}/file').content==stream.getvalue()
    assert [item['id'] for item in c.get(f'/api/productions/{production["id"]}/assets').json()]==[reference['id']]
    assert (s.ASSETS/stored_asset['path']).read_bytes()==stream.getvalue()

def test_empty_production_remains_visible_until_its_first_episode_is_created(authenticated):
    c=authenticated
    production=c.post('/api/productions',json={'name':'待建分集'}).json()
    listed={item['id']:item for item in c.get('/api/productions').json()}
    assert listed[production['id']]['episode_count']==0

def test_legacy_project_create_api_still_creates_one_episode_wrapper(authenticated):
    c=authenticated
    item=project(c)
    assert item['production_id']
    assert item['episode_no']==1 and item['episode_title']==item['name']
    parent=c.get('/api/productions/'+item['production_id']).json()
    assert parent['name']==item['name'] and parent['episode_count']==1

def test_project_schema_revision_and_generation_policy_roundtrip(authenticated):
    c=authenticated
    for kind in ('text','image','video'):
        publish_test_model(c,'phase0-'+kind,kind=kind,provider_type='volcengine_ark',default=True)
    publish_test_model(c,'seedance-custom',kind='video',provider_type='volcengine_ark')
    created=project(c)
    from backend.project_schema import CURRENT_SCHEMA_VERSION
    assert created['document']['schemaVersion']==CURRENT_SCHEMA_VERSION
    assert created['document']['generationPolicy']['image']=={'model_id':'phase0-image'}
    policy={**created['document']['generationPolicy'],'video':{'model_id':'seedance-custom'}}
    saved=c.patch('/api/productions/'+created['production_id']+'/context',json={
        'expected_revision':created['production_revision'],'patch':{'generationPolicy':policy}})
    assert saved.status_code==200,saved.text
    reopened=c.get('/api/projects/'+created['id']).json()['document']
    assert reopened['generationPolicy']['video']['model_id']=='seedance-custom'
    assert reopened['schemaVersion']==CURRENT_SCHEMA_VERSION


def test_film_bible_and_shot_bindings_round_trip_through_project_document(authenticated):
    import io
    from PIL import Image
    c=authenticated;p=project(c);doc=p['document']
    from backend.film_bible import normalize_visual_bible
    visual,key_ids=normalize_visual_bible({'cards':[{
      'key':'hero','kind':'character','name':'林岚','parent_key':'','description':'灰色风衣',
      'attributes':[],'invariants':['灰色风衣'],
    }]})
    doc['filmBible']['visual']=visual;version_id=key_ids['hero'][1]
    card_id=key_ids['hero'][0]
    visual['cards'][card_id]['generation']={'image':{'mode':'override','model_id':'seedream-custom'}}
    visual['versions'][version_id]['status']='locked'
    stream=io.BytesIO();Image.new('RGB',(8,8),'#334455').save(stream,format='PNG')
    reference=c.post(f'/api/projects/{p["id"]}/assets',files={'file':('reference.png',stream.getvalue(),'image/png')}).json()
    visual['versions'][version_id]['references']=[{
      'role':'primary','assetId':reference['id'],'source':'generated','createdAt':123,
      'provenance':{'jobId':'job-reference','model_id':'seedream-custom','targetSource':'override'},
    }]
    visual['versions'][version_id]['provenance']={'lockedAt':124}
    doc['shots']=[{'id':'shot-001','uid':'shot-stable-1','order':1,'assetBindings':{
      'characters':[{'role':'林岚','versionId':version_id}],'scene':None,'props':[]},'pipeline':{}}]
    create_visual_cards(c,p['id'],visual)
    create_object(c,p['id'],'shot',{'shot':doc['shots'][0],'nodes':[]})
    restored=c.get('/api/projects/'+p['id']).json()['document']
    assert restored['filmBible']['visual']==doc['filmBible']['visual']
    assert restored['filmBible']['visual']['cards'][card_id]['generation']['image']['mode']=='override'
    assert restored['filmBible']['visual']['versions'][version_id]['references'][0]['assetId']==reference['id']
    assert restored['shots']==doc['shots']
    assert all(card['source']=={'type':'script_extraction'} for card in restored['filmBible']['visual']['cards'].values())

def test_phase5_roundtrip_preserves_versions_binding_fingerprint_stale_and_media_without_jobs(authenticated):
    import copy
    import io
    from PIL import Image
    from backend.generation_fingerprint import build_generation_fingerprint
    c=authenticated;p=project(c);doc=p['document']
    v1={
        'id':'hero-v1','cardId':'hero','version':1,'parentVersionId':None,'status':'locked',
        'spec':{'description':'灰色风衣','attributes':[]},'invariants':['脸型不变'],
        'references':[{'role':'primary','assetId':'ref-v1'}],'createdAt':1,'provenance':{'lockedAt':2},
    }
    stream=io.BytesIO();Image.new('RGB',(16,16),'#334455').save(stream,format='PNG')
    media=c.post(f'/api/projects/{p["id"]}/assets?category=shot',files={'file':('old.png',stream.getvalue(),'image/png')}).json()
    v1['references'][0]['assetId']=media['id']
    doc['filmBible']['visual']={
        'cards':{'hero':{'id':'hero','kind':'character','name':'林岚','parentCardId':None,'currentVersionId':'hero-v1','status':'active','source':{'type':'script_extraction'}}},
        'versions':{'hero-v1':v1},
    }
    doc['shots']=[
        {'id':'A','uid':'shot-A','imageNode':'image-A','assetBindings':{'characters':[{'role':'林岚','versionId':'hero-v1'}],'scene':None,'props':[]}},
        {'id':'B','uid':'shot-B','imageNode':'image-B','assetBindings':{'characters':[{'role':'林岚','versionId':'hero-v1'}],'scene':None,'props':[]}},
    ]
    doc['nodes']=[]
    for shot in doc['shots']:
        fingerprint=build_generation_fingerprint(doc,shot,'phase5-provider','phase5-model',1)
        doc['nodes'].append({'id':shot['imageNode'],'data':{
            'kind':'image','model_id':'phase5-model',
            'assetId':media['id'],'resultJob':'historical-job-'+shot['id'],
            'generationFingerprint':fingerprint,
        }})
    before_jobs=len(c.get(f'/api/projects/{p["id"]}/jobs').json())
    card=create_visual_cards(c,p['id'],doc['filmBible']['visual'])['hero']
    shots={shot['id']:create_object(c,p['id'],'shot',{'shot':shot,
        'nodes':[node for node in doc['nodes'] if node['id']==shot['imageNode']]}) for shot in doc['shots']}

    # Fork v1 -> draft v2. Merely moving currentVersionId must not upgrade a Shot.
    doc=c.get(f'/api/projects/{p["id"]}').json()['document']
    doc['filmBible']['visual']['versions']['hero-v2']={
        **copy.deepcopy(v1),'id':'hero-v2','version':2,'parentVersionId':'hero-v1','status':'draft',
        'spec':{'description':'蓝色风衣','attributes':[]},'references':[],
        'provenance':{'forkedFromVersionId':'hero-v1'},
    }
    doc['filmBible']['visual']['cards']['hero']['currentVersionId']='hero-v2'
    second=patch_object(c,p['id'],card,{'card':doc['filmBible']['visual']['cards']['hero'],
        'versions':doc['filmBible']['visual']['versions'],'voice_profile':None})
    assert second.status_code==200,second.text
    card=second.json()
    after_fork=c.get(f'/api/projects/{p["id"]}').json()['document']
    assert [shot['assetBindings']['characters'][0]['versionId'] for shot in after_fork['shots']]==['hero-v1','hero-v1']
    assert after_fork['filmBible']['visual']['versions']['hero-v1']==v1

    # Confirm v2, then explicitly upgrade only Shot A and mark its old result stale.
    doc=copy.deepcopy(after_fork);v2=doc['filmBible']['visual']['versions']['hero-v2']
    v2['status']='locked';v2['references']=[{'role':'primary','assetId':media['id']}];v2['provenance']['lockedAt']=3
    third=patch_object(c,p['id'],card,{'card':doc['filmBible']['visual']['cards']['hero'],
        'versions':doc['filmBible']['visual']['versions'],'voice_profile':None})
    assert third.status_code==200,third.text
    card=third.json()
    doc=c.get(f'/api/projects/{p["id"]}').json()['document']
    upgraded=copy.deepcopy(shots['A']['content'])
    upgraded['shot']['assetBindings']['characters'][0]['versionId']='hero-v2'
    fourth=patch_object(c,p['id'],shots['A'],upgraded)
    assert fourth.status_code==200,fourth.text
    restored=c.get(f'/api/projects/{p["id"]}').json()['document']
    assert restored['filmBible']['visual']['versions']['hero-v1']['spec']['description']=='灰色风衣'
    assert restored['filmBible']['visual']['versions']['hero-v2']['parentVersionId']=='hero-v1'
    assert restored['shots'][0]['assetBindings']['characters'][0]['versionId']=='hero-v2'
    assert restored['shots'][1]['assetBindings']['characters'][0]['versionId']=='hero-v1'
    assert restored['nodes'][0]['data']['generationFingerprint']['hash']!=restored['nodes'][0]['data']['currentGenerationFingerprint']['hash']
    assert restored['nodes'][0]['data']['generationStatus']=='stale'
    assert restored['nodes'][0]['data']['stale'] is True
    assert restored['nodes'][1]['data']['generationStatus']=='current'
    assert restored['nodes'][1]['data'].get('stale') is not True

    # The HTTP save boundary blocks direct tampering and hard deletion.
    mutation=copy.deepcopy(card['content']);mutation['versions']['hero-v1']['spec']['description']='覆盖历史'
    assert patch_object(c,p['id'],card,mutation).status_code==400
    deletion=copy.deepcopy(card['content']);del deletion['versions']['hero-v1']
    assert patch_object(c,p['id'],card,deletion).status_code==400
    deprecated=copy.deepcopy(card['content']);deprecated['versions']['hero-v1']['status']='deprecated'
    archived=patch_object(c,p['id'],card,deprecated)
    assert archived.status_code==200,archived.text
    assert c.get(f'/api/projects/{p["id"]}').json()['document']['shots'][1]['assetBindings']['characters'][0]['versionId']=='hero-v1'
    assert len(c.get(f'/api/projects/{p["id"]}/jobs').json())==before_jobs
    assert c.get(f'/api/assets/{media["id"]}/file').status_code==200

def test_visual_reference_queue_validates_server_capability_and_persists_ownership(authenticated,monkeypatch,tmp_path):
    import copy
    import io
    from PIL import Image
    import backend.visual_references as visual_references
    from backend.film_bible import normalize_visual_bible

    c=authenticated
    provider=publish_test_model(c,'phase3-image',kind='image',provider_type='volcengine_ark',
        capabilities={'image_reference':True,'max_references':10})
    try:
        p=project(c)
        adaptation={
            'revision':c.get(f'/api/productions/{p["production_id"]}/adaptation').json()['revision'],
            'adaptationPlan':{
                'status':'approved',
                'format':{'episodeCount':2,'targetDuration':45,'ratio':'9:16','platform':'测试平台'},
                'storyCore':{'premise':'非默认前提'},'storyArc':{'opening':'非默认开场'},
                'adaptationStrategy':{'tone':'非默认风格'},'sourceEventIds':[],
            },
            'episodePlans':[{
                'episodeNo':number,'sourceChapterRefs':[],'logline':f'第 {number} 集',
                'coreConflict':'守护真相','emotionalBeat':'紧张','hook':'立刻入戏',
                'cliffhanger':'留下悬念','paywallRole':'conversion' if number==2 else 'setup',
                'targetDuration':45,'status':'approved',
            } for number in (1,2)],
            'monetizationPlan':{
                'mode':'custom','freeEpisodes':1,'firstPaywallEpisode':2,
                'beats':[{'episodeNo':1,'type':'pre_paywall_hook','setup':'非默认铺垫',
                    'cliffhanger':'非默认卡点','expectedEmotion':'期待','rationale':'测试保留'}],
            },
        }
        adaptation_saved=c.put(
            f'/api/productions/{p["production_id"]}/adaptation',json=adaptation,
        )
        assert adaptation_saved.status_code==200,adaptation_saved.text
        before_adaptation=c.get(f'/api/productions/{p["production_id"]}/adaptation').json()
        before_adaptation={key:copy.deepcopy(before_adaptation[key]) for key in (
            'adaptationPlan','episodePlans','monetizationPlan',
        )}
        p=c.get(f'/api/projects/{p["id"]}').json();doc=p['document']
        visual,keys=normalize_visual_bible({'cards':[
            {'key':'hero','kind':'character','name':'林岚','parent_key':'','description':'灰色风衣','attributes':[],'invariants':['脸型不变']},
            {'key':'wet','kind':'character_state','name':'雨中的林岚','parent_key':'hero','description':'衣服淋湿','attributes':[],'invariants':['仍是同一人']},
        ]})
        hero_version=keys['hero'][1];state_version=keys['wet'][1]
        stream=io.BytesIO();Image.new('RGB',(24,24),'#334455').save(stream,format='PNG')
        parent=c.post(
            f'/api/projects/{p["id"]}/assets?category=character',
            files={'file':('parent.png',stream.getvalue(),'image/png')},
        ).json()
        visual['versions'][hero_version]['status']='locked'
        visual['versions'][hero_version]['references']=[{'role':'primary','assetId':parent['id']}]
        doc['filmBible']['visual']=visual
        doc['generationPolicy']['image']={'model_id':'phase3-image'}
        cards=create_visual_cards(c,p['id'],visual)
        state_card=cards[keys['wet'][0]]
        saved=c.patch(f'/api/productions/{p["production_id"]}/context',json={
            'expected_revision':p['production_revision'],'patch':{'generationPolicy':doc['generationPolicy']}})
        assert saved.status_code==200,saved.text
        prepared=c.get(f'/api/projects/{p["id"]}').json()
        payload={
            'node_id':f'visual-version:{state_version}','kind':'image','submission_id':'phase3-state-reference',
            'input':{
                'model_id':'phase3-image','prompt':'雨中状态','allow_cloud':False,
                'model_capabilities':{'image_reference':True},
                'asset_ids':[parent['id']],'asset_category':'character',
                'visual_reference':{
                    'versionId':state_version,'targetSource':'project',
                    'parentVersionId':hero_version,'parentReferenceAssetId':parent['id'],
                },
            },
        }
        before=len(c.get(f'/api/projects/{p["id"]}/jobs').json())
        rejected_capabilities=[
            lambda provider,model_id:None,
            lambda provider,model_id:{'image_reference':False},
            lambda provider,model_id:(_ for _ in ()).throw(ValueError('图片模型目录中找不到所选模型')),
        ]
        for resolver in rejected_capabilities:
            monkeypatch.setattr(visual_references,'resolve_image_model_capabilities',resolver)
            rejected=c.post(f'/api/projects/{p["id"]}/jobs',json=payload)
            assert rejected.status_code==400,rejected.text
            assert len(c.get(f'/api/projects/{p["id"]}/jobs').json())==before

        monkeypatch.setattr(visual_references,'resolve_image_model_capabilities',lambda provider,model_id:{'image_reference':True})
        accepted=c.post(f'/api/projects/{p["id"]}/jobs',json=payload)
        assert accepted.status_code==200,accepted.text
        duplicate_payload={**payload,'submission_id':'phase3-state-reference-duplicate'}
        duplicate=c.post(f'/api/projects/{p["id"]}/jobs',json=duplicate_payload)
        assert duplicate.status_code==409
        assert '已有任务' in duplicate.text
        job=accepted.json()
        assert 'project_document' not in job
        assert job['collaboration']['target']=={'kind':'visual_card','id':state_card['id'],
            'revision':state_card['revision'],'assignment_epoch':state_card['assignment_epoch']}
        queued=c.get(f'/api/projects/{p["id"]}').json()
        assert queued['revision']==prepared['revision'] and queued['production_revision']==prepared['production_revision']
        assert queued['document']['filmBible']['visual']==prepared['document']['filmBible']['visual']
        # Register a synthetic local result; no provider HTTP is made here.
        from backend.providers.common import register
        image_path=tmp_path/'visual-candidate.png';Image.new('RGB',(24,24),'#445566').save(image_path)
        assert s.job_update(job['id'],status='running')
        asset=register(job,image_path)
        assert s.job_update(job['id'],status='succeeded',result={'assets':[asset]})
        assert c.get(f'/api/projects/{p["id"]}').json()['document']['filmBible']['visual']==visual
        adopted=c.post(f'/api/projects/{p["id"]}/candidates/{job["id"]}/adopt',json=object_version(state_card))
        assert adopted.status_code==200,adopted.text
        current=adopted.json()['target'];generation=current['content']['versions'][state_version]['provenance']['referenceGeneration']
        assert generation['submissionId']==payload['submission_id']
        assert generation['jobId']==job['id']
        assert current['content']['versions'][state_version]['status']=='pending_reference'
        assert current['content']['versions'][state_version]['references'][0]['assetId']==asset['id']
        restored=c.get(f'/api/projects/{p["id"]}').json()
        assert restored['revision']==prepared['revision']
        assert restored['production_revision']==prepared['production_revision']
        assert restored['document']['filmBible']['visual']['versions'][state_version]['provenance']['referenceGeneration']==generation
        after_adaptation=c.get(f'/api/productions/{p["production_id"]}/adaptation').json()
        assert {key:after_adaptation[key] for key in before_adaptation}==before_adaptation
        stale_without_production_token=copy.deepcopy(doc)
        stale_without_production_token['style']='不应覆盖的新风格'
        bypass=c.put(f'/api/projects/{p["id"]}',json={
            'name':p['name'],'revision':restored['revision'],
            'document':stale_without_production_token,
        })
        assert bypass.status_code==410
        assert c.get('/api/jobs/'+job['id']).json()['input']['asset_ids']==[parent['id']]
        assert c.post(f'/api/projects/{p["id"]}/candidates/{job["id"]}/adopt',json=object_version(current)).status_code==409
    finally:
        pass

def test_shot_reference_compiler_is_identical_for_single_and_batch_submission(authenticated,monkeypatch):
    import io
    from PIL import Image
    import backend.reference_compiler as reference_compiler
    import backend.visual_references as visual_references
    from backend.film_bible import normalize_visual_bible

    c=authenticated
    provider=publish_test_model(c,'phase4-image',kind='image',provider_type='volcengine_ark',
        capabilities={'image_reference':True,'max_references':10})
    try:
        p=project(c);doc=p['document']
        visual,keys=normalize_visual_bible({'cards':[
            {'key':'hero','kind':'character','name':'林岚','parent_key':'','description':'灰色风衣','attributes':[],'invariants':['脸型不变']},
            {'key':'alley','kind':'scene','name':'雨巷','parent_key':'','description':'青砖窄巷','attributes':[],'invariants':['拱门位置不变']},
        ]})
        assets={}
        for key,color in [('hero','#334455'),('alley','#556677'),('manual','#778899')]:
            stream=io.BytesIO();Image.new('RGB',(24,24),color).save(stream,format='PNG')
            assets[key]=c.post(
                f'/api/projects/{p["id"]}/assets?category=character',
                files={'file':(key+'.png',stream.getvalue(),'image/png')},
            ).json()
        for key in ('hero','alley'):
            version=visual['versions'][keys[key][1]]
            version['status']='locked'
            version['references']=[{'role':'primary','assetId':assets[key]['id']}]
        image_node={
            'id':'phase4-image-node','type':'media','position':{'x':0,'y':0},
            'data':{
                'kind':'image','label':'分镜图','model_id':'phase4-image',
                'prompt':'中景，人物穿过雨巷','asset_ids':[assets['manual']['id']],
            },
        }
        manual_node={
            'id':'manual-reference','type':'media','position':{'x':0,'y':0},
            'data':{'kind':'reference','assetId':assets['manual']['id']},
        }
        doc['filmBible']['visual']=visual
        doc['nodes']=[manual_node,image_node]
        doc['edges']=[{'id':'manual-edge','source':'manual-reference','target':'phase4-image-node'}]
        doc['shots']=[{
            'id':'shot-001','uid':'phase4-shot','imageNode':'phase4-image-node',
            'assetBindings':{
                'characters':[{'role':'主角','versionId':keys['hero'][1]}],
                'scene':{'versionId':keys['alley'][1]},'props':[],
            },
        }]
        create_visual_cards(c,p['id'],visual)
        create_object(c,p['id'],'node',{'node':{key:value for key,value in manual_node.items() if key!='position'}})
        create_object(c,p['id'],'shot',{'shot':doc['shots'][0],
            'nodes':[{key:value for key,value in image_node.items() if key!='position'}]})
        graph=next(row for row in c.get(f'/api/projects/{p["id"]}/objects').json() if row['kind']=='graph')
        structure={**graph['content'],'edges':doc['edges'],
            'positions':{node['id']:node['position'] for node in doc['nodes']}}
        saved=patch_object(c,p['id'],graph,structure)
        assert saved.status_code==200,saved.text

        maximum={'value':1}
        def capabilities(provider_value,model_id):
            return {'image_reference':True,'max_references':maximum['value']}
        monkeypatch.setattr(reference_compiler,'resolve_image_model_capabilities',capabilities)
        monkeypatch.setattr(visual_references,'resolve_image_model_capabilities',capabilities)

        single_payload={
            'node_id':'phase4-image-node','kind':'image','submission_id':'phase4-single-rejected',
            'input':{**image_node['data'],'allow_cloud':False},
        }
        rejected=c.post(f'/api/projects/{p["id"]}/jobs',json=single_payload)
        assert rejected.status_code==400 and '不会截断参考图' in rejected.text
        assert c.get(f'/api/projects/{p["id"]}/jobs').json()==[]

        maximum['value']=2
        single_payload['submission_id']='phase4-single-accepted'
        accepted=c.post(f'/api/projects/{p["id"]}/jobs',json=single_payload)
        assert accepted.status_code==200,accepted.text
        single=c.get('/api/jobs/'+accepted.json()['id']).json()['input']
        expected=[assets['hero']['id'],assets['alley']['id']]
        assert single['asset_ids']==expected
        assert single['image_reference_sources']==[
            {'type':'asset','asset_id':asset_id} for asset_id in expected
        ]
        assert single['reference_compiler']['source']=='shot.assetBindings'
        assert assets['manual']['id'] not in single['asset_ids']
        assert '视觉圣经一致性约束' in single['prompt']

        batch=c.post(
            f'/api/projects/{p["id"]}/run',
            json={'submission_id':'phase4-batch-accepted','node_ids':['phase4-image-node']},
        )
        assert batch.status_code==200,batch.text
        batch_job=c.get('/api/jobs/'+batch.json()['job_ids'][0]).json()['input']
        assert batch_job['asset_ids']==single['asset_ids']
        assert batch_job['image_reference_sources']==single['image_reference_sources']
        assert batch_job['reference_compiler']['bindings']==single['reference_compiler']['bindings']
        assert batch_job['prompt']==single['prompt']
        for job_id in [accepted.json()['id'],*batch.json()['job_ids']]:
            c.post('/api/jobs/'+job_id+'/cancel')
    finally:
        pass

def test_asset_library_semantic_categories(authenticated):
    import io
    from PIL import Image
    c=authenticated;p=project(c)
    stream=io.BytesIO();Image.new('RGB',(24,24),'#334455').save(stream,format='PNG')
    uploaded=c.post(f'/api/projects/{p["id"]}/assets?category=character',files={'file':('hero.png',stream.getvalue(),'image/png')})
    assert uploaded.status_code==200,uploaded.text
    asset=uploaded.json();assert asset['kind']=='image' and asset['category']=='character' and asset['source']=='uploaded'
    assert [a['id'] for a in c.get(f'/api/projects/{p["id"]}/assets?category=character&kind=image').json()]==[asset['id']]
    changed=c.patch(f'/api/projects/{p["id"]}/assets/{asset["id"]}',json={'category':'scene'})
    assert changed.status_code==200 and changed.json()['category']=='scene'
    assert c.get(f'/api/projects/{p["id"]}/assets?category=character').json()==[]
    assert c.patch(f'/api/projects/{p["id"]}/assets/{asset["id"]}',json={'category':'bad'}).status_code==400
    with s.db() as db:
        columns={row['column_name'] for row in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='assets'"
        )}
        indexes={row['indexname'] for row in db.execute(
            "SELECT indexname FROM pg_indexes WHERE schemaname=current_schema() AND tablename='assets'"
        )}
    assert {'category','source'}<=columns
    assert 'assets_project_category_created' in indexes

def test_cross_origin_and_secret_masking(authenticated):
    c=authenticated
    assert c.post('/api/projects',json={'name':'bad'},headers={'Origin':'https://other.example'}).status_code==403
    publish_test_model(c,'cloud',api_key='do-not-expose')
    public=c.get('/api/settings')
    assert 'do-not-expose' not in public.text and 'providers' not in public.json()
    private=c.get('/api/admin/model-providers').json()['providers']
    assert next(item for item in private if item['id']=='test-provider-cloud')['api_key_set'] is True
    assert c.put('/api/settings',json={'providers':[]}).status_code==410

def test_volcengine_ark_unified_settings_and_connection(authenticated,monkeypatch):
    import httpx
    c=authenticated
    public_test_dns(monkeypatch)
    calls=[]
    mock_egress(monkeypatch,lambda request: calls.append(request.method) or (_ for _ in ()).throw(AssertionError('must not call upstream')))
    for kind in ('text','image','video'):
        caps={} if kind=='text' else {'image_reference':True,'max_references':10 if kind=='image' else 1}
        if kind=='video':caps['end_frame']=True
        publish_test_model(c,'ark-'+kind,kind=kind,provider_type='volcengine_ark',capabilities=caps,api_key='ark-secret')
    public=c.get('/api/settings')
    assert 'ark-secret' not in public.text and 'models.example.test' not in public.text
    rows={item['id']:item for item in public.json()['models']}
    assert rows['ark-image']['capabilities']['image_reference'] is True
    assert rows['ark-image']['capabilities']['max_references']==10
    assert rows['ark-video']['capabilities']=={'image_reference':True,'max_references':1,'end_frame':True}
    private=next(item for item in c.get('/api/admin/model-providers').json()['providers'] if item['id']=='test-provider-ark-video')
    kept=c.put('/api/admin/model-providers/'+private['id'],json={
        'revision':private['revision'],'name':private['name'],'enabled':True,'config':private['config']})
    assert kept.status_code==200,kept.text
    assert kept.json()['credential_version_id']==private['credential_version_id']
    p=project(c)
    import io
    from PIL import Image
    stream=io.BytesIO();Image.new('RGB',(32,24),'#445566').save(stream,format='PNG')
    reference=c.post('/api/projects/'+p['id']+'/assets',files={'file':('ark-reference.png',stream.getvalue(),'image/png')}).json()
    for nid,kind in [('ark-image-reference','image'),('ark-video-reference','video'),
                     ('ark-video-transition','video'),('ark-video-tail-only','video'),
                     ('ark-video-many-references','video'),('ark-image','image'),('ark-video','video')]:
        target=c.post('/api/projects/'+p['id']+'/objects',json={'kind':'node',
            'content':{'node':{'id':nid,'type':'media','data':{'kind':kind}}}})
        assert target.status_code==201,target.text
    accepted=c.post('/api/projects/'+p['id']+'/jobs',json={
        'node_id':'ark-image-reference','kind':'image','submission_id':'ark-image-reference-job',
        'input':{'model_id':'ark-image','prompt':'参考图一的人物生成新场景','asset_ids':[reference['id']],'allow_cloud':True},
    })
    assert accepted.status_code==200,accepted.text
    accepted_video=c.post('/api/projects/'+p['id']+'/jobs',json={
        'node_id':'ark-video-reference','kind':'video','submission_id':'ark-video-reference-job',
        'input':{'model_id':'ark-video','prompt':'让人物走动','asset_ids':[reference['id']],'allow_cloud':True},
    })
    assert accepted_video.status_code==200,accepted_video.text
    accepted_transition=c.post('/api/projects/'+p['id']+'/jobs',json={
        'node_id':'ark-video-transition','kind':'video','submission_id':'ark-video-transition-job',
        'input':{'model_id':'ark-video','prompt':'从首帧连续运动到尾帧','asset_ids':[reference['id']],
                 'end_asset_id':reference['id'],'allow_cloud':True},
    })
    assert accepted_transition.status_code==200,accepted_transition.text
    rejected_tail_only=c.post('/api/projects/'+p['id']+'/jobs',json={
        'node_id':'ark-video-tail-only','kind':'video','submission_id':'ark-video-tail-only-job',
        'input':{'model_id':'ark-video','prompt':'移动到尾帧','end_asset_id':reference['id'],'allow_cloud':True},
    })
    assert rejected_tail_only.status_code==400 and '缺少首帧' in rejected_tail_only.text
    rejected_video=c.post('/api/projects/'+p['id']+'/jobs',json={
        'node_id':'ark-video-many-references','kind':'video','submission_id':'ark-video-many-references-job',
        'input':{'model_id':'ark-video','prompt':'让人物走动','asset_ids':[reference['id'],reference['id']],'allow_cloud':True},
    })
    assert rejected_video.status_code==400 and '数量超限' in rejected_video.text
    c.post('/api/jobs/'+accepted.json()['id']+'/cancel')
    c.post('/api/jobs/'+accepted_video.json()['id']+'/cancel')
    c.post('/api/jobs/'+accepted_transition.json()['id']+'/cancel')
    cloud_without_extra_authorization=c.post('/api/projects/'+p['id']+'/jobs',json={
        'node_id':'ark-image','kind':'image','submission_id':'ark-cloud-gate',
        'input':{'model_id':'ark-image','prompt':'一只猫'},
    })
    assert cloud_without_extra_authorization.status_code==200,cloud_without_extra_authorization.text
    c.post('/api/jobs/'+cloud_without_extra_authorization.json()['id']+'/cancel')
    queued=c.post('/api/projects/'+p['id']+'/jobs',json={
        'node_id':'ark-video','kind':'video','submission_id':'ark-cancel-cost-warning',
        'input':{'model_id':'ark-video','prompt':'一只猫走过窗前','allow_cloud':True},
    }).json()
    with s.db() as db:
        db.execute('UPDATE jobs SET provider_job_id=%s WHERE id=%s',('remote-ark-task',queued['id']))
    monkeypatch.setattr('backend.providers.volcengine_ark.cancel',lambda job,provider:False)
    cancelled=c.post('/api/jobs/'+queued['id']+'/cancel').json()
    assert cancelled['status']=='cancelled'
    assert cancelled['phase']=='本地已取消；供应商可能继续生成并产生费用'
    checked=c.post('/api/admin/model-providers/test-provider-ark-video/check')
    assert checked.status_code==200,checked.text
    assert checked.json()['status']=='unverified'
    for suffix in ('verify','test'):
        assert c.post('/api/providers/ark/'+suffix).status_code==410
    assert c.get('/api/providers/ark/models').status_code==410
    assert calls==[]


def test_hc_atom_unified_settings_and_connection(authenticated,monkeypatch):
    c=authenticated
    public_test_dns(monkeypatch)
    for kind in ('text','image','video'):
        publish_test_model(c,'hc-'+kind,kind=kind,provider_type='hc_atom')
    public=c.get('/api/models')
    assert CANARY not in public.text and 'models.example.test' not in public.text
    assert {row['kind'] for row in public.json()['models'] if row['id'].startswith('hc-')}=={'text','image','video'}
    private=next(row for row in c.get('/api/admin/model-providers').json()['providers'] if row['id']=='test-provider-hc-video')
    assert private['api_key_set'] is True and 'api_key' not in private
    checked=c.post('/api/admin/model-providers/'+private['id']+'/check')
    assert checked.status_code==200 and checked.json()['generation_verified'] is False
    assert c.post('/api/providers/hc/verify').status_code==410
    assert c.get('/api/providers/hc/models?kind=video').status_code==410


def test_ark_cancel_rereads_handle_attached_after_initial_snapshot(authenticated,monkeypatch):
    c=authenticated;p=project(c)
    now=time.time();jid='ark-cancel-reverse-race'
    provider={'id':'ark','type':'volcengine_ark','url':'https://ark.example.test','model':'test'}
    with s.db() as db:
        db.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                   (jid,jid,p['id'],'video-node','video','running',s.dumps({'provider':'ark','allow_cloud':True,'prompt':'test'}),now,now))
        bind_adapter_job(db,jid,'video',provider,{'prompt':'test'})
    original_job_update=s.job_update
    seen=[]
    def racing_job_update(job_id,**fields):
        if job_id==jid and fields.get('status')=='cancelled':
            s.attach_provider_job_id(jid,'task-attached-during-cancel')
        return original_job_update(job_id,**fields)
    monkeypatch.setattr(s,'job_update',racing_job_update)
    monkeypatch.setattr('backend.providers.volcengine_ark.cancel',lambda job,provider:seen.append(job['provider_job_id']) or True)
    cancelled=c.post('/api/jobs/'+jid+'/cancel')
    assert cancelled.status_code==200,cancelled.text
    assert seen==['task-attached-during-cancel']
    assert cancelled.json()['phase']=='已取消本地等待，并已请求供应商取消远端任务'

def test_revision_conflict_and_restore(authenticated):
    c=authenticated;p=project(c)
    doc=p['document'];doc['brief']='中文故事，严格保存。'
    payload={'expected_revision':p['revision'],'patch':{'brief':doc['brief']}}
    assert c.patch('/api/projects/'+p['id']+'/metadata',json=payload).json()['revision']==2
    assert c.patch('/api/projects/'+p['id']+'/metadata',json=payload).status_code==409
    assert c.get('/api/projects/'+p['id']).json()['document']['brief']==doc['brief']
    revisions=c.get('/api/projects/'+p['id']+'/revisions').json()
    assert len(revisions)==1
    old=c.get('/api/projects/'+p['id']+'/revisions/'+revisions[0]['id']).json()
    assert old['document']['brief']==''


def test_editor_timeline_round_trips_through_project_persistence(authenticated,tmp_path):
    import subprocess
    from backend.media import ffmpeg_executable
    c=authenticated;p=project(c);doc=p['document']
    source=tmp_path/'timeline.mp4'
    made=subprocess.run([ffmpeg_executable(),'-v','error','-f','lavfi','-i',
        'color=c=blue:s=64x64:r=24:d=5','-c:v','libx264','-pix_fmt','yuv420p',str(source)],
        capture_output=True,timeout=30)
    assert made.returncode==0,made.stderr
    with source.open('rb') as stream:
        uploaded=c.post(f'/api/projects/{p["id"]}/assets',files={'file':('timeline.mp4',stream,'video/mp4')})
    assert uploaded.status_code==200,uploaded.text
    aid=uploaded.json()['id']
    timeline={
        'version':2,
        'tracks':[{'id':'v1','name':'V1','type':'video','elements':[{
            'id':'clip-1','type':'video','s':1.25,'e':4.5,
            'props':{'src':f'/api/assets/{aid}/file','srcAssetId':aid,'time':.5,'volume':.7,'playbackRate':1.25,'opacity':.8,'mediaFilter':'cinematic','transition':{'toElementId':'clip-2','kind':'crossfade','duration':.4}},
            'metadata':{'assetId':aid,'mvc':{'fade':{'videoIn':.2,'videoOut':.4,'audioIn':.1,'audioOut':.3},'volumeKeyframes':[{'time':0,'value':.5},{'time':3.25,'value':1}]}},
            'frame':{'x':20,'y':30,'size':[640,360],'rotation':5},
        }]}],
        'assets':{aid:{'id':aid,'type':'video','url':f'/api/assets/{aid}/file'}},
    }
    row=next(row for row in c.get(f'/api/projects/{p["id"]}/objects').json() if row['kind']=='timeline')
    lease=c.post(f'/api/projects/{p["id"]}/objects/{row["id"]}/lease',json={
        'action':'acquire','assignment_epoch':row['assignment_epoch']})
    assert lease.status_code==200,lease.text
    saved=c.patch(f'/api/projects/{p["id"]}/objects/{row["id"]}',json={
        **object_version(row),'lease_token':lease.json()['token'],'lease_epoch':lease.json()['lease_epoch'],
        'content':{'timeline':timeline}})
    assert saved.status_code==200,saved.text
    restored=c.get('/api/projects/'+p['id']).json()['document']['editor']
    assert restored=={'version':1,'timeline':timeline}

def test_blank_project_name_uses_default(authenticated):
    c=authenticated
    item=c.post('/api/projects',json={'name':''}).json()
    assert item['name']=='未命名短片'
    saved=c.patch('/api/projects/'+item['id']+'/metadata',json={'expected_revision':item['revision'],'patch':{'name':'   '}})
    assert saved.status_code==200
    assert c.get('/api/projects/'+item['id']).json()['name']=='未命名短片'

def test_projects_and_assets_move_to_trash_and_restore(authenticated):
    import io
    from PIL import Image
    c=authenticated
    occupied=project(c)
    created=c.post('/api/projects/'+occupied['id']+'/objects',json={'kind':'node',
        'content':{'node':{'id':'n1','type':'media','data':{'kind':'text'}}}})
    assert created.status_code==201,created.text
    deleted=c.delete('/api/projects/'+occupied['id'])
    assert deleted.status_code==200 and deleted.json()=={'deleted':occupied['id'],'soft':True}
    assert c.get('/api/projects/'+occupied['id']).status_code==404
    assert occupied['id'] not in [item['id'] for item in c.get('/api/projects').json()]
    assert occupied['id'] in [item['id'] for item in c.get('/api/trash').json()['projects']]
    assert c.post(f'/api/trash/project/{occupied["id"]}/restore').status_code==200
    assert c.get('/api/projects/'+occupied['id']).status_code==200
    retained=c.get('/api/projects/'+occupied['id']+'/objects/'+created.json()['id']).json()
    assert retained['content']==created.json()['content']
    assert retained['assignment_epoch']>created.json()['assignment_epoch']

    stream=io.BytesIO();Image.new('RGB',(8,8),'#223344').save(stream,format='PNG')
    asset=c.post(f'/api/projects/{occupied["id"]}/assets',files={'file':('trash.png',stream.getvalue(),'image/png')}).json()
    assert c.delete(f'/api/projects/{occupied["id"]}/assets/{asset["id"]}').json()=={'deleted':asset['id'],'soft':True}
    assert asset['id'] not in [item['id'] for item in c.get(f'/api/projects/{occupied["id"]}/assets').json()]
    assert c.get(f'/api/assets/{asset["id"]}/file').status_code==404
    assert asset['id'] in [item['id'] for item in c.get('/api/trash').json()['assets']]
    assert c.post(f'/api/trash/asset/{asset["id"]}/restore').status_code==200
    assert c.get(f'/api/assets/{asset["id"]}/file').status_code==200

def test_cloud_submission_needs_no_extra_authorization_and_freezes_provider(authenticated):
    c=authenticated;p=project(c)
    create_node(c,p['id'],'n1')
    payload={'node_id':'n1','kind':'text','submission_id':'stable-submission-001','input':{'model_id':'cloud','prompt':'编写短片'}}
    first=c.post('/api/projects/'+p['id']+'/jobs',json=payload).json()
    second=c.post('/api/projects/'+p['id']+'/jobs',json=payload).json()
    assert first['id']==second['id']
    assert len(c.get('/api/projects/'+p['id']+'/jobs').json())==1
    assert 'do-not-expose' not in str(first)
    with s.db() as db:
        frozen=db.execute('SELECT provider FROM job_private WHERE job_id=%s',(first['id'],)).fetchone()['provider']
    assert json.loads(frozen)=={}
    with s.db() as db:
        from backend import platform_models
        assert platform_models.load_job_provider(db,first['id'])['api_key']=='do-not-expose'

def test_missing_or_removed_local_provider_fails_before_any_upstream_request(authenticated,monkeypatch):
    import httpx
    c=authenticated;p=project(c)
    create_node(c,p['id'],'missing-provider')
    create_node(c,p['id'],'legacy-local')
    previous=s.get_setting('providers',[])
    s.set_setting('providers',[])
    calls=[]
    monkeypatch.setattr(httpx,'Client',lambda *args,**kwargs:calls.append((args,kwargs)))
    missing=c.post('/api/projects/'+p['id']+'/jobs',json={
        'node_id':'missing-provider','kind':'text','submission_id':'missing-provider-001',
        'input':{'prompt':'must not leave this process'},
    })
    legacy=c.post('/api/projects/'+p['id']+'/jobs',json={
        'node_id':'legacy-local','kind':'text','submission_id':'legacy-local-001',
        'input':{'provider':'local','prompt':'must not leave this process'},
    })
    s.set_setting('providers',previous)
    assert missing.status_code==400 and legacy.status_code==400
    assert '不会自动回退' in missing.json()['detail']
    assert calls==[]

def test_cancel_wins_late_completion(authenticated):
    c=authenticated;p=project(c)
    create_node(c,p['id'],'n')
    old=s.get_setting('providers',[])
    provider=publish_test_model(c,'cancel-test-api')
    job=c.post('/api/projects/'+p['id']+'/jobs',json={'node_id':'n','kind':'text','submission_id':'cancel-submission-001','input':{'model_id':provider['id'],'prompt':'你好'}}).json()
    s.set_setting('providers',old)
    s.job_update(job['id'],status='running')
    assert c.post('/api/jobs/'+job['id']+'/cancel').json()['status']=='cancelled'
    assert s.job_update(job['id'],status='succeeded',result={'text':'late'}) is False
    assert c.get('/api/jobs/'+job['id']).json()['status']=='cancelled'

def test_media_upload_range_and_project_boundary(authenticated):
    from PIL import Image
    import io
    c=authenticated;p=project(c);other=project(c)
    stream=io.BytesIO();Image.new('RGB',(64,32),'#223344').save(stream,format='PNG')
    asset=c.post('/api/projects/'+p['id']+'/assets',files={'file':('sample.png',stream.getvalue(),'image/png')}).json()
    assert asset['metadata']['width']==64
    result=c.get(asset['url'],headers={'Range':'bytes=0-9'})
    assert result.status_code==206
    assert len(result.content)==10
    request={'node_id':'n','kind':'image','submission_id':'wrong-project-ref-001','input':{'prompt':'reference','asset_ids':[asset['id']]}}
    publish_test_model(c,'boundary-image',kind='image',provider_type='volcengine_ark',capabilities={'image_reference':True,'max_references':10})
    create_node(c,other['id'],'n',kind='image')
    request['input']['model_id']='boundary-image'
    rejected=c.post('/api/projects/'+other['id']+'/jobs',json=request)
    assert rejected.status_code==400 and '其他 Production' in rejected.text
    assert c.post('/api/projects/'+p['id']+'/assets',files={'file':('bad.html',b'<script>x</script>','text/html')}).status_code==400

def test_provider_asset_url_is_signed_expiring_and_needs_no_session(authenticated,monkeypatch):
    public_test_dns(monkeypatch)
    from backend.provider_assets import public_asset_url
    import io
    from PIL import Image
    c=authenticated;p=project(c)
    stream=io.BytesIO();Image.new('RGB',(16,16),'#334455').save(stream,format='PNG')
    asset=c.post('/api/projects/'+p['id']+'/assets',files={'file':('provider.png',stream.getvalue(),'image/png')}).json()
    url=public_asset_url({'public_base_url':'https://studio.example'},asset['id'])
    path='/' + url.split('/',3)[3]
    with TestClient(app) as anonymous:
        assert anonymous.get(path).content == stream.getvalue()
        assert anonymous.get(path.replace('signature=','signature=bad')).status_code == 403

def test_restart_marks_ambiguous_running_job(authenticated):
    c=authenticated;p=project(c)
    create_node(c,p['id'],'n')
    provider=publish_test_model(c,'restart-test-api')
    job=c.post('/api/projects/'+p['id']+'/jobs',json={'node_id':'n','kind':'text','submission_id':'interrupted-job-001','input':{'model_id':provider['id'],'prompt':'test'}}).json()
    with s.db() as db:
        db.execute("UPDATE jobs SET status='cancelled' WHERE status='queued' AND id!=%s",(job['id'],))
    s.job_update(job['id'],status='running',provider_job_id='upstream-paid-id')
    worker=Worker();worker.start();worker.stop()
    result=c.get('/api/jobs/'+job['id']).json()
    assert result['status']=='interrupted'
    assert result['provider_job_id']=='upstream-paid-id'

def test_graph_cycle_rejected_without_submitting(authenticated):
    c=authenticated;p=project(c);doc=p['document']
    doc['nodes']=[{'id':n,'data':{'kind':'text','prompt':'test'}} for n in ('a','b')]
    doc['edges']=[{'id':'ab','source':'a','target':'b'},{'id':'ba','source':'b','target':'a'}]
    for node in doc['nodes']:create_node(c,p['id'],node['id'],**node['data'])
    set_edges(c,p['id'],doc['edges'])
    response=c.post('/api/projects/'+p['id']+'/run',json={'submission_id':'graph-cycle-test'})
    assert response.status_code==400
    assert c.get('/api/projects/'+p['id']+'/jobs').json()==[]

def test_graph_storyboard_defaults_to_two_pass_film_bible(authenticated):
    c=authenticated;p=project(c);doc=p['document']
    publish_test_model(c,'local-test')
    doc['nodes']=[{'id':'plan','data':{'kind':'storyboard','model_id':'local-test','prompt':'雨夜故事'}}]
    for node in doc['nodes']:create_node(c,p['id'],node['id'],**node['data'])
    result=c.post('/api/projects/'+p['id']+'/run',json={'submission_id':'film-bible-graph-001'})
    assert result.status_code==200,result.text
    jobs=c.get('/api/projects/'+p['id']+'/jobs').json()
    assert jobs[0]['input']['film_bible'] is True
    assert jobs[0]['input']['target_duration']==15
    assert jobs[0]['input']['schema_version']=='film-bible-storyboard/v1'
    assert [stage['id'] for stage in jobs[0]['input']['prompt_stages']]==['visual_bible','bound_storyboard']
    assert all(stage['system_prompt'] for stage in jobs[0]['input']['prompt_stages'])
    assert all(stage['response_schema'] for stage in jobs[0]['input']['prompt_stages'])
    with s.db() as db:
        db.execute("UPDATE jobs SET status='cancelled' WHERE project_id=%s",(p['id'],))

def test_graph_scheduler_consumes_upstream_text(authenticated,monkeypatch):
    c=authenticated;p=project(c);doc=p['document']
    publish_test_model(c,'local-test')
    doc['nodes']=[{'id':n,'data':{'kind':'text','model_id':'local-test','prompt':prompt}} for n,prompt in [('a','故事'),('b','分镜')]]
    doc['edges']=[{'id':'ab','source':'a','target':'b'}]
    for node in doc['nodes']:create_node(c,p['id'],node['id'],**node['data'])
    set_edges(c,p['id'],doc['edges'])
    result=c.post('/api/projects/'+p['id']+'/run',json={'submission_id':'graph-run-test-001'}).json()
    assert result['count']==2
    with s.db() as db:
        db.execute("UPDATE jobs SET status='cancelled' WHERE status='queued' AND project_id!=%s",(p['id'],))
    queued=c.get('/api/projects/'+p['id']+'/jobs').json()
    assert all(job['input']['target_duration']==15 for job in queued)
    received=[]
    def text(self,job,provider):
        received.append(job['input']['prompt'])
        return {'text':'上游已确认的故事'}
    monkeypatch.setattr(Worker,'text',text)
    worker=Worker();worker.start()
    try:
        for _ in range(100):
            jobs=c.get('/api/projects/'+p['id']+'/jobs').json()
            if all(j['status']=='succeeded' for j in jobs):break
            time.sleep(.03)
        assert all(j['status']=='succeeded' for j in jobs),jobs
        assert received[0]=='故事'
        assert '上游已确认的故事' in received[1]
    finally:worker.stop()

@pytest.mark.parametrize('provider_type',['maestro','comfy','video_api'])
def test_resume_only_queries_frozen_upstream(authenticated,monkeypatch,provider_type):
    import httpx,io
    from PIL import Image
    from backend import worker as module
    c=authenticated;p=project(c)
    provider={'id':'recover-'+provider_type,'type':provider_type,'url':'http://engine.test','local':True,'model':'test','workflow':{}}
    kind='video' if provider_type=='video_api' else 'image'
    target=c.post('/api/projects/'+p['id']+'/objects',json={'kind':'node',
        'content':{'node':{'id':'n','type':'media','data':{'kind':kind,'prompt':'test'}}}})
    assert target.status_code==201,target.text
    publish_test_model(c,provider['id'],kind=kind,provider_type=provider_type,url=provider['url'],options={'workflow':{}})
    job=c.post('/api/projects/'+p['id']+'/jobs',json={'node_id':'n','kind':kind,'submission_id':'resume-'+provider_type,'input':{'model_id':provider['id'],'prompt':'test'}}).json()
    s.job_update(job['id'],status='interrupted',provider_job_id='original-handle')
    # Editing the service after interruption must not change the polling target.
    publish_test_model(c,provider['id'],kind=kind,provider_type=provider_type,url='http://changed.invalid',options={'workflow':{}})
    assert c.post('/api/jobs/'+job['id']+'/resume').json()['status']=='queued'
    assert c.post('/api/jobs/'+job['id']+'/resume').json()['id']==job['id']
    job=c.get('/api/jobs/'+job['id']).json()
    calls=[];picture=io.BytesIO();Image.new('RGB',(16,16),'red').save(picture,format='PNG')
    def handle(request):
        calls.append((request.method,str(request.url)))
        assert request.method=='GET','Recovery must never submit or upload again'
        assert request.url.host=='engine.test'
        path=request.url.path
        if path=='/api/v1/status/original-handle':return httpx.Response(200,json={'status':'completed','output_files':['recovered.png']})
        if path=='/history/original-handle':return httpx.Response(200,json={'original-handle':{'outputs':{'1':{'images':[{'filename':'recovered.png'}]}}}})
        if path=='/videos/original-handle':return httpx.Response(200,json={'status':'completed','video_url':'https://result.test/video.mp4'})
        if path in ('/api/v1/uploads/recovered.png','/view'):return httpx.Response(200,content=picture.getvalue())
        raise AssertionError(path)
    original=httpx.Client
    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(module,'download_result',lambda *args:{'id':'returned-video','kind':'video'})
    worker=Worker()
    class NoWait:
        def wait(self,seconds):return False
        def is_set(self):return False
    worker.halt=NoWait()
    assert worker.execute(job)['assets']
    assert calls

def test_resume_missing_handle_requeues_frozen_input_and_cancelled_rejected(authenticated):
    c=authenticated;p=project(c)
    target=c.post('/api/projects/'+p['id']+'/objects',json={'kind':'node',
        'content':{'node':{'id':'n','type':'media','data':{'kind':'text','prompt':'test'}}}})
    assert target.status_code==201,target.text
    provider=publish_test_model(c,'resume-test-api')
    job=c.post('/api/projects/'+p['id']+'/jobs',json={'node_id':'n','kind':'text','submission_id':'resume-no-handle','input':{'model_id':provider['id'],'prompt':'test'}}).json()
    s.job_update(job['id'],status='interrupted',error='restart',phase='old phase',progress=42,telemetry={'old':True})
    resumed=c.post('/api/jobs/'+job['id']+'/resume').json()
    assert resumed['status']=='queued'
    assert resumed['id']==job['id']
    assert resumed['input']==job['input']
    assert resumed['phase']=='使用已保存的输入重新排队'
    assert resumed['error'] is None and resumed['progress'] is None and resumed['telemetry'] is None
    assert c.post('/api/jobs/'+job['id']+'/cancel').json()['status']=='cancelled'
    assert c.post('/api/jobs/'+job['id']+'/resume').status_code==409

def test_replicate_resume_uses_frozen_service_and_cancel_requests_remote_stop(authenticated,monkeypatch):
    from backend import replicate_api
    c=authenticated;p=project(c)
    target=c.post('/api/projects/'+p['id']+'/objects',json={'kind':'node',
        'content':{'node':{'id':'n','type':'media','data':{'kind':'video','prompt':'镜头推进'}}}})
    assert target.status_code==201,target.text
    provider={'id':'replicate-video','name':'Replicate','type':'replicate','kind':'video','url':'https://api.replicate.com/v1','model':'bytedance/seedance-1-pro','api_key':'test-key','local':False}
    publish_test_model(c,provider['id'],kind='video',provider_type='replicate',url=provider['url'],upstream_model=provider['model'])
    job=c.post('/api/projects/'+p['id']+'/jobs',json={'node_id':'n','kind':'video','submission_id':'replicate-resume-001','input':{'model_id':'replicate-video','allow_cloud':True,'prompt':'镜头推进'}}).json()
    s.job_update(job['id'],status='interrupted',provider_job_id='prediction-original')
    publish_test_model(c,provider['id'],kind='video',provider_type='replicate',url='https://changed.invalid',upstream_model=provider['model'])
    assert c.post('/api/jobs/'+job['id']+'/resume').json()['status']=='queued'
    calls=[]
    monkeypatch.setattr(replicate_api,'cancel',lambda remote_job,frozen:calls.append((remote_job['provider_job_id'],frozen['url'])))
    assert c.post('/api/jobs/'+job['id']+'/cancel').json()['status']=='cancelled'
    assert calls==[('prediction-original','https://api.replicate.com/v1')]

    c.post('/api/jobs/'+job['id']+'/cancel')
    assert c.post('/api/jobs/'+job['id']+'/resume').status_code==409

def test_personal_prompt_library_versions_and_conflicts(authenticated):
    c=authenticated
    value=c.get('/api/prompt-library').json()
    body={'revision':value['revision'],'name':'我的电影分镜','kind':'storyboard','content':'只使用中文，保留角色。'}
    first=c.put('/api/admin/prompt-templates/test-template',json=body)
    assert first.status_code==200
    assert first.json()['templates'][0]['version']==1
    assert c.put('/api/admin/prompt-templates/test-template',json=body).status_code==409
    body.update(revision=first.json()['revision'],content='每镜一个动作。')
    second=c.put('/api/admin/prompt-templates/test-template',json=body).json()
    assert second['templates'][0]['history'][0]['content']=='只使用中文，保留角色。'
    assert c.get('/api/prompt-library').json()==second

def test_batch_late_validation_failure_rolls_back_all_jobs(authenticated):
    c=authenticated;p=project(c);doc=p['document']
    publish_test_model(c,'text-only')
    doc['nodes']=[{'id':'a','data':{'kind':'text','prompt':'story','model_id':'text-only'}},{'id':'b','data':{'kind':'image','prompt':'frame','model_id':'text-only'}}]
    doc['edges']=[{'id':'ab','source':'a','target':'b'}]
    for node in doc['nodes']:create_node(c,p['id'],node['id'],**node['data'])
    set_edges(c,p['id'],doc['edges'])
    result=c.post('/api/projects/'+p['id']+'/run',json={'submission_id':'atomic-batch-validation'})
    assert result.status_code==400
    assert c.get('/api/projects/'+p['id']+'/jobs').json()==[]
