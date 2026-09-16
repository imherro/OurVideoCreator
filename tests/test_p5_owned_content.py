"""Existing relational sources: HTTP ownership, real PG waiters, no legacy import."""
from concurrent.futures import ThreadPoolExecutor
import pytest

from backend import store as s
from backend.adaptation import SCRIPT_FIELDS
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits
from tests.test_p3_r2_interleavings import wait_for_db_waiters


def base(team):return '/api/productions/'+team['production']


def create_chapter(team,actor=None):
    actor=actor or team['a']
    source=actor.post(base(team)+'/sources',json={'title':'owned source','type':'manual','metadata':{}})
    assert source.status_code==200,source.text
    chapter=actor.post(base(team)+'/sources/'+source.json()['id']+'/chapters',json={'title':'one','content':'retained text'})
    assert chapter.status_code==200,chapter.text
    return chapter.json()


def endpoint(team,kind,row):
    return base(team)+'/owned-content/'+kind+'/'+(row['project_id'] if kind=='script' else row['id'])


def assign(team,kind,row,actor_id):
    result=team['admin'].post(endpoint(team,kind,row)+'/assign',json={
        'expected_revision':row['revision'],'assignment_epoch':row['assignment_epoch'],'assignee_id':actor_id})
    assert result.status_code==200,result.text
    return result.json()


def save(team,kind,row,actor=None,**patch):
    keys=SCRIPT_FIELDS if kind=='script' else {'title','content'}
    payload={key:row[key] for key in keys}
    payload.update(revision=row['revision'],assignment_epoch=row['assignment_epoch'])
    payload.update(patch)
    path=base(team)+('/episode-scripts/1' if kind=='script' else '/chapters/'+row['id'])
    return (actor or team['a']).put(path,json=payload)


def content(team,kind):
    if kind=='chapter':return create_chapter(team)
    result=team['admin'].get(base(team)+'/episode-scripts/1')
    assert result.status_code==200,result.text
    return assign(team,kind,result.json(),team['aid'])


@pytest.mark.parametrize('kind',['chapter','script'])
def test_owner_only_and_aba_rejects_even_current_revision(team,kind):
    row=content(team,kind)
    assert row['assignee_id']==team['aid']
    for actor in (team['b'],team['admin'],team['viewer']):
        assert save(team,kind,row,actor).status_code==403
    before=team['a'].get(endpoint(team,kind,row)+'/history').json()
    assert save(team,kind,row,assignment_epoch=0).status_code in {409,422}
    assert team['a'].get(endpoint(team,kind,row)+'/history').json()==before
    switched=assign(team,kind,row,team['bid'])
    returned=assign(team,kind,switched,team['aid'])
    assert save(team,kind,row,revision=returned['revision']).status_code==409
    assert save(team,kind,returned).status_code==200
    latest=team['a'].get(endpoint(team,kind,row)+'/history').json()[0]['snapshot']
    assert latest['updated_by']==team['aid']


@pytest.mark.parametrize('kind',['chapter','script'])
def test_same_version_wait_chain_one_success_one_conflict(team,kind):
    row=content(team,kind)
    table,key=('episode_scripts','project_id') if kind=='script' else ('source_chapters','id')
    target=row[key]
    with ThreadPoolExecutor(max_workers=2) as pool:
        with s.db() as c:
            c.execute(f'SELECT revision FROM {table} WHERE {key}=%s FOR UPDATE',(target,))
            pending=[pool.submit(save,team,kind,row,None,title=label) for label in ('first','second')]
            waits=wait_for_db_waiters(2)
            assert all(item['blockers'] for item in waits)
            print('owned-content PostgreSQL wait trace',kind,waits)
        responses=[item.result(15) for item in pending]
    assert sorted(item.status_code for item in responses)==[200,409]
    history=team['a'].get(endpoint(team,kind,row)+'/history').json()
    assert history[0]['revision']==row['revision']+1


def test_chapter_review_exact_version_and_viewer_comments(team):
    row=create_chapter(team)
    path=endpoint(team,'chapter',row)
    def review(actor,current,action):
        return actor.post(path+'/review',json={'expected_revision':current['revision'],
            'assignment_epoch':current['assignment_epoch'],'action':action})
    comment=team['viewer'].post(path+'/comments',json={'body':'viewer comment'})
    assert comment.status_code==201,comment.text
    assert len(team['viewer'].get(path+'/comments').json())==1
    assert team['viewer'].post(path+'/comments',json={'body':'hidden edit','content':'bypass'}).status_code==422
    submitted=review(team['a'],row,'submit')
    assert submitted.status_code==200,submitted.text
    assert review(team['admin'],row,'approve').status_code==409
    assert review(team['b'],submitted.json(),'approve').status_code==403
    approved=review(team['admin'],submitted.json(),'approve')
    assert approved.status_code==200,approved.text
    edited=save(team,'chapter',approved.json(),content='new draft')
    assert edited.status_code==200,edited.text
    assert edited.json()['status']=='in_progress'


@pytest.mark.parametrize('kind',['chapter','script'])
def test_member_revocation_preserves_relational_content(team,kind):
    row=content(team,kind)
    response=team['admin'].put(base(team)+'/members/'+team['aid'],json={'role':'viewer'})
    assert response.status_code==200,response.text
    latest=team['admin'].get(endpoint(team,kind,row)+'/history').json()[0]['snapshot']
    assert latest['assignee_id'] is None
    assert latest['assignment_epoch']==row['assignment_epoch']+1
    field='body' if kind=='script' else 'content'
    assert latest[field]==row[field]
    assert save(team,kind,row).status_code==403


