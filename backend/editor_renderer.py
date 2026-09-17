"""Compile a persisted Twick project into one native FFmpeg render graph."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


MAX_DURATION = 6 * 60 * 60
VISUAL_TYPES = {'video', 'image'}
MEDIA_TYPES = {'video', 'image', 'audio'}
SUPPORTED_TYPES = MEDIA_TYPES | {'text', 'caption'}
SUPPORTED_TRANSITIONS = {'fade', 'crossfade'}
SUPPORTED_MEDIA_FILTERS = {
    'none', 'saturated', 'bright', 'vibrant', 'retro', 'blackWhite',
    'grayscale', 'sepia', 'cool', 'warm', 'cinematic', 'contrast',
    'softGlow', 'moody', 'dreamy', 'inverted', 'vintage', 'dramatic', 'faded',
}


@dataclass
class RenderPlan:
    args: list[str]
    duration: float
    visual_count: int
    audio_count: int
    text_count: int


def _number(value: Any, default: float = 0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        result = default
    if not math.isfinite(result):
        result = default
    return result


def _clamp(value: Any, low: float, high: float, default: float = 0) -> float:
    return max(low, min(high, _number(value, default)))


def _asset_id(element: dict) -> str:
    metadata = element.get('metadata') or {}
    props = element.get('props') or {}
    value = metadata.get('assetId') or props.get('srcAssetId')
    if not isinstance(value, str) or not value:
        raise ValueError(f'剪辑元素 {element.get("id", "未知")} 缺少项目素材 ID')
    return value


def _fade(element: dict) -> dict[str, float]:
    mvc = (element.get('metadata') or {}).get('mvc') or {}
    raw = mvc.get('fade') or {}
    duration = _number(element.get('e')) - _number(element.get('s'))
    limit = max(0, duration / 2)
    result = {key: _clamp(raw.get(key), 0, limit) for key in ('videoIn', 'videoOut', 'audioIn', 'audioOut')}
    animation = element.get('animation') or {}
    if animation.get('name') == 'fade':
        interval = _clamp(animation.get('interval', animation.get('duration')), 0, limit)
        animate = animation.get('animate')
        if animate in {'enter', 'both'}:
            result['videoIn'] = max(result['videoIn'], interval)
        if animate in {'exit', 'both'}:
            result['videoOut'] = max(result['videoOut'], interval)
    return result


def _color(value: Any, default: str = '#000000') -> str:
    text = str(value or '')
    return text if re.fullmatch(r'#[0-9a-fA-F]{6}', text) else default


def _ass_color(value: Any, opacity: float = 1) -> str:
    color = _color(value, '#ffffff').lstrip('#')
    alpha = round((1 - _clamp(opacity, 0, 1, 1)) * 255)
    return f'&H{alpha:02X}{color[4:6]}{color[2:4]}{color[0:2]}&'


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, rest = divmod(centiseconds, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f'{hours}:{minutes:02d}:{secs:02d}.{cs:02d}'


def _ass_text(value: Any) -> str:
    return str(value or '').replace('\\', r'\\').replace('{', r'\{').replace('}', r'\}').replace('\r', '').replace('\n', r'\N')


def _atempo(rate: float) -> list[str]:
    filters = []
    while rate > 2:
        filters.append('atempo=2')
        rate /= 2
    while rate < .5:
        filters.append('atempo=0.5')
        rate /= .5
    filters.append(f'atempo={rate:.8g}')
    return filters


def _media_filter(name: Any) -> list[str]:
    return {
        'none': [],
        'saturated': ['eq=saturation=1.4:contrast=1.1'],
        'bright': ['eq=brightness=.18:contrast=1.05'],
        'vibrant': ['eq=saturation=1.6:brightness=.1:contrast=1.1'],
        'retro': ['colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131', 'eq=contrast=1.3:brightness=-.08:saturation=.8'],
        'blackWhite': ['hue=s=0', 'eq=contrast=1.25:brightness=.03'],
        'grayscale': ['hue=s=0', 'eq=contrast=1.25:brightness=.03'],
        'sepia': ['colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131', 'eq=contrast=1.08'],
        'cool': ['hue=h=15', 'eq=brightness=.06:saturation=1.3:contrast=1.05'],
        'warm': ['hue=h=-15', 'eq=brightness=.1:saturation=1.3:contrast=1.05'],
        'cinematic': ['eq=contrast=1.4:brightness=-.03:saturation=.85'],
        'contrast': ['eq=contrast=1.4:brightness=-.03:saturation=.85'],
        'softGlow': ['gblur=sigma=1.2', 'eq=brightness=.12:contrast=.95:saturation=1.1'],
        'moody': ['eq=brightness=.03:contrast=1.4:saturation=.65'],
        'dreamy': ['gblur=sigma=2', 'eq=brightness=.18:contrast=.95:saturation=1.4'],
        'inverted': ['negate', 'hue=h=180'],
        'vintage': ['colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131', 'eq=saturation=1.4:contrast=1.2:brightness=.06'],
        'dramatic': ['eq=contrast=1.5:brightness=-.06:saturation=1.2'],
        'faded': ['eq=brightness=.12:contrast=.9:saturation=.8'],
    }.get(str(name), [])


def _volume_filter(element: dict, base: float, duration: float) -> str:
    mvc = (element.get('metadata') or {}).get('mvc') or {}
    raw = mvc.get('volumeKeyframes')
    if not isinstance(raw, list) or not raw:
        return f'volume={base:.6f}'
    points = []
    for point in raw:
        if not isinstance(point, dict):
            raise ValueError('音量关键帧格式无效')
        time = _number(point.get('time'), -1)
        value = _number(point.get('value'), -1)
        if time < 0 or time > duration or value < 0 or value > 2:
            raise ValueError('音量关键帧超出片段范围')
        points.append((time, value))
    points.sort()
    if any(points[index][0] <= points[index - 1][0] for index in range(1, len(points))):
        raise ValueError('音量关键帧时间必须递增且不能重复')
    expression = f'{points[-1][1]:.8g}'
    for index in range(len(points) - 2, -1, -1):
        t0, v0 = points[index]
        t1, v1 = points[index + 1]
        linear = f'{v0:.8g}+({v1 - v0:.8g})*(t-{t0:.8g})/{t1 - t0:.8g}'
        expression = f'if(lt(t,{t1:.8g}),{linear},{expression})'
    if points[0][0] > 0:
        expression = f'if(lt(t,{points[0][0]:.8g}),{points[0][1]:.8g},{expression})'
    return f"volume='{base:.6f}*({expression})':eval=frame"


class EditorRenderCompiler:
    def __init__(
        self,
        project_id: str,
        project: dict,
        resolution: tuple[int, int],
        work: Path,
        asset_lookup: Callable[[str], Any],
        probe_media: Callable[[Path], dict],
        *,
        production_id: str | None = None,
    ):
        self.project_id = project_id
        # Only callers that resolved the production from trusted storage may
        # opt into cross-episode assets. Timeline metadata is never authority.
        self.production_id = production_id
        self.project = project
        self.width, self.height = resolution
        self.work = work
        self.asset_lookup = asset_lookup
        self.probe_media = probe_media
        self.tracks = project.get('tracks') if isinstance(project, dict) else None
        if not isinstance(self.tracks, list):
            raise ValueError('编辑工程格式无效：缺少 tracks')
        if not 64 <= self.width <= 4096 or not 64 <= self.height <= 4096:
            raise ValueError('导出分辨率无效')
        self.elements: list[tuple[int, dict, dict]] = []
        element_ids: set[str] = set()
        for track_index, track in enumerate(self.tracks):
            if not isinstance(track, dict) or not isinstance(track.get('elements'), list):
                raise ValueError('编辑工程包含无效轨道')
            track_props = track.get('props') or {}
            for element in track['elements']:
                if not isinstance(element, dict):
                    raise ValueError('编辑工程包含无效元素')
                start, end = _number(element.get('s'), -1), _number(element.get('e'), -1)
                if start < 0 or end - start < .05 or end > MAX_DURATION:
                    raise ValueError(f'剪辑元素 {element.get("id", "未知")} 的时间范围无效')
                element_id = element.get('id')
                if not isinstance(element_id, str) or not element_id or element_id in element_ids:
                    raise ValueError('编辑工程的元素 ID 缺失或重复')
                element_ids.add(element_id)
                element_type = element.get('type')
                if element_type not in SUPPORTED_TYPES and not track_props.get('hidden'):
                    raise ValueError(f'剪辑元素 {element_id} 使用了导出器不支持的类型：{element_type or "缺失"}')
                props = element.get('props') or {}
                media_filter = props.get('mediaFilter')
                if element_type in VISUAL_TYPES and media_filter not in (None, '') and media_filter not in SUPPORTED_MEDIA_FILTERS:
                    raise ValueError(f'剪辑元素 {element_id} 使用了不支持的画面滤镜：{media_filter}')
                animation = element.get('animation') or {}
                if animation and (element_type == 'audio' or animation.get('name') != 'fade'):
                    raise ValueError(f'剪辑元素 {element_id} 使用了导出器不支持的动画')
                if element.get('frameEffects') or element.get('textEffect'):
                    raise ValueError(f'剪辑元素 {element_id} 使用了导出器不支持的高级效果')
                self.elements.append((track_index, track_props, element))
        self.duration = max((_number(item[2]['e']) for item in self.elements), default=0)
        if self.duration <= 0:
            raise ValueError('编辑时间线没有可导出的内容')

    def _row(self, element: dict, expected: str):
        row = self.asset_lookup(_asset_id(element))
        same_production = bool(row and self.production_id and row.get('production_id') == self.production_id)
        if not row or (row['project_id'] != self.project_id and not same_production):
            raise ValueError('编辑时间线引用了不存在或属于其他项目的素材')
        kind = row['kind']
        if expected == 'video' and kind != 'video':
            raise ValueError('视频元素引用的不是视频素材')
        if expected == 'audio' and kind != 'audio':
            raise ValueError('音频元素引用的不是音频素材')
        if expected == 'image' and kind != 'image':
            raise ValueError('图片元素引用的不是图片素材')
        return row

    def _write_ass(self, text_elements: list[tuple[int, dict, dict]]) -> Path | None:
        if not text_elements:
            return None
        header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {self.width}
PlayResY: {self.height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Microsoft YaHei,42,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,2,0,2,30,30,28,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
        events = []
        for track_index, track_props, element in text_elements:
            props = element.get('props') or {}
            fade = _fade(element)
            start, end = _number(element['s']), _number(element['e'])
            if element.get('type') == 'caption':
                font = track_props.get('font') or {}
                colors = track_props.get('colors') or {}
                size = round(_clamp(font.get('size'), 8, 300, 42))
                fill = _ass_color(colors.get('text', '#ffffff'))
                outline = _ass_color(colors.get('outlineColor', '#000000'))
                x, y, align = self.width / 2, self.height - max(24, self.height * .045), 2
                text = element.get('t') or props.get('text') or ''
                font_name = str(font.get('family') or 'Microsoft YaHei').replace(',', ' ')
                bold = 1 if _number(font.get('weight'), 700) >= 600 else 0
            else:
                size = round(_clamp(props.get('fontSize'), 8, 300, 48))
                fill = _ass_color(props.get('fill', '#ffffff'), _clamp(props.get('opacity'), 0, 1, 1))
                outline = _ass_color(props.get('stroke', '#000000'))
                x, y, align = _number(props.get('x'), self.width / 2), _number(props.get('y'), self.height / 2), 7
                text = props.get('text') or ''
                font_name = str(props.get('fontFamily') or 'Microsoft YaHei').replace(',', ' ')
                bold = 1 if _number(props.get('fontWeight'), 400) >= 600 else 0
            tags = [f'\\an{align}', f'\\pos({x:.1f},{y:.1f})', f'\\fs{size}', f'\\fn{font_name}', f'\\c{fill}', f'\\3c{outline}', f'\\b{bold}']
            rotation = _number(props.get('rotation'))
            if rotation:
                tags.append(f'\\frz{rotation:.2f}')
            fade_in, fade_out = fade['videoIn'], fade['videoOut']
            if fade_in or fade_out:
                tags.append(f'\\fad({round(fade_in * 1000)},{round(fade_out * 1000)})')
            events.append(f'Dialogue: {track_index},{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{{{"".join(tags)}}}{_ass_text(text)}')
        path = self.work / 'editor_text.ass'
        path.write_text(header + '\n'.join(events) + '\n', encoding='utf-8-sig')
        return path

    def compile(self, executable: str, output: Path) -> RenderPlan:
        media = [(ti, tp, el) for ti, tp, el in self.elements if el.get('type') in MEDIA_TYPES and not tp.get('muted')]
        text = [(ti, tp, el) for ti, tp, el in self.elements if el.get('type') in {'text', 'caption'} and not tp.get('hidden')]
        infos: dict[str, dict] = {}
        input_indexes: dict[str, int] = {}
        args = [executable, '-y']
        for _, _, element in media:
            element_id = str(element.get('id'))
            kind = str(element.get('type'))
            row = self._row(element, kind)
            path = Path(row['absolute_path'])
            if kind == 'image':
                args += ['-loop', '1', '-i', str(path)]
                infos[element_id] = {'has_audio': False}
            else:
                if kind == 'audio' and (element.get('props') or {}).get('loop'):
                    args += ['-stream_loop', '-1']
                args += ['-i', str(path)]
                infos[element_id] = self.probe_media(path)
            input_indexes[element_id] = len(input_indexes)

        visual = [(ti, tp, el) for ti, tp, el in media if el.get('type') in VISUAL_TYPES and not tp.get('hidden')]
        visual.sort(key=lambda item: (_number(item[2].get('zIndex'), item[0]), item[0], _number(item[2].get('s'))))
        transition_in: dict[str, tuple[float, str, float]] = {}
        transition_out: dict[str, float] = {}
        for _, _, element in visual:
            transition = element.get('transition') or (element.get('props') or {}).get('transition') or {}
            if not transition:
                continue
            target = str(transition.get('toElementId') or '')
            target_element = next((item[2] for item in visual if str(item[2].get('id')) == target), None)
            kind = str(transition.get('kind') or '')
            amount = _number(transition.get('duration'), -1)
            if kind not in SUPPORTED_TRANSITIONS:
                raise ValueError(f'剪辑元素 {element.get("id")} 使用了不支持的转场：{kind or "缺失"}')
            if not target_element:
                raise ValueError(f'剪辑元素 {element.get("id")} 的转场目标不存在或不可见')
            if _number(target_element.get('s')) < _number(element.get('s')):
                raise ValueError('转场目标必须位于来源片段之后')
            target_duration = _number(target_element['e']) - _number(target_element['s'])
            max_amount = min(10, (_number(element['e']) - _number(element['s'])) / 2, target_duration / 2)
            if amount < .05 or amount > max_amount:
                raise ValueError(f'剪辑元素 {element.get("id")} 的转场时长无效')
            if target in transition_in:
                raise ValueError(f'剪辑元素 {target} 不能同时接收多个转场')
            transition_in[target] = (_number(element['e']) - amount, kind, amount)
            transition_out[str(element.get('id'))] = amount

        filters = [f'color=c={_color(self.project.get("backgroundColor"))}:s={self.width}x{self.height}:r=24:d={self.duration:.6f}[v0]']
        current_video = 'v0'
        for visual_index, (_, _, element) in enumerate(visual):
            element_id = str(element.get('id'))
            input_index = input_indexes[element_id]
            props = element.get('props') or {}
            start, end = _number(element['s']), _number(element['e'])
            duration = end - start
            rate = _clamp(props.get('playbackRate'), .25, 4, 1)
            source_in = max(0, _number(props.get('time')))
            info = infos[element_id]
            if element.get('type') == 'video' and source_in + duration * rate > _number(info.get('duration')) + .08:
                raise ValueError(f'视频片段 {element.get("name") or element_id} 超出素材时长')
            incoming = transition_in.get(element_id)
            effective_start = max(0, min(start, incoming[0])) if incoming else start
            preroll = start - effective_start
            effective_duration = duration + preroll
            frame = element.get('frame') or {}
            size = frame.get('size') or [self.width, self.height]
            width = round(_clamp(size[0] if len(size) > 0 else self.width, 1, 8192, self.width))
            height = round(_clamp(size[1] if len(size) > 1 else self.height, 1, 8192, self.height))
            x, y = _number(frame.get('x')), _number(frame.get('y'))
            chain = []
            if element.get('type') == 'video':
                chain += [f'trim=start={source_in:.6f}:end={source_in + duration * rate:.6f}', f'setpts=(PTS-STARTPTS)/{rate:.8g}']
                if preroll > 0:
                    chain.append(f'tpad=start_mode=clone:start_duration={preroll:.6f}')
            else:
                chain += [f'trim=duration={effective_duration:.6f}', 'setpts=PTS-STARTPTS']
            fit = str(element.get('objectFit') or 'cover')
            if fit == 'cover':
                chain += [f'scale={width}:{height}:force_original_aspect_ratio=increase', f'crop={width}:{height}']
            elif fit == 'contain':
                chain += [f'scale={width}:{height}:force_original_aspect_ratio=decrease', f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black@0']
            else:
                chain.append(f'scale={width}:{height}')
            chain += _media_filter(props.get('mediaFilter'))
            rotation = _number(frame.get('rotation'), _number(props.get('rotation')))
            if rotation:
                chain.append(f'rotate={rotation:.6f}*PI/180:c=none:ow=rotw(iw):oh=roth(ih)')
            chain.append('format=rgba')
            opacity = _clamp(props.get('opacity'), 0, 1, 1)
            if opacity < .999:
                chain.append(f'colorchannelmixer=aa={opacity:.6f}')
            fade = _fade(element)
            transition_out_duration = transition_out.get(element_id, 0)
            fade_in = max(fade['videoIn'], incoming[2] if incoming else 0)
            fade_out = max(fade['videoOut'], transition_out_duration)
            if fade_in:
                chain.append(f'fade=t=in:st=0:d={fade_in:.6f}:alpha=1')
            if fade_out:
                chain.append(f'fade=t=out:st={max(0, effective_duration - fade_out):.6f}:d={fade_out:.6f}:alpha=1')
            chain.append(f'setpts=PTS-STARTPTS+{effective_start:.6f}/TB')
            element_label = f've{visual_index}'
            filters.append(f'[{input_index}:v]{",".join(chain)}[{element_label}]')
            next_video = f'v{visual_index + 1}'
            filters.append(f'[{current_video}][{element_label}]overlay=x={x:.3f}:y={y:.3f}:eof_action=pass:repeatlast=0:format=auto[{next_video}]')
            current_video = next_video

        ass = self._write_ass(text)
        if ass:
            filters.append(f'[{current_video}]subtitles=filename={ass.name}[vtext]')
            current_video = 'vtext'
        filters.append(f'[{current_video}]fps=24,format=yuv420p[vout]')

        audio_labels = []
        for _, track_props, element in media:
            if element.get('type') not in {'audio', 'video'} or track_props.get('muted'):
                continue
            element_id = str(element.get('id'))
            if element.get('type') == 'video' and not infos[element_id].get('has_audio'):
                continue
            props = element.get('props') or {}
            if props.get('muted'):
                continue
            start, end = _number(element['s']), _number(element['e'])
            duration = end - start
            rate = _clamp(props.get('playbackRate'), .25, 4, 1)
            source_in = max(0, _number(props.get('time')))
            source_end = source_in + duration * rate
            if not props.get('loop') and source_end > _number(infos[element_id].get('duration')) + .08:
                raise ValueError(f'音频片段 {element.get("name") or element_id} 超出素材时长')
            chain = [f'atrim=start={source_in:.6f}:end={source_end:.6f}', 'asetpts=PTS-STARTPTS', *_atempo(rate), 'aresample=48000']
            volume = _clamp(props.get('volume'), 0, 2, 1)
            chain.append(_volume_filter(element, volume, duration))
            fade = _fade(element)
            if fade['audioIn']:
                chain.append(f'afade=t=in:st=0:d={fade["audioIn"]:.6f}')
            if fade['audioOut']:
                chain.append(f'afade=t=out:st={max(0, duration - fade["audioOut"]):.6f}:d={fade["audioOut"]:.6f}')
            if start:
                chain.append(f'adelay={round(start * 1000)}:all=1')
            label = f'a{len(audio_labels)}'
            filters.append(f'[{input_indexes[element_id]}:a]{",".join(chain)}[{label}]')
            audio_labels.append(label)
        if audio_labels:
            joined = ''.join(f'[{label}]' for label in audio_labels)
            filters.append(f'{joined}amix=inputs={len(audio_labels)}:duration=longest:normalize=0,alimiter=limit=.95,atrim=duration={self.duration:.6f}[aout]')
        else:
            filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={self.duration:.6f}[aout]')

        args += [
            '-filter_complex', ';'.join(filters),
            '-map', '[vout]', '-map', '[aout]', '-t', f'{self.duration:.6f}',
            '-c:v', 'libx264', '-preset', 'fast', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-ac', '2', '-ar', '48000', '-movflags', '+faststart', str(output),
        ]
        return RenderPlan(args, self.duration, len(visual), len(audio_labels), len(text))
