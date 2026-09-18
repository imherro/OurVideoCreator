"""Five-role storyboard -> artist preparation -> generator adoption, no paid calls."""
from backend import store as s
from tests.test_business_roles import enable,change_roles,assign
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits,url,version
from tests.test_p5_storyboard_candidates import storyboard,objects
from tests.test_p5_object_candidates import candidate


def setup(team):
    enable(team);change_roles(team,team['aid'],['generator']);change_roles(team,team['bid'],['artist'])
    assign(team,team['aid'],confirm_special=True)
    with s.db() as c:c.execute("UPDATE episode_scripts SET body='已批准测试剧本',status='approved' WHERE project_id=%s",(team['pid'],))
    return '/api/productions/'+team['production']+'/workflow/asset-candidates'


def test_artist_prepares_new_cards_without_generator_asset_permissions(team,monkeypatch):
    path=setup(team);root,job,result=storyboard(team,monkeypatch)
    preview=team['a'].get(candidate(team,job)).json()
    assert preview['impact']['needs_artist'] and not preview['can_adopt']
    denied=team['a'].post(candidate(team,job)+'/adopt',json=version(root))
    assert denied.status_code==409,denied.text
    assert not [row for row in objects(team) if row['kind']=='visual_card']
    listing=team['b'].get(path).json();assert listing['can_prepare'] and len(listing['items'])==1
    body={'fingerprint':listing['items'][0]['fingerprint']}
    assert team['a'].post(path+'/'+job['id'],json=body).status_code==403
    assert team['admin'].post(path+'/'+job['id'],json=body).status_code==403
    response=team['b'].post(path+'/'+job['id'],json=body)
    assert response.status_code==200,response.text
    cards=[row for row in objects(team) if row['kind']=='visual_card']
    assert len(cards)==len(result['filmBible']['visual']['cards'])
    assert all(row['assignee_id']==team['bid'] and row['status']=='in_progress' for row in cards)
    assert team['b'].get(path).json()['items']==[]
    assert team['b'].post(path+'/'+job['id'],json=body).status_code==409
    preview=team['a'].get(candidate(team,job)).json()
    assert not preview['impact']['needs_artist'] and preview['can_adopt']
    response=team['a'].post(candidate(team,job)+'/adopt',json=version(root))
    assert response.status_code==200,response.text
    shots=[row for row in objects(team) if row['kind']=='shot']
    assert len(shots)==1 and shots[0]['assignee_id']==team['aid']
    assert [row for row in objects(team) if row['kind']=='visual_card']==cards
    assert not team['a'].get(path).json()['items']


def test_new_artist_confirmation_rejects_prior_staffing_fingerprint(team,monkeypatch):
    path=setup(team);_,job,_=storyboard(team,monkeypatch)
    original=team['b'].get(path).json()['items'][0]
    change_roles(team,team['bid'],[])
    assert team['b'].post(path+'/'+job['id'],json={'fingerprint':original['fingerprint']}).status_code==403
    change_roles(team,team['bid'],['artist'])
    assert team['b'].post(path+'/'+job['id'],json={'fingerprint':original['fingerprint']}).status_code==409
    assert not [row for row in objects(team) if row['kind']=='visual_card']
