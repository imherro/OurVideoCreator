"""Doubao Speech V3 adapter for stable character dialogue voices."""
from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path

import httpx

from .. import store as s
from .. import provider_egress
from . import common

DEFAULT_URL = 'https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse'
DEFAULT_RESOURCE_ID = 'seed-tts-2.0'
DEFAULT_VOICE_TYPE = 'zh_female_vv_uranus_bigtts'
VALID_FORMATS = {'mp3', 'ogg_opus'}
VALID_SAMPLE_RATES = {8000, 16000, 22050, 24000, 32000, 44100, 48000}


def _headers(provider):
    key = str(provider.get('api_key') or '').strip()
    if not key:
        raise ValueError('豆包语音尚未配置 Speech API Key')
    return {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        'X-Api-Key': key,
        'X-Api-Resource-Id': str(provider.get('resource_id') or DEFAULT_RESOURCE_ID),
        'X-Api-Request-Id': str(uuid.uuid4()),
    }


def synthesize(worker, job, provider):
    inp = job['input']
    text = str(inp.get('prompt') or '').strip()
    if not text:
        raise ValueError('请输入试听或对白文本')
    if len(text.encode('utf-8')) > 1024:
        raise ValueError('单条对白不能超过 1024 字节，请拆成多句生成')
    voice_type = str(inp.get('voice_type') or provider.get('model') or DEFAULT_VOICE_TYPE).strip()
    if not voice_type:
        raise ValueError('请为角色选择豆包语音音色 ID')
    params = {**(provider.get('parameters') or {}), **(inp.get('parameters') or {})}
    audio_format = str(params.get('format') or 'mp3')
    if audio_format not in VALID_FORMATS:
        raise ValueError('豆包语音输出格式只支持 mp3 或 ogg_opus')
    sample_rate = int(params.get('sample_rate') or 24000)
    if sample_rate not in VALID_SAMPLE_RATES:
        raise ValueError('豆包语音采样率无效')
    speech_rate = max(-50, min(100, int(params.get('speech_rate') or 0)))
    loudness_rate = max(-50, min(100, int(params.get('loudness_rate') or 0)))
    additions = {'disable_markdown_filter': True, 'enable_latex_tn': False}
    emotion = str(params.get('emotion') or inp.get('emotion') or '').strip()
    raw_contexts = params.get('context_texts')
    if isinstance(raw_contexts, str):
        context_texts = [raw_contexts.strip()] if raw_contexts.strip() else []
    elif isinstance(raw_contexts, list):
        context_texts = [str(item).strip() for item in raw_contexts if str(item).strip()]
    else:
        context_texts = []
    if not context_texts and emotion:
        context_texts = [f'请以{emotion}的情绪和语气演绎下面这句影片对白。']
    if context_texts:
        # Seed TTS 2.0 accepts natural-language performance direction through
        # additions.context_texts. The former implementation put an arbitrary
        # Chinese sentence in the legacy emotion enum, which was ignored.
        additions['context_texts'] = [item[:500] for item in context_texts[:1]]
    body = {
        'user': {'uid': 'anying-studio'},
        'req_params': {
            'text': text,
            'speaker': voice_type,
            'sample_rate': sample_rate,
            'audio_params': {
                'format': audio_format,
                'speech_rate': speech_rate,
                'loudness_rate': loudness_rate,
                'bit_rate': int(params.get('bit_rate') or 64000),
            },
            'additions': json.dumps(additions, ensure_ascii=False),
        },
    }
    suffix = '.ogg' if audio_format == 'ogg_opus' else '.' + audio_format
    path = s.DATA / (s.uid('doubao-tts-') + suffix)
    worker.progress(job, '豆包语音正在合成固定角色音色')
    try:
        chunks = []
        with provider_egress.client(origin=provider['url'],timeout=httpx.Timeout(120, connect=15), headers=_headers(provider), trust_env=True) as client:
            with client.stream('POST', str(provider.get('url') or DEFAULT_URL), json=body) as response:
                if not response.is_success:
                    response.read()
                    common.checked(response)
                for line in response.iter_lines():
                    if worker.cancelled(job):
                        raise InterruptedError()
                    if not line.startswith('data:'):
                        continue
                    try:
                        event = json.loads(line[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    code = event.get('code', 0)
                    if code not in (0, 20000000):
                        raise ValueError('豆包语音生成失败：' + str(event.get('message') or code)[:500])
                    if event.get('data'):
                        chunks.append(base64.b64decode(event['data']))
        if not chunks:
            raise ValueError('豆包语音没有返回音频数据')
        path.write_bytes(b''.join(chunks))
        requested_name = str(inp.get('output_name') or f'{inp.get("character_name") or "角色"} · 固定音色试听')
        name = str(Path(requested_name).with_suffix(suffix))
        asset = common.register(job, path, name, category='voice')
        return {
            'assets': [asset],
            'voiceType': voice_type,
            'voiceVersion': inp.get('voice_version'),
            'dialogue': inp.get('dialogue'),
        }
    finally:
        path.unlink(missing_ok=True)


def verify(provider):
    if not str(provider.get('api_key') or '').strip():
        raise ValueError('请先填写豆包语音 Speech API Key')
    if not str(provider.get('resource_id') or DEFAULT_RESOURCE_ID).strip():
        raise ValueError('请填写豆包语音 Resource ID')
    return {'status': 'configured', 'message': '语音凭证和资源参数已保存；点击角色试听会进行首次计费调用'}
