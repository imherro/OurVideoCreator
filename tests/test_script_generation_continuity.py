import copy
import json
import uuid

import pytest

from backend import store as s
from tests.test_adaptation import adaptation_client, setup_production, save_and_approve
from tests.test_adaptation_scope import approved_script
from tests.test_p5_relation_candidates import complete_without_network


GENERATED = {
    'title': '第二集', 'synopsis': '阿青循着密信继续追查',
    'body': '夜。阿青带着密信走进客栈。', 'estimatedDuration': 60,
    'characters': ['阿青'], 'scenes': ['客栈'], 'props': ['密信'],
}


def prepare(client):
    production, first, chapter, bundle = setup_production(client, count=2)
    root = '/api/productions/' + production['id']
    save_and_approve(client, production, bundle)
    previous = approved_script(client, root, 1, chapter)
    second = client.post(root + '/episodes', json={'title': '第二集'}).json()
    return root, production, first, second, chapter, previous


def submit(client, root):
    return client.post(root + '/script-generations', json={
        'episode_nos': [2], 'model_id': 'p1-test-openai',
        'submission_id': 'continuity-' + uuid.uuid4().hex,
    })


def candidate_path(project_id, job_id):
    return f'/api/projects/{project_id}/candidates/{job_id}'


def expected(script, **extra):
    return {'expected_revision': script['revision'],
            'assignment_epoch': script['assignment_epoch'], **extra}


@pytest.mark.parametrize('change', ['previous_script', 'film_bible'])
def test_formal_script_candidate_freezes_continuity_until_adoption(adaptation_client, monkeypatch, change):
    client = adaptation_client
    root, production, _, second, _, previous = prepare(client)
    response = submit(client, root)
    assert response.status_code == 200, response.text
    job = response.json()['jobs'][0]
    continuity = job['input']['continuity_context']
    assert job['input']['schema_version'] == 'episode-script/v2'
    assert continuity['immediatePreviousAvailable'] is True
    assert continuity['previousEpisodes'][-1]['script']['body'] == previous['body']
    assert previous['body'] in job['input']['prompt']
    assert '承接前集结尾' in job['input']['system_prompt']
    complete_without_network(monkeypatch, job, GENERATED)

    before = client.get(root + '/episode-scripts/2').json()
    with s.db() as connection:
        if change == 'previous_script':
            connection.execute('''UPDATE episode_scripts SET body=%s,revision=revision+1
                WHERE project_id=%s''', ('前集出现了新的结尾。', previous['project_id']))
        else:
            row = connection.execute('SELECT shared_context FROM productions WHERE id=%s',
                                     (production['id'],)).fetchone()
            context = json.loads(row['shared_context'])
            context['filmBible']['continuity']['weather'] = '暴雨'
            connection.execute('UPDATE productions SET shared_context=%s,revision=revision+1 WHERE id=%s',
                               (s.dumps(context), production['id']))
    adopted = client.post(candidate_path(second['id'], job['id']) + '/adopt',
                          json=expected(before, accept_stale=True))
    assert adopted.status_code == 409, adopted.text
    assert client.get(root + '/episode-scripts/2').json() == before
    assert 'adopted' not in client.get(candidate_path(second['id'], job['id'])).json()['job']['collaboration']


def test_generic_script_job_rebuilds_server_continuity_and_prompt(adaptation_client):
    client = adaptation_client
    root, _, _, second, _, previous = prepare(client)
    submitted = submit(client, root)
    assert submitted.status_code == 200, submitted.text
    original = submitted.json()['jobs'][0]
    assert client.post('/api/jobs/' + original['id'] + '/cancel').status_code == 200
    forged = copy.deepcopy(original['input'])
    forged.update(prompt='FORGED PROMPT', system_prompt='FORGED SYSTEM',
                  response_schema={}, continuity_context={'forged': True})
    response = client.post('/api/projects/' + second['id'] + '/jobs', json={
        'node_id': original['node_id'], 'kind': 'text',
        'submission_id': 'generic-' + uuid.uuid4().hex, 'input': forged,
    })
    assert response.status_code == 200, response.text
    normalized = response.json()
    assert 'FORGED' not in normalized['input']['prompt']
    assert 'FORGED' not in normalized['input']['system_prompt']
    assert normalized['input']['continuity_context']['previousEpisodes'][-1]['script']['body'] == previous['body']
    assert normalized['input']['response_schema']['required']
    assert client.post('/api/jobs/' + normalized['id'] + '/cancel').status_code == 200


def test_formal_script_submission_rejects_locked_prior_and_accepted_target(adaptation_client):
    client = adaptation_client
    root, _, _, second, _, previous = prepare(client)
    with s.db() as connection:
        connection.execute('SELECT project_id FROM episode_scripts WHERE project_id=%s FOR UPDATE',
                           (previous['project_id'],)).fetchone()
        locked = submit(client, root)
        assert locked.status_code == 409 and '正在保存' in locked.text, locked.text

    created = client.post('/api/projects/' + second['id'] + '/objects', json={
        'kind': 'node', 'content': {'node': {
            'id': 'accepted-video', 'type': 'video', 'data': {'kind': 'video'},
        }},
    })
    assert created.status_code == 201, created.text
    node = created.json()
    content = node['content']
    content['node']['data']['assetId'] = 'isolated-accepted-video'
    with s.db() as connection:
        connection.execute('UPDATE collaboration_objects SET content=%s WHERE id=%s',
                           (s.dumps(content), node['id']))
    protected = submit(client, root)
    assert protected.status_code == 409 and '采纳视频' in protected.text, protected.text
