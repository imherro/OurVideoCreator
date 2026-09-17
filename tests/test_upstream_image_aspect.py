"""Canonical episode aspect within published platform rules, no paid calls."""
import pytest
import json
import httpx

from backend import model_validation as v, platform_models, store as s
from backend.worker import Worker
from tests.platform_model_helpers import admin, create_provider, publish_test_model
from tests.test_p4_r1_regressions import fake, model, ordinary_editor
from tests.test_p4_submission_execution import project, submit


def definition(rules, defaults):
    return {'capabilities': {}, 'rules': rules, 'defaults': defaults}


@pytest.mark.parametrize('ratio,size', [('16:9','2048x1152'), ('9:16','1152x2048'), ('4:3','2048x1536'),
                                     ('3:4','1536x2048'), ('21:9','2048x864'), ('1:1','2048x2048')])
def test_unlinked_image_uses_episode_frame_not_square_default(ratio, size):
    spec = definition({'size': {'type': 'string', 'enum': ['1024x1024', size]}}, {'size': '1024x1024'})
    result = v.shot_parameters(spec, {'size': '1024x1024'}, 'image', {'ratio': ratio, 'shots': []}, 'independent')
    assert result['size'] == size


@pytest.mark.parametrize('tier_rule', [{'type':'string','enum':['2k']}, {'type':'string'}])
def test_quality_resolution_does_not_hide_declared_pixel_size(tier_rule):
    spec = definition({'size': {'type': 'string', 'enum': ['1024x1024','2048x1152']},
                       'resolution': tier_rule}, {'size':'1024x1024','resolution':'2k'})
    document = {'ratio':'16:9', 'shots':[{'imageNode':'image'}]}
    assert v.shot_parameters(spec, {}, 'image', document, 'image') == {'size':'2048x1152','resolution':'2k'}


def test_mismatched_published_size_is_rejected_not_silently_rendered_square():
    spec = definition({'size': {'type':'string','enum':['1024x1024']}}, {'size':'1024x1024'})
    with pytest.raises(ValueError, match='画幅'):
        v.shot_parameters(spec, {}, 'image', {'ratio':'9:16','shots':[{'imageNode':'image'}]}, 'image')


def test_valid_published_alternative_size_is_not_expanded_beyond_admin_limits():
    spec = definition({'size': {'type':'string','enum':['1280x720']}}, {'size':'1280x720'})
    assert v.shot_parameters(spec, {}, 'image', {'ratio':'16:9'}, 'image')['size'] == '1280x720'


def test_canonical_panorama_purpose_keeps_2_to_1():
    spec = definition({'size':{'type':'string','enum':['1024x512','1152x2048']}}, {'size':'1152x2048'})
    document = {'ratio':'9:16','nodes':[{'id':'pano','data':{'image_purpose':'panorama'}}]}
    assert v.shot_parameters(spec, {}, 'image', document, 'pano')['size']=='1024x512'
    assert v.shot_parameters(spec, {}, 'image', document, 'ordinary')['size']=='1152x2048'


def test_image_aspect_does_not_create_unpublished_controls_or_bypass_rejections():
    spec = definition({'ratio':{'type':'string','enum':['1:1','9:16']}}, {'ratio':'1:1'})
    assert v.shot_parameters(spec, {}, 'image', {'ratio':'9:16'}, 'image')=={'ratio':'9:16'}
    assert v.shot_parameters(definition({}, {}), {}, 'image', {'ratio':'9:16'}, 'image')=={}
    with pytest.raises(ValueError, match='字段无效'):
        v.shot_parameters(spec, {'size':'1152x2048'}, 'image', {'ratio':'9:16'}, 'image')
    with pytest.raises(ValueError, match='画幅'):
        v.shot_parameters(spec, {}, 'image', {'ratio':'16:9'}, 'image')


