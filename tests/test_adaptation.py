import copy
import json

import pytest
from fastapi.testclient import TestClient

from backend import store as s
from backend.app import app
from backend.worker import Worker
from backend.adaptation import validate_adaptation_bundle


@pytest.fixture(scope="module")
def adaptation_client():
    with TestClient(app) as client:
        status = client.get("/api/auth/status").json()
        endpoint = "/api/auth/login" if status["configured"] else "/api/auth/setup"
        response = client.post(endpoint, json={"password": "integration-test-only"})
        assert response.status_code == 200, response.text
        response = client.put("/api/settings", json={"providers": [{
            "id": "p1-test-openai", "name": "P1 test gateway", "type": "openai",
            "kind": "text", "url": "http://127.0.0.1:1/v1", "local": False,
        }]})
        assert response.status_code == 200, response.text
        yield client


def setup_production(client, count=60):
    production = client.post("/api/productions", json={"name": "Phase 3 连载剧"}).json()
    episode = client.post(
        f'/api/productions/{production["id"]}/episodes', json={"title": "第一集"}
    ).json()
    source = client.post(
        f'/api/productions/{production["id"]}/sources',
        json={"title": "原著", "type": "manual", "metadata": {}},
    ).json()
    chapter = client.post(
        f'/api/productions/{production["id"]}/sources/{source["id"]}/chapters',
        json={"title": "第一章", "content": "阿青发现父亲留下的密信，并决定进城追查。"},
    ).json()
    adaptation = client.get(f'/api/productions/{production["id"]}/adaptation').json()
    adaptation["adaptationPlan"] = {
        "status": "draft",
        "format": {"episodeCount": count, "targetDuration": 60, "ratio": "9:16", "platform": "红果短剧"},
        "storyCore": {"premise": "追查密信", "theme": "信任", "protagonist": "阿青", "goal": "找到真相", "stakes": "家族安危"},
        "storyArc": {"opening": "发现密信", "development": "追查线索", "turningPoint": "盟友背叛", "climax": "当面对质", "ending": "真相揭晓"},
        "adaptationStrategy": {"audience": "短剧用户", "tone": "悬疑", "changes": "压缩支线", "constraints": "保持主线"},
        "sourceEventIds": [],
    }
    adaptation["episodePlans"] = [{
        "episodeNo": number, "sourceChapterRefs": [chapter["id"]],
        "logline": f"阿青追查第 {number} 条线索", "coreConflict": "真相与信任冲突",
        "emotionalBeat": "疑虑加深", "hook": f"第 {number} 集开场疑点",
        "cliffhanger": f"第 {number} 集结尾出现新证据", "paywallRole": "none",
        "targetDuration": 60, "status": "draft",
    } for number in range(1, count + 1)]
    adaptation["episodePlans"][min(2, count - 1)]["paywallRole"] = "conversion"
    adaptation["monetizationPlan"] = {
        "mode": "free_then_paid", "freeEpisodes": min(3, count), "firstPaywallEpisode": min(4, count + 1),
        "beats": [{"episodeNo": min(3, count), "type": "pre_paywall_hook", "setup": "盟友失踪",
            "cliffhanger": "密信另有夹层", "expectedEmotion": "迫切", "rationale": "推动追更"}],
    }
    return production, episode, chapter, adaptation


