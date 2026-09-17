from pathlib import Path

import pytest

from backend.editor_renderer import EditorRenderCompiler, SUPPORTED_MEDIA_FILTERS, _media_filter


def element(asset_id='asset-1', start=0, end=1):
    return {
        'id': 'element-1', 'type': 'image', 's': start, 'e': end,
        'props': {'srcAssetId': asset_id}, 'metadata': {'assetId': asset_id},
        'frame': {'x': 0, 'y': 0, 'size': [128, 128]},
    }


@pytest.mark.parametrize('rate', [0.5, 1, 2])
def test_generic_two_clip_render_keeps_second_clip_and_full_duration(tmp_path, rate):
    import subprocess
    from backend import store as s
    from backend.media import ffmpeg_executable, probe
    s.init()
    ffmpeg = ffmpeg_executable()
    assets = {}
    elements = []
    for index, color in enumerate(['red', 'blue']):
        path = tmp_path / (color + '.mp4')
        result = subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
            f'color=c={color}:s=64x64:r=24:d=1', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(path)],
            capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr
        assets[color] = {'id': color, 'project_id': 'p', 'kind': 'video', 'absolute_path': str(path)}
        elements.append({'id': color, 'type': 'video', 's': index / rate, 'e': (index + 1) / rate,
            'props': {'srcAssetId': color, 'time': 0, 'playbackRate': rate, 'volume': 0},
            'frame': {'x': 0, 'y': 0, 'size': [64, 64]}, 'mediaDuration': 1})
    timeline = {'version': 2, 'metadata': {'custom': {'timelineDuration': 60}},
                'tracks': [{'id': 'v1', 'type': 'element', 'elements': elements}]}
    plan = EditorRenderCompiler('p', timeline, (64, 64), tmp_path, assets.get, probe).compile(ffmpeg, tmp_path / 'out.mp4')
    assert plan.duration == 2 / rate
    rendered = subprocess.run(plan.args, capture_output=True, timeout=30)
    assert rendered.returncode == 0, rendered.stderr
    for time, channel in [(.5 / rate, 0), (1.5 / rate, 2)]:
        frame = subprocess.run([ffmpeg, '-v', 'error', '-ss', str(time), '-i', str(tmp_path / 'out.mp4'),
            '-frames:v', '1', '-vf', 'scale=1:1', '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-'],
            capture_output=True, timeout=20)
        assert frame.returncode == 0, frame.stderr
        assert len(frame.stdout) == 3
        assert frame.stdout[channel] > 200 and sum(frame.stdout) - frame.stdout[channel] < 40, frame.stdout


def test_editor_compiler_rejects_cross_project_assets(tmp_path):
    project = {'version': 2, 'tracks': [{'id': 'v1', 'name': 'V1', 'elements': [element()]}]}
    compiler = EditorRenderCompiler(
        'project-a', project, (128, 128), tmp_path,
        lambda _asset_id: {'id': 'asset-1', 'project_id': 'project-b', 'kind': 'image', 'absolute_path': str(tmp_path / 'x.png')},
        lambda _path: {},
    )
    with pytest.raises(ValueError, match='属于其他项目'):
        compiler.compile('ffmpeg', Path(tmp_path / 'out.mp4'))


@pytest.mark.parametrize('asset_production,target_production', [(None, 'work-a'), ('work-b', 'work-a'), ('work-a', None), ('', '')])
def test_cross_episode_requires_explicit_matching_trusted_production(tmp_path, asset_production, target_production):
    clip = element()
    timeline = {'version': 2, 'tracks': [{'id': 'v1', 'elements': [clip]}],
                'metadata': {'production_id': 'work-a'}}
    row = {'id': 'asset-1', 'project_id': 'other-episode', 'production_id': asset_production, 'kind': 'image'}
    compiler = EditorRenderCompiler('current-episode', timeline, (128, 128), tmp_path,
                                   lambda _: row, lambda _: {}, production_id=target_production)
    with pytest.raises(ValueError, match='属于其他项目'):
        compiler._row(clip, 'image')


@pytest.mark.parametrize('start,end', [(-1, 1), (1, 1), (0, 21601)])
def test_editor_compiler_rejects_invalid_element_ranges(tmp_path, start, end):
    project = {'version': 2, 'tracks': [{'id': 'v1', 'name': 'V1', 'elements': [element(start=start, end=end)]}]}
    with pytest.raises(ValueError, match='时间范围无效'):
        EditorRenderCompiler('project-a', project, (128, 128), tmp_path, lambda _: None, lambda _: {})