@pytest.mark.parametrize('provider_type', ['openai', 'hc_atom'])
def test_api_freeze_and_actual_wire_follow_canonical_portrait_frame(admin, fake, provider_type):
    base, events = fake
    provider = create_provider(admin, config={'type':provider_type, 'url':base + ('/v1' if provider_type=='openai' else ''),
        'options':{'parameters':{'image':{'size':'1024x1024'}}}})
    published = model(admin, provider, kind='image', upstream='test-image',
        rules={'size':{'type':'string','enum':['1024x1024','1152x2048']}}, defaults={'size':'1024x1024'}).json()
    p = project(admin)
    changed = admin.patch(f"/api/projects/{p['id']}/metadata", json={'expected_revision':p['revision'],'patch':{'ratio':'9:16'}})
    assert changed.status_code == 200, changed.text
    with ordinary_editor(admin, p) as client:
        response = submit(client, p['id'], published['id'], kind='image', input={
            'model_id':published['id'],'prompt':'portrait','image_purpose':'panorama','parameters':{'size':'1024x1024'}})
        assert response.status_code == 200, response.text
        job = response.json()
        with s.db() as c:
            frozen = platform_models.load_job_provider(c, job['id'])['job_parameters']
        assert frozen['size'] == '1152x2048'
        assert s.job_update(job['id'], status='running')
        assert Worker().execute(job)['assets']
        assert events[-1]['size'] == frozen['size']
        # The old receipt must keep its original rules after a platform update.
        revised = admin.put('/api/admin/models/' + published['id'], json={
            'revision':published['revision'],'kind':'image','provider_id':provider['id'],'published':True,'enabled':True,
            'definition':{**published['definition'],'rules':{'size':{'type':'string','enum':['1024x1024']}},
                          'defaults':{'size':'1024x1024'}}})
        assert revised.status_code == 200, revised.text
        replay = client.post(f"/api/projects/{p['id']}/jobs", json={
            'node_id':job['node_id'],'kind':'image','submission_id':job['submission_id'],
            'input':{'model_id':published['id'],'prompt':'portrait','image_purpose':'panorama','parameters':{'size':'1024x1024'}}})
        assert replay.status_code == 200 and replay.json()['id'] == job['id']
        before = client.get(f"/api/projects/{p['id']}/jobs").json()
        rejected = submit(client, p['id'], published['id'], kind='image', input={
            'model_id':published['id'],'prompt':'portrait','parameters':{'size':'1024x1024'}})
        assert rejected.status_code == 400 and '画幅' in rejected.text
        assert client.get(f"/api/projects/{p['id']}/jobs").json() == before
        assert len(events) == 1


def test_runninghub_uses_frozen_pixels_without_overwriting_quality_tier(admin, monkeypatch):
    from tests.egress_helpers import mock_egress
    from tests.test_runninghub import NoWait
    from backend.providers import common
    published = publish_test_model(admin, s.uid('rh-aspect-'), kind='image', provider_type='runninghub',
        upstream_model='seedream-v5-pro', url='https://www.runninghub.ai',
        rules={'size':{'type':'string','enum':['1024x1024','1152x2048']},'resolution':{'type':'string','enum':['2k']}},
        defaults={'size':'1024x1024','resolution':'2k'},
        options={'parameters':{'image':{'size':'1024x1024','resolution':'2k'}}})
    p = project(admin)
    assert admin.patch(f"/api/projects/{p['id']}/metadata", json={
        'expected_revision':p['revision'],'patch':{'ratio':'9:16'}}).status_code == 200
    requests=[]
    def handle(request):
        if request.url.path.endswith('/text-to-image'):
            requests.append(json.loads(request.read()))
            return httpx.Response(200,json={'code':0,'taskId':'test-aspect'})
        assert request.url.path == '/openapi/v2/query'
        return httpx.Response(200,json={'code':0,'status':'SUCCESS','results':[{'url':'https://media.example/result.png'}]})
    mock_egress(monkeypatch,handle)
    monkeypatch.setattr(common,'download_result',lambda *a,**k:{'id':'wire-only','kind':'image'})
    with ordinary_editor(admin,p) as client:
        response=submit(client,p['id'],published['id'],kind='image',input={
            'model_id':published['id'],'prompt':'portrait','parameters':{'size':'1024x1024','resolution':'2k'}})
        assert response.status_code == 200,response.text
        job=response.json();assert s.job_update(job['id'],status='running')
        worker=Worker();worker.halt=NoWait()
        assert worker.execute(job)['assets']
    assert len(requests)==1
    assert (requests[0]['width'],requests[0]['height'],requests[0]['resolution'])==(1152,2048,'2k')
