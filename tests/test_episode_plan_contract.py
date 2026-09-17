import copy
import json
import pytest
from backend.episode_plans import validate_result,continuity_context
from backend import store as s
from tests.test_adaptation import adaptation_client,setup_production,save_and_approve
from tests.test_adaptation_scope import approved_script
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits
from tests.test_p5_object_candidates import voice_card

VALUE={'episodeNo':3,'sourceChapterRefs':['chapter-a'],'logline':'承接','coreConflict':'冲突',
       'emotionalBeat':'紧张','hook':'新事件','cliffhanger':'悬念','paywallRole':'none','targetDuration':60}


def test_result_becomes_draft_without_mutating_candidate():
    value=copy.deepcopy(VALUE);value['sourceChapterRefs']*=2
    result=validate_result(value,3,60,['chapter-a'])
    assert result['status']=='draft' and result['sourceChapterRefs']==['chapter-a']
    assert 'status' not in value and len(value['sourceChapterRefs'])==2


@pytest.mark.parametrize('patch',[
    {'episodeNo':True},{'episodeNo':3.0},{'episodeNo':4},{'targetDuration':True},
    {'targetDuration':float('nan')},{'targetDuration':float('inf')},{'targetDuration':61},
    {'sourceChapterRefs':[]},{'sourceChapterRefs':['other']},{'sourceChapterRefs':[' ']},
    {'logline':' '},{'status':'approved'},{'paywallRole':[]},
])
def test_result_rejects_off_contract_values(patch):
    with pytest.raises(ValueError):validate_result({**VALUE,**patch},3,60,['chapter-a'])


def test_continuity_reads_real_saved_scripts_and_does_not_write(adaptation_client):
    client=adaptation_client
    production,episode,chapter,bundle=setup_production(client,count=3)
    save_and_approve(client,production,bundle)
    root='/api/productions/'+production['id']
    first=approved_script(client,root,1,chapter)
    second=approved_script(client,root,2,chapter)
    with s.db() as c:
        c.execute('UPDATE episode_scripts SET body=%s WHERE project_id=%s',('A'*1700+'END',first['project_id']))
        c.execute('UPDATE episode_scripts SET body=%s WHERE project_id=%s',('B'*2100+'IMMEDIATE',second['project_id']))
    with s.db() as c:
        before=[dict(r) for r in c.execute('SELECT * FROM episode_scripts ORDER BY project_id')]
        context=continuity_context(c,episode['id'],3)
        after=[dict(r) for r in c.execute('SELECT * FROM episode_scripts ORDER BY project_id')]
    assert before==after
    assert context['immediatePreviousAvailable']
    older,immediate=context['previousEpisodes']
    assert older['script']['endingExcerpt'].endswith('END') and len(older['script']['endingExcerpt'])==1500
    assert older['script']['excerptTruncated']
    assert immediate['script']['body']=='B'*2100+'IMMEDIATE'
    assert immediate['script']['assignment_epoch']==second['assignment_epoch']
    with s.db() as c:
        c.execute("UPDATE episode_scripts SET status='stale' WHERE project_id=%s",(second['project_id'],))
        changed=continuity_context(c,episode['id'],3)
    assert not changed['immediatePreviousAvailable']
    assert changed['previousEpisodes'][1]['evidence']=='planning_only'


def test_continuity_uses_locked_canonical_visual_versions(team):
    card=voice_card(team,'unused-model')
    with s.db() as c:
        document=json.loads(c.execute('SELECT document FROM projects WHERE id=%s',(team['pid'],)).fetchone()['document'])
        document['filmBible']={'visual':{'cards':{'fake':{'id':'fake','name':'obsolete'}}}}
        c.execute('UPDATE projects SET document=%s WHERE id=%s',(json.dumps(document),team['pid']))
        content=card['content'];content['versions']['hero-v1']['status']='locked'
        content['versions']['hero-v1']['spec']['description']='Canonical locked appearance'
        c.execute('UPDATE collaboration_objects SET content=%s WHERE id=%s',(json.dumps(content),card['id']))
        result=continuity_context(c,team['pid'],2)
        assert len(result['lockedAssets'])==1
        assert result['lockedAssets'][0]['id']=='hero'
        assert result['lockedAssets'][0]['spec']['description']=='Canonical locked appearance'
        content['card']['status']='deprecated'
        c.execute('UPDATE collaboration_objects SET content=%s WHERE id=%s',(json.dumps(content),card['id']))
        assert continuity_context(c,team['pid'],2)['lockedAssets']==[]