def test_editor_compiler_rejects_visible_unsupported_elements(tmp_path):
    unsupported = element()
    unsupported.update({'type': 'rect', 'props': {'fill': '#ffffff'}})
    project = {'version': 2, 'tracks': [{'id': 'v1', 'name': 'V1', 'elements': [unsupported]}]}
    with pytest.raises(ValueError, match='不支持的类型'):
        EditorRenderCompiler('project-a', project, (128, 128), tmp_path, lambda _: None, lambda _: {})


@pytest.mark.parametrize('patch,match', [
    ({'props': {'mediaFilter': 'unknown'}}, '不支持的画面滤镜'),
    ({'animation': {'name': 'rise'}}, '不支持的动画'),
    ({'frameEffects': [{'name': 'circle'}]}, '不支持的高级效果'),
])
def test_editor_compiler_rejects_unimplemented_effects(tmp_path, patch, match):
    visual = element()
    visual.update(patch)
    project = {'version': 2, 'tracks': [{'id': 'v1', 'name': 'V1', 'elements': [visual]}]}
    with pytest.raises(ValueError, match=match):
        EditorRenderCompiler('project-a', project, (128, 128), tmp_path, lambda _: None, lambda _: {})


@pytest.mark.parametrize('transition,match', [
    ({'toElementId': 'missing', 'kind': 'crossfade', 'duration': .2}, '目标不存在'),
    ({'toElementId': 'element-2', 'kind': 'wipe', 'duration': .2}, '不支持的转场'),
    ({'toElementId': 'element-2', 'kind': 'crossfade', 'duration': 2}, '转场时长无效'),
])
def test_editor_compiler_rejects_invalid_transitions(tmp_path, transition, match):
    first = element(start=0, end=1)
    first['transition'] = transition
    second = element(start=1, end=2)
    second['id'] = 'element-2'
    project = {'version': 2, 'tracks': [
        {'id': 'v1', 'name': 'V1', 'elements': [first]},
        {'id': 'v2', 'name': 'V2', 'elements': [second]},
    ]}
    compiler = EditorRenderCompiler(
        'project-a', project, (128, 128), tmp_path,
        lambda asset_id: {'id': asset_id, 'project_id': 'project-a', 'kind': 'image', 'absolute_path': str(tmp_path / 'x.png')},
        lambda _path: {},
    )
    with pytest.raises(ValueError, match=match):
        compiler.compile('ffmpeg', Path(tmp_path / 'out.mp4'))


def test_editor_compiler_translates_transform_filter_and_native_fade(tmp_path):
    visual = element(start=.5, end=2.5)
    visual.update({
        'props': {'srcAssetId': 'asset-1', 'opacity': .5, 'mediaFilter': 'blackWhite'},
        'frame': {'x': 12, 'y': 18, 'size': [96, 72], 'rotation': 15},
        'animation': {'name': 'fade', 'animate': 'both', 'interval': .25, 'duration': 2},
    })
    compiler = EditorRenderCompiler(
        'project-a', {'version': 2, 'tracks': [{'id': 'v1', 'name': 'V1', 'elements': [visual]}]},
        (128, 128), tmp_path,
        lambda asset_id: {'id': asset_id, 'project_id': 'project-a', 'kind': 'image', 'absolute_path': str(tmp_path / 'x.png')},
        lambda _path: {},
    )
    plan = compiler.compile('ffmpeg', Path(tmp_path / 'out.mp4'))
    graph = plan.args[plan.args.index('-filter_complex') + 1]
    assert 'hue=s=0' in graph
    assert 'rotate=15.000000*PI/180' in graph
    assert 'colorchannelmixer=aa=0.500000' in graph
    assert 'fade=t=in:st=0:d=0.250000:alpha=1' in graph
    assert 'fade=t=out:st=1.750000:d=0.250000:alpha=1' in graph
    assert 'overlay=x=12.000:y=18.000' in graph


@pytest.mark.parametrize('filter_name', sorted(SUPPORTED_MEDIA_FILTERS - {'none'}))
def test_every_exposed_media_filter_is_valid_ffmpeg(filter_name):
    import subprocess
    from backend import store as s
    from backend.media import ffmpeg_executable
    s.init()
    filters = _media_filter(filter_name)
    assert filters, filter_name
    result = subprocess.run([
        ffmpeg_executable(), '-v', 'error', '-f', 'lavfi', '-i',
        'color=c=#4678aa:s=32x32:d=0.1', '-vf', ','.join(filters),
        '-frames:v', '1', '-f', 'null', '-',
    ], capture_output=True, timeout=20)
    assert result.returncode == 0, (filter_name, result.stderr)