def save_and_approve(client, production, adaptation):
    saved = client.put(
        f'/api/productions/{production["id"]}/adaptation',
        json={key: adaptation[key] for key in ("revision", "adaptationPlan", "episodePlans", "monetizationPlan")},
    )
    assert saved.status_code == 200, saved.text
    reviewed = client.post(
        f'/api/productions/{production["id"]}/adaptation/review',
        json={"revision": saved.json()["revision"]},
    )
    assert reviewed.status_code == 200, reviewed.text
    approved = client.post(
        f'/api/productions/{production["id"]}/adaptation/approve',
        json={"revision": reviewed.json()["revision"]},
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def test_generated_plan_repairs_optional_monetization_outside_episode_range():
    generated = {
        'adaptationPlan': {
            'format': {'episodeCount': 1, 'targetDuration': 15, 'ratio': '16:9', 'platform': '通用短视频'},
            'storyCore': {'premise': '', 'theme': '', 'protagonist': '', 'goal': '', 'stakes': ''},
            'storyArc': {'opening': '', 'development': '', 'turningPoint': '', 'climax': '', 'ending': ''},
            'adaptationStrategy': {'audience': '', 'tone': '', 'changes': '', 'constraints': ''},
            'sourceEventIds': [],
        },
        'episodePlans': [{
            'episodeNo': 1, 'sourceChapterRefs': [], 'logline': '', 'coreConflict': '',
            'emotionalBeat': '', 'hook': '', 'cliffhanger': '', 'paywallRole': 'none',
            'targetDuration': 15,
        }],
        'monetizationPlan': {
            'mode': 'free_then_paid', 'freeEpisodes': 8, 'firstPaywallEpisode': 4,
            'beats': [
                {'episodeNo': 1, 'type': 'hook', 'setup': '', 'cliffhanger': '', 'expectedEmotion': '', 'rationale': ''},
                {'episodeNo': 3, 'type': 'paywall', 'setup': '', 'cliffhanger': '', 'expectedEmotion': '', 'rationale': ''},
            ],
        },
    }
    result = validate_adaptation_bundle(generated, generated=True)
    assert result['monetizationPlan']['freeEpisodes'] == 1
    assert result['monetizationPlan']['firstPaywallEpisode'] == 2
    assert [beat['episodeNo'] for beat in result['monetizationPlan']['beats']] == [1]
    # EP02 is the sentinel for “the single-episode series has no paid episode”.
    # Saving the generated plan manually must keep accepting that value.
    assert validate_adaptation_bundle(result)['monetizationPlan']['firstPaywallEpisode'] == 2


def test_manual_plan_still_rejects_invalid_first_paywall_episode():
    manual = {
        'adaptationPlan': {
            'status': 'draft',
            'format': {'episodeCount': 1, 'targetDuration': 15, 'ratio': '16:9', 'platform': '通用短视频'},
            'storyCore': {}, 'storyArc': {}, 'adaptationStrategy': {}, 'sourceEventIds': [],
        },
        'episodePlans': [{
            'episodeNo': 1, 'sourceChapterRefs': [], 'logline': '', 'coreConflict': '',
            'emotionalBeat': '', 'hook': '', 'cliffhanger': '', 'paywallRole': 'none',
            'targetDuration': 15, 'status': 'draft',
        }],
        'monetizationPlan': {
            'mode': 'free_then_paid', 'freeEpisodes': 1, 'firstPaywallEpisode': 4, 'beats': [],
        },
    }
    with pytest.raises(ValueError, match='首个付费集编号无效'):
        validate_adaptation_bundle(manual)


def test_60_episode_plan_and_paywall_are_canonical_editable_and_no_job_is_automatic(adaptation_client):
    client = adaptation_client
    production, episode, chapter, adaptation = setup_production(client)
    saved = client.put(
        f'/api/productions/{production["id"]}/adaptation',
        json={key: adaptation[key] for key in ("revision", "adaptationPlan", "episodePlans", "monetizationPlan")},
    )
    assert saved.status_code == 200, saved.text
    loaded = client.get(f'/api/productions/{production["id"]}/adaptation').json()
    assert len(loaded["episodePlans"]) == 60
    assert all(plan["sourceChapterRefs"] == [chapter["id"]] for plan in loaded["episodePlans"])
    assert loaded["monetizationPlan"]["beats"][0]["cliffhanger"] == "密信另有夹层"
    assert loaded["adaptationPlan"]["status"] == "draft"
    assert client.get(f'/api/projects/{episode["id"]}/jobs').json() == []

    edited = copy.deepcopy(loaded)
    edited["episodePlans"][2]["hook"] = "阿青在门缝发现血迹"
    edited["monetizationPlan"]["beats"][0]["rationale"] = "强化第三集转付费动机"
    result = client.put(
        f'/api/productions/{production["id"]}/adaptation',
        json={key: edited[key] for key in ("revision", "adaptationPlan", "episodePlans", "monetizationPlan")},
    )
    assert result.status_code == 200
    assert result.json()["episodePlans"][2]["hook"] == "阿青在门缝发现血迹"
    assert result.json()["episodePlans"][2]["status"] == "draft"
    assert client.get(f'/api/projects/{episode["id"]}/jobs').json() == []


def test_script_generation_requires_explicit_approval_and_selected_set_isolated(adaptation_client, monkeypatch):
    client = adaptation_client
    production, episode, _, adaptation = setup_production(client)
    saved = client.put(
        f'/api/productions/{production["id"]}/adaptation',
        json={key: adaptation[key] for key in ("revision", "adaptationPlan", "episodePlans", "monetizationPlan")},
    ).json()
    blocked = client.post(
        f'/api/productions/{production["id"]}/script-generations',
        json={"episode_nos": [5], "provider": "p1-test-openai", "model": "test-text", "allow_cloud": False, "submission_id": "phase3-before-approval"},
    )
    assert blocked.status_code == 400
    reviewed = client.post(f'/api/productions/{production["id"]}/adaptation/review',json={"revision": saved["revision"]}).json()
    approved = client.post(f'/api/productions/{production["id"]}/adaptation/approve',json={"revision": reviewed["revision"]}).json()

    body = {"episode_nos": [5, 8, 12], "provider": "p1-test-openai", "model": "test-text", "allow_cloud": False, "submission_id": "phase3-selected-batch"}
    first = client.post(f'/api/productions/{production["id"]}/script-generations',json=body)
    second = client.post(f'/api/productions/{production["id"]}/script-generations',json=body)
    assert first.status_code == second.status_code == 200, first.text
    assert [job["id"] for job in first.json()["jobs"]] == [job["id"] for job in second.json()["jobs"]]
    assert {job["kind"] for job in first.json()["jobs"]} == {"text"}
    assert {job["scope"] for job in first.json()["jobs"]} == {"episode"}
    assert {job["input"]["episode_script_generation"]["episodeNo"] for job in first.json()["jobs"]} == {5, 8, 12}
    assert {job["input"]["schema_version"] for job in first.json()["jobs"]} == {"episode-script/v1"}
    assert all(job["input"]["system_prompt"] and job["input"]["response_schema"] for job in first.json()["jobs"])

    worker = Worker()
    generated = {
        "title": "生成集", "synopsis": "阿青继续追查", "body": "内景 夜\n阿青：我会找到答案。",
        "estimatedDuration": 60, "characters": ["阿青"], "scenes": ["旧屋"], "props": ["密信"],
    }
    monkeypatch.setattr(worker,"_chat_text",lambda *_args,**_kwargs:json.dumps(generated,ensure_ascii=False))
    for job in first.json()["jobs"]:
        s.job_update(job["id"],status="running")
        result = worker.text({**job,"status":"running"},{"url":"http://unused","local":True})
        assert result["script"]["status"] == "review"
        s.job_update(job["id"],status="succeeded",result=result)

    scripts = client.get(f'/api/productions/{production["id"]}/scripts').json()
    changed = {item["episodeNo"] for item in scripts if item["script"] and item["script"]["body"]}
    assert changed == {5, 8, 12}
    assert client.get(f'/api/productions/{production["id"]}/episode-scripts/13').json()["revision"] == 0
    with s.db() as connection:
        assert {row["kind"] for row in connection.execute(
            "SELECT DISTINCT kind FROM jobs WHERE project_id IN (SELECT id FROM projects WHERE production_id=?)",
            (production["id"],),
        )} == {"text"}


def test_canonical_script_projects_to_canvas_and_canvas_edit_cannot_replace_it(adaptation_client):
    client = adaptation_client
    production, _, _, adaptation = setup_production(client, count=2)
    with s.db() as connection:
        row = connection.execute("SELECT shared_context FROM productions WHERE id=?", (production["id"],)).fetchone()
        context = json.loads(row["shared_context"])
        context["generationPolicy"]["text"] = {"providerId": "ark-for-script", "modelId": "doubao-seed"}
        connection.execute("UPDATE productions SET shared_context=? WHERE id=?", (s.dumps(context), production["id"]))
    approved = save_and_approve(client, production, adaptation)
    virtual = client.get(f'/api/productions/{production["id"]}/episode-scripts/2').json()
    payload = {
        "revision": virtual["revision"], "title": "第二集", "synopsis": "追查仓库",
        "body": "外景 日\n阿青推开仓库大门。", "estimatedDuration": 60,
        "sourceChapterRefs": approved["episodePlans"][1]["sourceChapterRefs"],
        "storyGoal": approved["episodePlans"][1]["coreConflict"],
        "paywallBeat": {"role": "none", "hook": "门锁已开", "cliffhanger": "脚步声逼近"},
        "characters": ["阿青"], "scenes": ["仓库"], "props": ["密信"],
    }
    saved = client.put(f'/api/productions/{production["id"]}/episode-scripts/2',json=payload)
    assert saved.status_code == 200, saved.text
    project_id = saved.json()["project_id"]
    projected = client.get(f'/api/projects/{project_id}').json()
    node = next(item for item in projected["document"]["nodes"] if item["data"].get("canonicalScriptProjection"))
    assert node["data"]["text"] == payload["body"]
    assert node["data"]["provider"] == "ark-for-script"
    assert node["data"]["model"] == "doubao-seed"
    assert node["data"]["generationPolicyInherited"] is True
    node["data"]["text"] = "从画布篡改"
    put = client.put(f'/api/projects/{project_id}',json={
        "name": projected["name"], "revision": projected["revision"],
        "production_revision": projected["production_revision"], "document": projected["document"],
    })
    assert put.status_code == 200, put.text
    reopened = client.get(f'/api/projects/{project_id}').json()
    projection = next(item for item in reopened["document"]["nodes"] if item["data"].get("canonicalScriptProjection"))
    assert projection["data"]["text"] == payload["body"]
    assert client.get(f'/api/productions/{production["id"]}/episode-scripts/2').json()["body"] == payload["body"]

    current_script = client.get(f'/api/productions/{production["id"]}/episode-scripts/2').json()
    cleared = client.put(f'/api/productions/{production["id"]}/episode-scripts/2',json={
        **payload, "revision": current_script["revision"], "body": "",
    })
    assert cleared.status_code == 200, cleared.text
    cleared_project = client.get(f'/api/projects/{project_id}').json()
    assert not any(item["data"].get("canonicalScriptProjection") for item in cleared_project["document"]["nodes"])
    assert not any(item["data"].get("text") == payload["body"] for item in cleared_project["document"]["nodes"])

    stale_canvas = copy.deepcopy(cleared_project["document"])
    stale_canvas["nodes"].append({
        "id": node["id"], "type": "media", "position": {"x": 80, "y": 80},
        "data": {"kind": "text", "text": payload["body"], "canonicalScriptProjection": True},
    })
    stale_put = client.put(f'/api/projects/{project_id}',json={
        "name": cleared_project["name"], "revision": cleared_project["revision"],
        "production_revision": cleared_project["production_revision"], "document": stale_canvas,
    })
    assert stale_put.status_code == 200, stale_put.text
    assert client.get(f'/api/productions/{production["id"]}/episode-scripts/2').json()["body"] == ""
    after_stale_put = client.get(f'/api/projects/{project_id}').json()
    assert not any(item["data"].get("text") == payload["body"] for item in after_stale_put["document"]["nodes"])


def test_canvas_script_becomes_the_canonical_episode_script_and_can_bypass_planning(adaptation_client):
    client = adaptation_client
    project = client.post('/api/projects',json={'name':'画布快速创作','duration':15}).json()
    node_id='canvas-script-draft'
    project['document']['nodes'].append({
        'id':node_id,'type':'media','position':{'x':80,'y':80},
        'data':{'kind':'text','label':'画布剧本','text':'内景 日\n女孩推开门。'},
    })
    stored=client.put(f'/api/projects/{project["id"]}',json={
        'name':project['name'],'revision':project['revision'],
        'production_revision':project['production_revision'],'document':project['document'],
    })
    assert stored.status_code==200,stored.text
    script=client.get(f'/api/productions/{project["production_id"]}/episode-scripts/1').json()
    saved=client.put(f'/api/productions/{project["production_id"]}/episode-scripts/1',json={
        'revision':script['revision'],'title':'第一集','synopsis':'','body':'内景 日\n女孩推开门。',
        'estimatedDuration':15,'sourceChapterRefs':[],'storyGoal':'','paywallBeat':{},
        'characters':[],'scenes':[],'props':[],'canvasNodeId':node_id,
    })
    assert saved.status_code==200,saved.text
    assert saved.json()['metadata']['origin']=='canvas'
    projected=client.get(f'/api/projects/{project["id"]}').json()
    projection=next(node for node in projected['document']['nodes'] if node['id']==node_id)
    assert projection['data']['canonicalScriptProjection'] is True
    assert projection['data']['scriptOrigin']=='canvas'
    reviewed=client.post(f'/api/productions/{project["production_id"]}/episode-scripts/1/review',json={'revision':saved.json()['revision']})
    assert reviewed.status_code==200,reviewed.text
    approved=client.post(f'/api/productions/{project["production_id"]}/episode-scripts/1/approve',json={'revision':reviewed.json()['revision']})
    assert approved.status_code==200,approved.text
    assert approved.json()['status']=='approved'


def test_project_put_cannot_persist_a_second_copy_of_production_adaptation(adaptation_client):
    client = adaptation_client
    production, episode, _, adaptation = setup_production(client, count=2)
    canonical = save_and_approve(client, production, adaptation)
    project = client.get(f'/api/projects/{episode["id"]}').json()
    project["document"]["adaptationPlan"] = {"forged": True}
    project["document"]["episodePlans"] = [{"forged": True}]
    project["document"]["monetizationPlan"] = {"forged": True}
    saved = client.put(f'/api/projects/{episode["id"]}', json={
        "name": project["name"], "revision": project["revision"],
        "production_revision": project["production_revision"], "document": project["document"],
    })
    assert saved.status_code == 200, saved.text
    reopened = client.get(f'/api/projects/{episode["id"]}').json()
    assert all(key not in reopened["document"] for key in ("adaptationPlan", "episodePlans", "monetizationPlan"))
    with s.db() as connection:
        stored = json.loads(connection.execute('SELECT document FROM projects WHERE id=?',(episode["id"],)).fetchone()["document"])
    assert all(key not in stored for key in ("adaptationPlan", "episodePlans", "monetizationPlan"))
    current = client.get(f'/api/productions/{production["id"]}/adaptation').json()
    assert current["adaptationPlan"] == canonical["adaptationPlan"]
    assert current["episodePlans"] == canonical["episodePlans"]
    assert current["monetizationPlan"] == canonical["monetizationPlan"]


def test_source_edit_marks_approved_plan_and_derived_script_stale_without_ai_call(adaptation_client):
    client = adaptation_client
    production, _, chapter, adaptation = setup_production(client, count=1)
    approved = save_and_approve(client, production, adaptation)
    virtual = client.get(f'/api/productions/{production["id"]}/episode-scripts/1').json()
    script = client.put(f'/api/productions/{production["id"]}/episode-scripts/1',json={
        "revision": virtual["revision"], "title": "第一集", "synopsis": "密信出现", "body": "阿青读信。",
        "estimatedDuration": 60, "sourceChapterRefs": [chapter["id"]], "storyGoal": "查明真相",
        "paywallBeat": {}, "characters": ["阿青"], "scenes": ["旧屋"], "props": ["密信"],
    }).json()
    reviewed = client.post(f'/api/productions/{production["id"]}/episode-scripts/1/review',json={"revision": script["revision"]}).json()
    approved_script = client.post(f'/api/productions/{production["id"]}/episode-scripts/1/approve',json={"revision": reviewed["revision"]})
    assert approved_script.status_code == 200, approved_script.text
    before_jobs = sum(len(item["jobs"]) if isinstance(item,dict) and "jobs" in item else 0 for item in [])
    edited = client.put(f'/api/productions/{production["id"]}/chapters/{chapter["id"]}',json={
        "title": chapter["title"], "content": chapter["content"] + "\n密信被烧毁。", "revision": chapter["revision"],
    })
    assert edited.status_code == 200, edited.text
    stale = client.get(f'/api/productions/{production["id"]}/adaptation').json()
    assert stale["adaptationPlan"]["status"] == "stale"
    assert stale["episodePlans"][0]["status"] == "stale"
    assert client.get(f'/api/productions/{production["id"]}/episode-scripts/1').json()["status"] == "stale"
    with s.db() as connection:
        assert connection.execute(
            "SELECT COUNT(*) value FROM jobs WHERE project_id IN (SELECT id FROM projects WHERE production_id=?)",
            (production["id"],),
        ).fetchone()["value"] == before_jobs
