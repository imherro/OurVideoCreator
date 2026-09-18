from tests.test_episode_samples import clip,setup,upload
from tests.test_sample_reviews import send
from tests.test_business_roles import change_roles
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits


def tasklist(team,client):
    response=client.get('/api/productions/'+team['production']+'/workflow/tasks')
    assert response.status_code==200,response.text
    return response.json()['tasks']


def test_roles_get_actual_work_and_revocation_removes_it(team,clip):
    path,delivery=setup(team)
    generator=tasklist(team,team['a']);editor=tasklist(team,team['b'])
    assert {row['role'] for row in generator}=={'generator'}
    assert {row['role'] for row in editor}=={'editor'}
    assert editor[0]['stage']=='deliveries' and editor[0]['project_id']==team['pid']
    one=upload(team,path,delivery,clip).json()['id']
    assert tasklist(team,team['b'])[0]['stage']=='samples'
    producer=tasklist(team,team['admin'])
    assert any(row['stage']=='samples' and row['project_id']==team['pid'] for row in producer)
    assert send(team,path,one,'approve').status_code==201
    assert not any(row['stage']=='samples' for row in tasklist(team,team['admin']))
    assert '已批准' in tasklist(team,team['b'])[0]['next_step']
    change_roles(team,team['bid'],[])
    assert tasklist(team,team['b'])==[]


def test_multi_roles_merge_without_gaining_another_members_assignment(team):
    setup(team);change_roles(team,team['bid'],['editor','generator'])
    tasks=tasklist(team,team['b'])
    assert {row['role'] for row in tasks}=={'editor'}
    # A role alone does not claim the other person's episode work.
    assert all(row['stage']!='storyboard' for row in tasks)
