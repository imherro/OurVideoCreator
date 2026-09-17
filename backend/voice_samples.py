"""Confirmed character timbre references; no dialogue mixing or automatic adoption."""
import base64
import math
import subprocess
from . import store as s
from .media import probe, ffmpeg_executable
from .providers import common

MODES={'voice_sample','full_dialogue'}

def dialogue_mode(document,shot):
    mode=(shot or {}).get('dialogueMode') or document.get('dialogueMode') or 'full_dialogue'
    if mode not in MODES:raise ValueError('对白生成方式无效')
    return mode


def compile_samples(document,shot,project_id,caps):
    from .motion_references import file_hash
    profiles=((document.get('filmBible') or {}).get('voices') or {}).get('profiles') or {}
    samples=[];seen=set();media={}
    for line in shot.get('dialogues') or []:
        if not str(line.get('text') or '').strip():continue
        cid=line.get('characterCardId');name=line.get('characterName') or '角色'
        if cid in seen:continue
        from .voice_resolution import resolved_voice
        voice_card,profile=resolved_voice(document,shot,line);aid=profile.get('referenceAssetId')
        if not cid or profile.get('status')!='locked' or not aid or profile.get('referenceVersion')!=profile.get('version'):
            raise ValueError(f'{name}尚未确认当前版本的声音样本，请试听并锁定角色声音参考')
        if aid not in media:
            if len(media)>=caps['max_audio']:raise ValueError('音色样本数量超过平台上限，不会截断或混合')
            asset=common.assets_by_ids({'project_id':project_id},[aid])[0]
            path=(s.ASSETS/asset['path']).resolve()
            if asset['kind']!='audio' or not path.is_relative_to(s.ASSETS.resolve()) or not path.is_file():
                raise ValueError('声音样本已丢失或不是音频')
            if path.suffix.lower() not in ('.mp3','.wav') or path.stat().st_size>15*1024**2:
                raise ValueError('声音样本需为不超过15 MB的MP3或WAV')
            data=probe(path);duration=float(data.get('duration') or 0)
            if not data.get('has_audio') or data.get('video_codec') or not math.isfinite(duration) or not 2<=duration<=caps['max_reference_duration']:
                raise ValueError(f"声音样本需为2–{caps['max_reference_duration']}秒的纯音频")
            # Force the advertised container so renamed non-MP3/WAV files are not accepted.
            decoded=subprocess.run([ffmpeg_executable(),'-v','error','-xerror','-f',path.suffix[1:].lower(),
                '-i',str(path),'-map','0:a:0','-vn','-f','null','-'],capture_output=True,timeout=60,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if decoded.returncode:raise ValueError('声音样本格式不符或无法完整解码，请重新导出MP3/WAV')
            media[aid]={'duration':duration,'sha256':file_hash(path),'name':asset['name']}
        if (profile.get('source') or {}).get('type')=='uploaded':
            asset=common.assets_by_ids({'project_id':project_id},[aid])[0]
            receipt=(asset.get('metadata') or {}).get('voice_reference') or {}
            if (profile['source'].get('originalAssetId')!=aid or not receipt.get('authorized_at')
                or profile['source'].get('authorizedAt')!=receipt['authorized_at'] or media[aid]['sha256']!=receipt.get('sha256')):
                raise ValueError('上传声音样本与已确认文件不一致，请重新上传并确认')
        samples.append({'characterCardId':cid,'characterName':name,'voiceCardId':voice_card,'voiceVersion':profile['version'],
                        **({'source':profile['source']['type']} if profile.get('source') else {}),
                        'voiceType':profile.get('voiceType',''),'assetId':aid,'purpose':'timbre_only',
                        'media':media[aid],'index':list(media).index(aid)+1})
        seen.add(cid)
    if sum(item['duration'] for item in media.values())>caps['max_reference_duration']:
        raise ValueError('声音样本总时长超过平台上限，不会自动裁剪')
    return samples


def submission_assets(job):
    from .motion_references import file_hash
    samples={item['assetId']:item for item in job['input'].get('voice_samples',[])}
    assets=common.assets_by_ids(job,list(samples))
    for asset in assets:
        path=(s.ASSETS/asset['path']).resolve()
        if not path.is_relative_to(s.ASSETS.resolve()) or not path.is_file() or file_hash(path)!=samples[asset['id']]['media']['sha256']:
            raise ValueError('声音样本在提交后变化，请重新提交')
    return assets


def sample_data_uri(asset):
    path=s.ASSETS/asset['path']
    return ('data:audio/wav;base64,' if path.suffix.lower()=='.wav' else 'data:audio/mpeg;base64,')+base64.b64encode(path.read_bytes()).decode('ascii')
