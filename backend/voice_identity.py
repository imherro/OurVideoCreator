"""Compare voice auditions using canonical history, never a caller fingerprint."""
import json
from fastapi import HTTPException
from .collaboration_document import object_content


def identity(profile):
    profile=profile or {}
    parameters=profile.get('parameters') or {}
    return (profile.get('model_id'),str(profile.get('voiceType') or '').strip(),
            str(profile.get('previewText') or '').strip(),parameters.get('speechRate') or 0,
            str(parameters.get('emotion') or '').strip())


def original_profile(connection, target):
    historical=connection.execute('SELECT snapshot FROM collaboration_history WHERE object_id=%s AND revision=%s',
                                  (target['id'],target['revision'])).fetchone()
    if not historical:
        raise HTTPException(409,'音色试听缺少原对象快照，请重新生成')
    snapshot=historical['snapshot']
    if isinstance(snapshot,str):snapshot=json.loads(snapshot)
    return object_content(snapshot).get('voice_profile')


def validate_parameters(connection,target,parameters):
    profile=original_profile(connection,target)
    settings=(profile or {}).get('parameters') or {}
    for saved,wire,default in [('speechRate','speech_rate',0),('emotion','emotion','')]:
        if (settings.get(saved) or default)!=(parameters.get(wire) or default):
            raise HTTPException(422,'试听必须使用角色当前保存的语速和情绪；请调整设置或平台允许参数')


def validate_adoption(connection,target,profile):
    if identity(original_profile(connection,target))!=identity(profile):
        raise HTTPException(409,'试听文本、语速或情绪已变化，旧试听不能确认为当前音色，请重新生成')


def validate_lock(connection,row,content):
    before=object_content(row).get('voice_profile') or {}
    profile=content.get('voice_profile') or {}
    if profile.get('status')!='locked' or before.get('status')=='locked':return
    # A generated audition can only be confirmed after the existing explicit
    # adoption path. No new snapshot field or rewrite of old jobs is required.
    if not profile.get('previewAssetId'):return  # Preserve historical preset-only profiles.
    job=connection.execute('SELECT * FROM jobs WHERE id=%s AND production_id=%s',
                           (profile.get('generationJobId'),row['production_id'])).fetchone()
    from . import store as s
    job=s.unpack(job) if job else {}
    binding=job.get('collaboration') or {}
    if (job.get('status')!='succeeded' or binding.get('mode')!='voice' or not binding.get('adopted')
        or binding.get('target',{}).get('id')!=row['id']
        or profile['previewAssetId'] not in {a.get('id') for a in (job.get('result') or {}).get('assets',[]) if a.get('kind')=='audio'}):
        raise HTTPException(409,'请先在任务中心明确采纳当前角色的试听，再锁定音色')
    validate_adoption(connection,binding['target'],profile)