def test_import_self_owned_and_cross_production_hidden(team):
    result=team['b'].post(base(team)+'/sources/import',json={'title':'import','type':'txt','metadata':{},'content':'第一章\nOriginal'})
    assert result.status_code==200,result.text
    rows=team['a'].get(base(team)+'/chapters',params={'source_id':result.json()['id']}).json()
    assert rows and all(row['assignee_id']==team['bid'] and row['created_by']==team['bid'] for row in rows)
    other=team['admin'].post('/api/projects',json={'name':'other owned work'}).json()
    target='/api/productions/'+other['production_id']+'/owned-content/chapter/'+rows[0]['id']
    assert team['admin'].get(target+'/history').status_code==404


def test_adaptation_get_readonly_and_editor_cannot_write(team):
    path=base(team)+'/adaptation'
    row=team['viewer'].get(path).json()
    assert team['viewer'].get(path).json()==row
    payload={key:row[key] for key in ('revision','adaptationPlan','episodePlans','monetizationPlan')}
    assert team['a'].put(path,json=payload).status_code==403
    assert team['admin'].put(path,json=payload).status_code==200


def test_source_and_batch_delete_require_explicit_takeover_and_all_versions(team):
    first=create_chapter(team)
    second=team['b'].post(base(team)+'/sources/'+first['source_id']+'/chapters',json={'title':'two','content':'keep second'}).json()
    source_path=base(team)+'/sources/'+first['source_id']
    def versions(rows):return {r['id']:{'revision':r['revision'],'assignment_epoch':r['assignment_epoch']} for r in rows}
    assert team['admin'].delete(source_path).status_code==422
    assert team['admin'].request('DELETE',source_path,json={'versions':versions([first,second])}).status_code==403
    manager=team['admin'].get('/api/auth/status').json()['user']['id']
    first=assign(team,'chapter',first,manager)
    failed=team['admin'].post(base(team)+'/chapters/trash',json={'chapter_ids':[first['id'],second['id']],
        'versions':versions([first,second])})
    assert failed.status_code==403,failed.text
    live=team['a'].get(base(team)+'/chapters').json()
    assert {first['id'],second['id']} <= {r['id'] for r in live}
    second=assign(team,'chapter',second,manager)
    stale=versions([first,second]);stale[second['id']]['revision']-=1
    assert team['admin'].post(base(team)+'/chapters/trash',json={'chapter_ids':[first['id'],second['id']],
        'versions':stale}).status_code==409
    assert len(team['a'].get(base(team)+'/chapters').json())==2
    deleted=team['admin'].request('DELETE',source_path,json={'versions':versions([first,second])})
    assert deleted.status_code==200,deleted.text
    assert team['a'].get(base(team)+'/chapters').json()==[]


@pytest.mark.parametrize('kind',['chapter','script'])
def test_restore_new_revision_not_historical_ownership(team,kind):
    original=content(team,kind)
    field='body' if kind=='script' else 'content'
    edited=save(team,kind,original,**{field:'changed text'})
    assert edited.status_code==200,edited.text
    row=edited.json();path=endpoint(team,kind,row)
    assigned=assign(team,kind,row,team['bid'])
    payload={'expected_revision':assigned['revision'],'assignment_epoch':assigned['assignment_epoch'],
             'revision':original['revision']}
    assert team['a'].post(path+'/restore',json=payload).status_code==403
    assert team['admin'].post(path+'/restore',json=payload).status_code==403
    restored=team['b'].post(path+'/restore',json=payload)
    assert restored.status_code==200,restored.text
    latest=restored.json()
    assert latest['revision']==assigned['revision']+1
    assert latest[field]==original[field]
    assert latest['assignee_id']==team['bid'] and latest['assignment_epoch']==assigned['assignment_epoch']
    assert team['viewer'].get(path).json()[field]==original[field]
    assert team['b'].post(path+'/restore',json=payload).status_code==409


@pytest.mark.parametrize('operation',['save','create'])
def test_tombstone_committed_during_lock_wait_is_rechecked(team,operation):
    chapter=create_chapter(team)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with s.db() as c:
            if operation=='save':
                c.execute('SELECT id FROM source_chapters WHERE id=%s FOR UPDATE',(chapter['id'],))
                pending=pool.submit(save,team,'chapter',chapter,None,content='must not write')
                kind,target='chapter',chapter['id']
            else:
                c.execute('SELECT id FROM source_documents WHERE id=%s FOR UPDATE',(chapter['source_id'],))
                pending=pool.submit(team['a'].post,base(team)+'/sources/'+chapter['source_id']+'/chapters',
                    json={'title':'must not create','content':'hidden parent'})
                kind,target='source',chapter['source_id']
            waits=wait_for_db_waiters(1)
            assert waits[0]['blockers']
            print('owned-content deletion wait trace',operation,waits)
            c.execute('INSERT INTO deleted_items(kind,item_id,project_id,deleted_at) VALUES(%s,%s,%s,1)',
                      (kind,target,team['production']))
        response=pending.result(15)
    assert response.status_code==404,response.text
    with s.db() as c:
        assert c.execute('SELECT revision FROM source_chapters WHERE id=%s',(chapter['id'],)).fetchone()['revision']==1
        assert c.execute('SELECT COUNT(*) n FROM source_chapters WHERE source_id=%s',(chapter['source_id'],)).fetchone()['n']==1
        assert c.execute('SELECT COUNT(*) n FROM source_chapter_revisions WHERE chapter_id=%s',(chapter['id'],)).fetchone()['n']==0
