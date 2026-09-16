import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend import store as s
from tests.auth_helpers import login_admin
from tests.platform_model_helpers import publish_test_model


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as value:
        login_admin(value)
        yield value


@pytest.fixture()
def configured_provider(client):
    return {kind: publish_test_model(client, "setup-"+kind, kind=kind, provider_type="volcengine_ark")
            for kind in ("text", "image", "video")}


def test_project_create_with_setup_fields_owns_data_and_has_no_generation_side_effects(client, configured_provider):
    payload = {
        "name": "花信未迟",
        "episode_title": "初见",
        "style": "国风电影写实",
        "ratio": "9:16",
        "duration": 60,
        "video_resolution": "1080p",
        "video_ratio": "21:9",
        "video_duration": 8,
        "video_format": "mov",
        "episode_count": 12,
        "platform": "抖音",
        "brief": "十五秒概念扩展",
        "generation_policy": {
            kind: {"model_id": configured_provider[kind]["id"]}
            for kind in ("text", "image", "video")
        },
        "film_bible": {
            "story": {"worldEra": "当代江南"},
            "style": {"visualTone": "克制", "avoidItems": ["高饱和"]},
            "continuity": {"characterSceneConsistency": "服装和天气连续"},
        },
    }
    response = client.post("/api/projects", json=payload)
    assert response.status_code == 200, response.text
    project = response.json()
    document = project["document"]
    assert project["name"] == project["episode_title"] == "初见"
    assert document["style"] == "国风电影写实"
    assert document["ratio"] == "9:16" and document["duration"] == 60
    assert document["videoResolution"] == "1080p"
    assert document["videoRatio"] == "21:9"
    assert document["videoDuration"] == 8
    assert document["videoFormat"] == "mov"
    assert document["brief"] == payload["brief"]
    assert document["generationPolicy"] == payload["generation_policy"]
    assert document["filmBible"]["story"]["worldEra"] == "当代江南"
    assert document["filmBible"]["visual"] == {"cards": {}, "versions": {}}
    assert document["filmBible"]["styleVersion"] == 1
    assert client.get(f'/api/projects/{project["id"]}/jobs').json() == []
    assert client.get(f'/api/projects/{project["id"]}/assets').json() == []
    with s.db() as db:
        episode = db.execute("SELECT document FROM projects WHERE id=%s", (project["id"],)).fetchone()
        production = db.execute("SELECT name,shared_context FROM productions WHERE id=%s", (project["production_id"],)).fetchone()
    stored_episode = json.loads(episode["document"])
    assert not {"style", "generationPolicy", "filmBible"}.intersection(stored_episode)
    stored_context = json.loads(production["shared_context"])
    assert production["name"] == "花信未迟"
    assert stored_context["style"] == payload["style"]
    assert stored_context["generationPolicy"] == payload["generation_policy"]
    assert stored_context["adaptationPlan"]["format"] == {
        "episodeCount": 12, "targetDuration": 60.0, "ratio": "9:16", "platform": "抖音",
    }
    assert len(stored_context["episodePlans"]) == 12
    assert all(plan["targetDuration"] == 60 for plan in stored_context["episodePlans"])


def test_project_create_name_only_remains_backward_compatible(client):
    response = client.post("/api/projects", json={"name": "Legacy"})
    assert response.status_code == 200
    project = response.json()
    assert project["name"] == project["episode_title"] == "Legacy"
    assert project["document"]["style"] == "电影写实"
    assert project["document"]["ratio"] == "16:9"
    assert project["document"]["duration"] == 15
    adaptation = client.get(f'/api/productions/{project["production_id"]}/adaptation').json()
    assert adaptation["adaptationPlan"]["format"] == {
        "episodeCount": 1, "targetDuration": 15.0, "ratio": "16:9", "platform": "通用短视频",
    }
    assert len(adaptation["episodePlans"]) == 1


