from concurrent.futures import ThreadPoolExecutor
from backend import store as s
from tests.test_p5_owned_content import create_chapter, base
from tests.test_p5_object_transactions import team, admin, clients, clear_auth_rate_limits
from tests.test_p3_r2_interleavings import wait_for_db_waiters


def test_append_permissions_ownership_and_recycle_slots(team):
    first=create_chapter(team)
    root=base(team);path=root+f'/sources/{first["source_id"]}/chapters/import'
    body={'title':'补充','content':'第二章\n新正文'}
    assert team['viewer'].post(path,json=body).status_code==403
    result=team['b'].post(path,json=body)
    assert result.status_code==200,result.text
    chapters=team['a'].get(root+'/chapters').json()
    assert chapters[0]==first
    second=chapters[1]
    assert second['assignee_id']==team['bid'] and second['created_by']==team['bid']
    # Explicit manager takeover is still required to delete another editor's chapter.
    from tests.test_p5_owned_content import assign
    manager=team['admin'].get('/api/auth/status').json()['user']['id']
    second=assign(team,'chapter',second,manager)
    response=team['admin'].request('DELETE',root+'/chapters/'+second['id'],json={
        'revision':second['revision'],'assignment_epoch':second['assignment_epoch']})
    assert response.status_code==200,response.text
    assert team['a'].post(path,json=body).status_code==200
    assert team['admin'].post('/api/trash/chapter/'+second['id']+'/restore').status_code==200
    assert [c['chapter_no'] for c in team['a'].get(root+'/chapters').json()]==[1,2,3]


def test_append_serializes_with_manual_chapter_creation(team):
    first=create_chapter(team);root=base(team);path=root+f'/sources/{first["source_id"]}/chapters'
    with ThreadPoolExecutor(max_workers=2) as pool:
        with s.db() as c:
            c.execute('SELECT id FROM source_documents WHERE id=%s FOR UPDATE',(first['source_id'],))
            append=pool.submit(team['a'].post,path+'/import',json={'title':'追加','content':'第二章\n正文'})
            manual=pool.submit(team['b'].post,path,json={'title':'手工','content':'正文'})
            assert len(wait_for_db_waiters(2))>=2
        results=[append.result(15),manual.result(15)]
    assert [r.status_code for r in results]==[200,200]
    assert [c['chapter_no'] for c in team['a'].get(root+'/chapters').json()]==[1,2,3]


def test_append_rejects_trashed_source(team):
    root=base(team)
    source=team['admin'].post(root+'/sources',json={'title':'空原著'}).json()
    path=root+'/sources/'+source['id']
    assert team['admin'].request('DELETE',path,json={'versions':{}}).status_code==200
    assert team['admin'].post(path+'/chapters/import',json={'title':'追加','content':'正文'}).status_code==404
    assert team['admin'].get(root+'/chapters').json()==[]
