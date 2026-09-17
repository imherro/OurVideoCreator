import json
import pytest
from backend import store as s
from backend.direct_scripts import narrative_context, context_fingerprint, assist_prompt
from tests.test_direct_script_manual import admin, clients, clear_auth_rate_limits, checked, endpoint, save
from tests.test_p5_object_transactions import team
from tests.test_p5_object_candidates import voice_card


def test_context_reads_canonical_current_and_latest_three_nonstale_episodes(admin):
    first = checked(admin.post('/api/projects', json={'name':'Direct context', 'creation_mode':'direct'}))
    projects = [first]
    for number in range(2, 7):
        projects.append(checked(admin.post('/api/productions/'+first['production_id']+'/episodes',
                                         json={'title':f'EP {number}'})))
    for number, project in enumerate(projects, 1):
        row = checked(admin.get(endpoint(project)))
        checked(save(admin, project, row, title=f'Canonical {number}', body=f'prefix-{number}'+str(number)*8100))
    with s.db() as c:
        # An actual obsolete script is excluded, leaving EP2, EP3 and EP5.
        c.execute("UPDATE episode_scripts SET status='stale' WHERE project_id=%s", (projects[3]['id'],))
        before = narrative_context(c, projects[-1]['id'])
        assert [episode['episodeNo'] for episode in before['previousEpisodes']] == [2, 3, 5]
        assert all(len(episode['body']) == 8000 for episode in before['previousEpisodes'])
        assert before['currentScript']['title'] == 'Canonical 6'
        assert before['currentScript']['body'].startswith('prefix-6')
        assert context_fingerprint(before) == context_fingerprint(narrative_context(c, projects[-1]['id']))
        c.execute('UPDATE episode_scripts SET body=%s,revision=revision+1 WHERE project_id=%s',
                  ('changed previous episode', projects[4]['id']))
        after = narrative_context(c, projects[-1]['id'])
        assert context_fingerprint(before) != context_fingerprint(after)
        assert before['previousEpisodes'][-1]['body'] == '5'*8000
    prompt = assist_prompt(after, '续写本集，不要改写前集')
    assert 'Canonical 6' in prompt and 'changed previous episode' in prompt
    assert admin.get('/api/projects/'+projects[-1]['id']+'/jobs').json() == []


@pytest.mark.parametrize('instruction', ['', '   ', None, 'x'*24001])
def test_assist_prompt_rejects_missing_or_excessive_instruction(instruction):
    with pytest.raises(ValueError):
        assist_prompt({}, instruction)


def test_context_fingerprint_ignores_mapping_order_not_content():
    assert context_fingerprint({'a':1,'b':2}) == context_fingerprint({'b':2,'a':1})
    assert context_fingerprint({'a':1}) != context_fingerprint({'a':2})


def test_visual_summary_uses_collaboration_object_not_stale_document(team):
    card = voice_card(team, 'unused-model')
    with s.db() as c:
        project = c.execute('SELECT document FROM projects WHERE id=%s', (team['pid'],)).fetchone()
        document = json.loads(project['document'])
        document['filmBible'] = {'visual': {'cards': {'fake': {'name':'obsolete carrier'}}}}
        c.execute('UPDATE projects SET document=%s WHERE id=%s', (json.dumps(document), team['pid']))
        snapshot = narrative_context(c, team['pid'])
        assert snapshot['charactersAndScenes'] == [{'id':'hero','name':'Hero','kind':'character','description':'hero'}]
        content = card['content']
        content['versions']['hero-v1']['spec']['description'] = 'Changed canonical appearance'
        c.execute('UPDATE collaboration_objects SET content=%s WHERE id=%s', (json.dumps(content), card['id']))
        changed = narrative_context(c, team['pid'])
        assert changed['charactersAndScenes'][0]['description'] == 'Changed canonical appearance'
        assert context_fingerprint(snapshot) != context_fingerprint(changed)
        content['card']['status'] = 'deprecated'
        c.execute('UPDATE collaboration_objects SET content=%s WHERE id=%s', (json.dumps(content), card['id']))
        assert narrative_context(c, team['pid'])['charactersAndScenes'] == []