def test_legacy_adaptation_get_is_read_only_and_setup_format_is_explicit(client):
    project = client.post("/api/projects", json={
        "name": "旧项目规格修复", "ratio": "16:9", "duration": 30,
    }).json()
    with s.db() as db:
        row = db.execute("SELECT shared_context FROM productions WHERE id=%s", (project["production_id"],)).fetchone()
        context = json.loads(row["shared_context"])
        context["adaptationPlan"]["format"] = {
            "episodeCount": 60, "targetDuration": 60, "ratio": "9:16", "platform": "红果短剧",
        }
        context["episodePlans"] = []
        db.execute("UPDATE productions SET shared_context=%s WHERE id=%s", (s.dumps(context), project["production_id"]))
    def snapshot():
        with s.db() as db:
            row = db.execute("SELECT shared_context,revision,updated FROM productions WHERE id=%s",
                             (project["production_id"],)).fetchone()
            history = db.execute("SELECT COUNT(*) count FROM production_revisions WHERE production_id=%s",
                                 (project["production_id"],)).fetchone()['count']
            events = db.execute("SELECT COUNT(*) count FROM events WHERE project_id=%s",
                                (project["id"],)).fetchone()['count']
        return dict(row), history, events
    before = snapshot()
    response = client.get(f'/api/productions/{project["production_id"]}/adaptation')
    assert response.status_code == 200, response.text
    adaptation = response.json()
    # P5 forbids implicit legacy migration through a read endpoint.
    assert adaptation["adaptationPlan"]["format"] == context["adaptationPlan"]["format"]
    assert adaptation["episodePlans"] == []
    assert snapshot() == before
    from backend.adaptation import configure_adaptation_format
    configured = configure_adaptation_format(context, 1, 30, '16:9', '通用短视频')
    assert configured["adaptationPlan"]["format"] == {
        "episodeCount": 1, "targetDuration": 30.0, "ratio": "16:9", "platform": "通用短视频",
    }
    assert len(configured["episodePlans"]) == 1
    assert configured["episodePlans"][0]["targetDuration"] == 30
    assert context["episodePlans"] == []


def test_invalid_generation_policy_leaves_no_partial_rows(client, configured_provider):
    with s.db() as db:
        before = tuple(db.execute(f"SELECT COUNT(*) count FROM {table}").fetchone()['count'] for table in ("productions", "projects"))
    response = client.post("/api/projects", json={
        "name": "不应创建",
        "generation_policy": {"text": {"model_id": "missing"}, "image": None, "video": None},
    })
    assert response.status_code == 400
    with s.db() as db:
        after = tuple(db.execute(f"SELECT COUNT(*) count FROM {table}").fetchone()['count'] for table in ("productions", "projects"))
    assert after == before


def test_project_create_rejects_removed_local_text_runtime_target(client, configured_provider):
    response = client.post("/api/projects", json={
        "name": "本地文本项目",
        "generation_policy": {
            "text": {"model_id": "local"},
            "image": None,
            "video": None,
        },
    })
    assert response.status_code == 400
    assert "不会自动切换" in response.json()["detail"]


def test_production_rename_is_revision_protected_and_preserves_episode_and_context(client):
    project = client.post("/api/projects", json={"name": "原作品", "episode_title": "第一集"}).json()
    production = client.get(f'/api/productions/{project["production_id"]}').json()
    before_context = production["context"]
    renamed = client.patch(f'/api/productions/{production["id"]}', json={"revision": production["revision"], "name": "新作品"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["revision"] == production["revision"] + 1
    assert client.patch(f'/api/productions/{production["id"]}', json={"revision": production["revision"], "name": "覆盖"}).status_code == 409
    current = client.get(f'/api/productions/{production["id"]}').json()
    episode = client.get(f'/api/projects/{project["id"]}').json()
    assert current["name"] == "新作品" and current["context"] == before_context
    assert episode["name"] == episode["episode_title"] == "第一集"


def test_shared_settings_save_preserves_adaptation_context(client):
    project = client.post("/api/projects", json={"name": "上下文保留"}).json()
    with s.db() as db:
        row = db.execute("SELECT shared_context FROM productions WHERE id=%s", (project["production_id"],)).fetchone()
        context = json.loads(row["shared_context"])
        context["adaptationPlan"] = {"status": "approved", "premise": "保留改编方案"}
        context["episodePlans"] = [{"episode_no": 1, "title": "保留集纲"}]
        context["monetizationPlan"] = {"format": "learning"}
        db.execute("UPDATE productions SET shared_context=%s WHERE id=%s", (s.dumps(context), project["production_id"]))
    current = client.get(f'/api/projects/{project["id"]}').json()
    current["document"]["generationPolicy"] = {"text": None, "image": None, "video": None}
    retired = client.put(f'/api/projects/{project["id"]}', json={
        "name": current["name"],
        "revision": current["revision"],
        "production_revision": current["production_revision"],
        "document": current["document"],
    })
    assert retired.status_code == 410, retired.text
    saved = client.patch(f'/api/productions/{project["production_id"]}/context', json={
        "expected_revision": current["production_revision"],
        "patch": {"generationPolicy": current["document"]["generationPolicy"]},
    })
    assert saved.status_code == 200, saved.text
    assert saved.json()["revision"] == current["production_revision"] + 1
    production = client.get(f'/api/productions/{project["production_id"]}').json()["context"]
    assert production["generationPolicy"] == current["document"]["generationPolicy"]
    assert production["adaptationPlan"]["status"] == "approved"
    assert production["adaptationPlan"]["premise"] == "保留改编方案"
    assert production["episodePlans"] == context["episodePlans"]
    assert production["monetizationPlan"]["format"] == "learning"
