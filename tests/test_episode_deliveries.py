"""Real PG delivery snapshots; media bytes are synthetic, no provider calls."""
from copy import deepcopy
import io
import json
import time
import zipfile

import pytest

from backend import store as s, business_roles as br
from tests.test_business_roles import enable,change_roles,actor,assign
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,url,save


def prepared(team):
    enable(team);change_roles(team,team['aid'],['generator']);change_roles(team,team['bid'],['editor'])
    assign(team,team['aid'],confirm_special=True)
    aid=s.uid('asset-');path=s.asset_path(aid,'.mp4');path.write_bytes(b'synthetic-selected-video')
    # A persisted synthetic media fixture: tests exercise packaging, not codecs.
    with s.db() as c:
        c.execute('''INSERT INTO assets(id,project_id,production_id,name,kind,mime,path,source,metadata,created,category)
            VALUES(%s,%s,%s,'selected.mp4','video','video/mp4',%s,'upload','{}',%s,'general')''',
            (aid,team['pid'],team['production'],path.name,time.time()))
        c.execute("UPDATE episode_scripts SET body='剧本正文',title='第一集',status='approved',revision=revision+1 WHERE project_id=%s",(team['pid'],))
    response=team['a'].post(url(team),json={'kind':'shot','content':{
        'shot':{'id':'01','uid':'stable-shot','videoNode':'selected-video','dialogues':[{'id':'d1','text':'你好','characterName':'小林'}]},
        'nodes':[{'id':'selected-video','type':'media','data':{'kind':'video','assetId':aid}}]}})
    assert response.status_code==201,response.text
    row=response.json()
    graph=next(row for row in team['a'].get(url(team)).json() if row['kind']=='graph')
    content=deepcopy(graph['content']);content['shotOrder']=['stable-shot'];content['nodeOrder']=['selected-video']
    response=save(team,graph,content);assert response.status_code==200,response.text
    return '/api/projects/'+team['pid']+'/deliveries',row,path


def confirm(team,path):
    preview=team['a'].get(path+'/preview')
    assert preview.status_code==200,preview.text
    assert preview.json()['issues']==[],preview.text
    return {'fingerprint':preview.json()['fingerprint']}


def test_fixed_selected_package_editor_download_and_idempotent_confirmation(team):
    path,row,media=prepared(team);body=confirm(team,path)
    assert team['b'].post(path,json=body).status_code==403
    assert team['admin'].post(path,json=body).status_code==403
    response=team['a'].post(path,json=body);assert response.status_code==201,response.text
    delivery=response.json();assert delivery['version']==1
    assert team['a'].post(path,json=body).json()['id']==delivery['id']
    result=team['b'].get(path+'/'+delivery['id']+'/download');assert result.status_code==200,result.text
    with zipfile.ZipFile(io.BytesIO(result.content)) as bundle:
        assert 'manifest.json' in bundle.namelist() and 'script.txt' in bundle.namelist()
        manifest=json.loads(bundle.read('manifest.json'))
        assert len(manifest['files'])==1
        assert bundle.read(manifest['files'][0]['filename'])==b'synthetic-selected-video'
        assert '你好' in bundle.read('dialogue.txt').decode()
        assert bundle.read('script.txt').decode().endswith('剧本正文')
    # Later editing and even external loss of source bytes must not change V1.
    content=deepcopy(row['content']);content['nodes'][0]['data']['stale']=True
    assert save(team,row,content).status_code==200
    media.write_bytes(b'changed-source-bytes')
    assert team['b'].get(path+'/'+delivery['id']+'/download').content==result.content
    assert team['a'].get(path+'/preview').json()['issues']
    assert team['a'].post(path,json=body).status_code==409


def test_changed_staffing_during_packaging_cannot_publish_and_editor_is_readonly(team,monkeypatch):
    from backend import episode_deliveries as delivery
    path,_,_=prepared(team);body=confirm(team,path)
    original=delivery.checksum
    def revoke(archive):
        change_roles(team,team['aid'],[])
        return original(archive)
    monkeypatch.setattr(delivery,'checksum',revoke)
    response=team['a'].post(path,json=body)
    assert response.status_code==403,response.text
    assert team['b'].get(path).json()==[]
    with s.db() as c:
        assert c.execute('SELECT count(*) n FROM episode_deliveries WHERE project_id=%s',(team['pid'],)).fetchone()['n']==0


def test_missing_and_tampered_archive_are_explicit_and_cross_episode_is_hidden(team):
    path,_,_=prepared(team);body=confirm(team,path)
    response=team['a'].post(path,json=body);assert response.status_code==201,response.text
    did=response.json()['id']
    other=team['admin'].post('/api/projects',json={'name':'another production','five_role_workflow':True}).json()
    assert team['admin'].get('/api/projects/'+other['id']+'/deliveries/'+did+'/download').status_code==404
    with s.db() as c:name=c.execute('SELECT archive_name FROM episode_deliveries WHERE id=%s',(did,)).fetchone()['archive_name']
    (s.DATA/'deliveries'/name).write_bytes(b'tampered-test-archive')
    failed=team['b'].get(path+'/'+did+'/download')
    assert failed.status_code==409 and '完整性' in failed.text


def test_new_delivery_is_append_only_and_revoked_member_cannot_download(team):
    path,row,_=prepared(team)
    first=team['a'].post(path,json=confirm(team,path)).json()
    content=deepcopy(row['content']);content['shot']['dialogues'][0]['text']='修改后的对白'
    assert save(team,row,content).status_code==200
    second=team['a'].post(path,json=confirm(team,path))
    assert second.status_code==201,second.text
    assert second.json()['version']==2 and second.json()['id']!=first['id']
    history=team['b'].get(path).json()
    assert [item['version'] for item in history]==[2,1]
    assert history[1]['manifest']['shots'][0]['dialogues'][0]['text']=='你好'
    # Role removal alone keeps content readable; membership removal does not.
    change_roles(team,team['bid'],[])
    assert team['b'].get(path+'/'+first['id']+'/download').status_code==200
    with s.db() as c:
        c.execute('DELETE FROM production_members WHERE production_id=%s AND user_id=%s',(team['production'],team['bid']))
    assert team['b'].get(path+'/'+first['id']+'/download').status_code in (403,404)


def test_missing_selected_media_lists_issue_and_prevents_publishing(team):
    path,_,media=prepared(team)
    media.rename(media.with_suffix('.preserved-fixture'))
    preview=team['a'].get(path+'/preview').json()
    assert any('文件丢失' in issue for issue in preview['issues'])
    response=team['a'].post(path,json={'fingerprint':preview['fingerprint']})
    assert response.status_code==409,response.text
    assert team['a'].get(path).json()==[]
