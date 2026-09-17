"""Readable generated names without changing asset identity or cancellation."""
from concurrent.futures import ThreadPoolExecutor
import time

from PIL import Image
import pytest

from backend import store as s
from backend.providers import common


def job_for(project_id=None, node_id='video-6', **inputs):
    s.init()
    now = time.time()
    project_id = project_id or s.uid('naming-project-')
    job_id = s.uid('naming-job-')
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s) ON CONFLICT DO NOTHING',
                  (project_id, 'Naming fixture', '{}', now, now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                  (job_id, job_id, project_id, node_id, 'image', 'running', s.dumps(inputs), now, now))
    return {'id': job_id, 'project_id': project_id, 'node_id': node_id, 'input': inputs}


def image_file(tmp_path):
    source = tmp_path / 'source.png'
    Image.new('RGB', (12, 12), 'blue').save(source)
    return source


def test_real_registration_uses_label_and_preserves_file_identity(tmp_path):
    source = image_file(tmp_path)
    job = job_for(label='shot-006 · 分镜图')
    first = common.register(job, source, 'Seedream 生成图.png')
    second = common.register(job_for(job['project_id'], label='shot-006 · 分镜图'), source, '幻场 AI 生成图.png')
    assert first['name'] == '镜头 06 · 分镜图 · V1.png'
    assert second['name'] == '镜头 06 · 分镜图 · V2.png'
    with s.db() as c:
        row = c.execute('SELECT * FROM assets WHERE id=%s', (second['id'],)).fetchone()
    assert row['name'] == second['name']
    assert row['path'] == second['id'] + '.png'
    assert (s.ASSETS / row['path']).read_bytes() == source.read_bytes()
    assert s.unpack(row)['metadata']['input']['label'] == job['input']['label']


@pytest.mark.parametrize('requested,inputs,count,expected', [
    ('生成结果.mp4', {'label': 'shot-006 · 视频'}, 1, '镜头 06 · 视频 · V2.mp4'),
    ('Seedream 生成图.png', {'output_name': '球球 · 主参考图 · V1.png', 'label': 'ignored'}, 9, '球球 · 主参考图 · V1.png'),
    ('导演导入.mp4', {'label': 'shot-001 · 视频'}, 3, '导演导入.mp4'),
    ('生成结果 · 固定角色音色.mp4', {'asset_label': 'shot-002 · 视频'}, 0, '镜头 02 · 视频 · 固定角色音色 · V1.mp4'),
    ('生成结果.mp4', {}, 2, '生成结果.mp4'),
    ('生成结果.mp4', {'asset_name': '角色/../预览?.png'}, 0, '角色-..-预览.mp4'),
])
def test_name_policy(requested, inputs, count, expected):
    assert common._registered_asset_name({'input': inputs}, requested, '.mp4', count) == expected


def test_same_node_concurrent_registration_gets_distinct_display_versions(tmp_path):
    source = image_file(tmp_path)
    first = job_for(label='shot-006 · 分镜图')
    jobs = [first, *(job_for(first['project_id'], label='shot-006 · 分镜图') for _ in range(3))]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda job: common.register(job, source, '生成结果.png'), jobs))
    assert {item['name'] for item in results} == {f'镜头 06 · 分镜图 · V{i}.png' for i in range(1, 5)}
    other_node = common.register(job_for(first['project_id'], node_id='other', label='shot-006 · 分镜图'), source, '生成结果.png')
    other_ep = common.register(job_for(label='shot-006 · 分镜图'), source, '生成结果.png')
    assert other_node['name'] == other_ep['name'] == '镜头 06 · 分镜图 · V1.png'


def test_explicit_visual_name_and_existing_custom_names_remain_stable(tmp_path):
    source = image_file(tmp_path)
    job = job_for(output_name='球球 · 状态参考图 · V3.png', label='ignored')
    named = common.register(job, source, 'Seedream 生成图.png')
    assert named['name'] == '球球 · 状态参考图 · V3.png'
    custom = common.register(job_for(label='ignored'), source, '导演参考.png')
    assert custom['name'] == '导演参考.png'


def test_cancel_while_waiting_for_name_group_never_publishes_media(tmp_path):
    from tests.test_p3_r2_interleavings import wait_for_db_waiters
    source = image_file(tmp_path)
    job = job_for(label='shot-006 · 分镜图')
    existing = set(s.ASSETS.iterdir())
    group = s.dumps(['asset-name', job['project_id'], job['node_id'], 'image'])
    with ThreadPoolExecutor(max_workers=1) as pool:
        with s.db() as c:
            c.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))', (group,))
            future = pool.submit(common.register, job, source, '生成结果.png')
            assert wait_for_db_waiters(1)
            assert s.job_update(job['id'], status='cancelled')
        with pytest.raises(InterruptedError):
            future.result(10)
    with s.db() as c:
        assert c.execute('SELECT count(*) n FROM assets WHERE project_id=%s', (job['project_id'],)).fetchone()['n'] == 0
    assert set(s.ASSETS.iterdir()) == existing
    assert source.exists()
