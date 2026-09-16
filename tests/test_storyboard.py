import json,time
import httpx,pytest
from backend import store as s
from backend.worker import Worker
from backend.prompts import validate_shots

def board(duration):
    return {'title':'雨后','shots':[{'id':'1','duration':duration,'scene':'小巷','characters':'橘猫','action':'发现机器人','camera':'中景固定','audio':'雨滴声','image_prompt':'雨后小巷，橘猫与机器人','video_prompt':'橘猫缓缓转头'}]}

def test_duration_and_required_fields_are_checked():
    assert validate_shots(board(5),5)['shots'][0]['id']=='shot-001'
    with pytest.raises(ValueError,match='总时长'):validate_shots(board(5),10)
    missing=board(5);del missing['shots'][0]['camera']
    with pytest.raises(ValueError,match='camera'):validate_shots(missing)

@pytest.mark.parametrize('fixed',[True,False])
def test_repair_is_limited_to_one_additional_request(monkeypatch,fixed):
    s.init();pid=s.uid();jid=s.uid();now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'repair','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'n','storyboard','running','{}',now,now))
    job={'id':jid,'project_id':pid,'node_id':'n','kind':'storyboard','input':{'prompt':'写分镜','target_duration':10}}
    requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        content=json.dumps(board(10 if fixed and len(requests)==2 else 5),ensure_ascii=False)
        return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':content}}]})+'\n\ndata: [DONE]\n\n')
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(respond)))
    if fixed:
        result=Worker().text(job,{'url':'http://test/v1','local':True})
        assert result['repair_count']==1
        assert result['shots'][0]['duration']==10
    else:
        with pytest.raises(ValueError,match='修正后仍'):Worker().text(job,{'url':'http://test/v1','local':True})
    assert len(requests)==2
    assert '上次结果未通过校验' in requests[1]['messages'][1]['content']

def test_film_bible_storyboard_is_two_text_passes_with_deterministic_bindings(monkeypatch):
    s.init();pid=s.uid();jid=s.uid();now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'two-pass','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'n','storyboard','running','{}',now,now))
    visual={'cards':[
      {'key':'hero','kind':'character','name':'林岚','parent_key':'','description':'灰色风衣青年','attributes':[],'invariants':['灰色风衣']},
      {'key':'alley','kind':'scene','name':'雨巷','parent_key':'','description':'夜晚雨巷','attributes':[],'invariants':['蓝色霓虹灯']},
    ]}
    board={'title':'雨巷','shots':[{
      'duration':5,'scene':'雨巷','characters':'林岚','action':'向前走','emotion':'警觉','camera':'中景跟拍','audio':'雨声',
      'image_prompt':'林岚站在雨巷','video_prompt':'林岚向前走','character_keys':['hero'],'scene_key':'alley','prop_keys':[],
      'dialogues':[{'character_key':'hero','text':'雨还没有停。','emotion':'警觉'}],
    }]}
    payloads=[visual,board];requests=[]
    def respond(request):
        requests.append(request)
        content=json.dumps(payloads[len(requests)-1],ensure_ascii=False)
        return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':content}}]})+'\n\ndata: [DONE]\n\n')
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(respond)))
    job={'id':jid,'project_id':pid,'node_id':'n','kind':'storyboard','input':{
      'provider':'ark','model':'doubao','prompt':'雨夜里的青年','target_duration':5,'film_bible':True,
    }}
    result=Worker().text(job,{'url':'http://test/v1','structured':True,'api_key':'test'})
    assert len(requests)==2
    assert all(request.url.path.endswith('/chat/completions') for request in requests)
    bodies=[json.loads(request.content) for request in requests]
    assert bodies[0]['response_format']['json_schema']['schema']['properties'].get('cards')
    assert bodies[1]['response_format']['json_schema']['schema']['properties'].get('shots')
    assert result['repair_count']==0 and result['shots'][0]['uid'].startswith('shot-')
    binding=result['shots'][0]['assetBindings']['characters'][0]['versionId']
    assert binding in result['filmBible']['visual']['versions']

def test_non_structured_visual_output_gets_one_bounded_repair(monkeypatch):
    s.init();pid=s.uid();jid=s.uid();now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'visual-repair','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'n','storyboard','running','{}',now,now))
    malformed=[{'key':'hero','kind':'character','name':'林岚','parent_key':'','description':'灰色风衣','attributes':{},'invariants':'灰色风衣'}]
    valid_visual={'cards':[{'key':'hero','kind':'character','name':'林岚','parent_key':'','description':'灰色风衣','attributes':[],'invariants':['灰色风衣']}]}
    valid_board={'title':'短片','shots':[{'duration':5,'scene':'室内','characters':'林岚','action':'站立','emotion':'平静','camera':'中景','audio':'环境声','image_prompt':'林岚站立','video_prompt':'林岚呼吸','character_keys':['hero'],'scene_key':'','prop_keys':[],'dialogues':[]}]}
    payloads=[malformed,valid_visual,valid_board];requests=[]
    def respond(request):
        requests.append(json.loads(request.content));content=json.dumps(payloads[len(requests)-1],ensure_ascii=False)
        return httpx.Response(200,text='data: '+json.dumps({'choices':[{'delta':{'content':content}}]})+'\n\ndata: [DONE]\n\n')
    original=httpx.Client;monkeypatch.setattr(httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(respond)))
    job={'id':jid,'project_id':pid,'node_id':'n','kind':'storyboard','input':{'provider':'ark','model':'doubao','prompt':'短片','target_duration':5,'film_bible':True}}
    result=Worker().text(job,{'url':'http://test/v1','api_key':'test'})
    assert len(requests)==3 and result['visual_repair_count']==1 and result['storyboard_repair_count']==0
    assert '必须严格输出以下 JSON Schema' in requests[0]['messages'][1]['content']
    assert '上次视觉圣经未通过校验' in requests[1]['messages'][1]['content']
