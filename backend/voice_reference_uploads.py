"""Admit local reference audio without registering a TTS voice or changing a card."""
import math
import subprocess
from pathlib import Path
from fastapi import HTTPException
from . import store as s
from .media import probe,ffmpeg_executable
from .motion_references import file_hash

MAX_BYTES=30*1024**2
MAX_SECONDS=120


def validate_file(path):
    path=Path(path)
    if path.suffix.lower() not in ('.mp3','.wav') or not 0<path.stat().st_size<=MAX_BYTES:
        raise ValueError('声音样本仅支持不超过30 MB的非空MP3/WAV')
    data=probe(path);duration=float(data.get('duration') or 0)
    if not data.get('has_audio') or data.get('video_codec') or not math.isfinite(duration) or not 0<duration<=MAX_SECONDS:
        raise ValueError('声音样本须为120秒以内的可播放纯音频；模型限制在提交时另行检查')
    decoded=subprocess.run([ffmpeg_executable(),'-v','error','-xerror','-f',path.suffix[1:].lower(),
        '-i',str(path),'-map','0:a:0','-vn','-f','null','-'],capture_output=True,timeout=30,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    if decoded.returncode:raise ValueError('声音样本真实格式不符或无法完整解码，请重新导出MP3/WAV')
    return data


def uploaded(profile):
    return isinstance((profile or {}).get('source'),dict) and profile['source'].get('type')=='uploaded'


def require_tts(profile):
    if uploaded(profile):raise ValueError('上传声音仅提供音色参考，不能自动逐句合成；请选择音色样本参考')


def validate_profile(c,production_id,before,after):
    before=before or {};after=after or {}
    source=after.get('source')
    if source is not None and (not isinstance(source,dict) or source.get('type') not in ('uploaded','doubao_tts')):
        raise HTTPException(422,'声音来源无效')
    from .voice_identity import identity
    if (uploaded(before) or uploaded(after)) and before and identity(before)!=identity(after):
        if type(after.get('version')) is not int or after['version']<=before.get('version',0):
            raise HTTPException(422,'声音来源或样本变化须建立新的声音版本')
    if not uploaded(after):return
    if type(after.get('version')) is not int or after['version']<1 or after.get('status') not in ('draft','locked'):
        raise HTTPException(422,'上传声音版本或状态无效')
    aid=source.get('originalAssetId')
    row=c.execute('''SELECT * FROM assets WHERE id=%s AND production_id=%s
        AND NOT EXISTS(SELECT 1 FROM deleted_items WHERE kind='asset' AND item_id=assets.id)''',
        (aid,production_id)).fetchone()
    asset=s.unpack(row) if row else {}
    admission=(asset.get('metadata') or {}).get('voice_reference') or {}
    if asset.get('kind')!='audio' or not admission.get('authorized_at') or source.get('authorizedAt')!=admission['authorized_at']:
        raise HTTPException(422,'请先校验本作品声音样本并确认使用权')
    if after.get('generationJobId') or after.get('previewAssetId') not in (None,aid):
        raise HTTPException(422,'上传声音不能关联生成试听记录或其他样本')
    if after.get('status')=='draft' and (after.get('referenceAssetId') or after.get('referenceVersion') is not None):
        raise HTTPException(422,'上传声音草稿须先试听再明确锁定，不能携带确认标记')
    if after.get('status')=='locked':
        if not uploaded(before) or identity(before)!=identity(after) or before.get('version')!=after['version'] or before.get('previewAssetId')!=aid:
            raise HTTPException(422,'请先保存上传声音草稿并试听，再明确锁定')
        if after.get('referenceAssetId')!=aid or after.get('previewAssetId')!=aid or after.get('referenceVersion')!=after['version']:
            raise HTTPException(422,'锁定声音参考与上传样本版本不一致')
        path=(s.ASSETS/asset['path']).resolve()
        if not path.is_relative_to(s.ASSETS.resolve()) or not path.is_file() or file_hash(path)!=admission.get('sha256'):
            raise HTTPException(422,'声音样本文件已丢失或变化，请重新上传')
