"""Validate immutable audition history and state selection inside object commands."""
from fastapi import HTTPException
from .voice_resolution import locked_versions,voice_snapshot


def metadata_only(before,after):
    return bool(before and after and voice_snapshot(before)==voice_snapshot(after))


def validate_library(before,after):
    before=before or {};after=after or {}
    if not any(key in profile for profile in (before,after) for key in ('lockedVersions','defaultVersion')):return
    stored=after.get('lockedVersions')
    if not isinstance(stored,dict) or not all(isinstance(item,dict) for item in stored.values()):
        raise HTTPException(422,'声音历史必须是版本快照映射')
    if type(after.get('version')) is not int or after['version']<1 or after.get('status') not in ('draft','locked'):
        raise HTTPException(422,'声音版本或状态无效')
    if not isinstance(after.get('name',''),str) or len(after.get('name',''))>100:
        raise HTTPException(422,'声音版本名称不超过100字')
    history=locked_versions(before)
    if after.get('status')=='locked':
        key=str(after.get('version'));current=voice_snapshot(after)
        from .voice_identity import is_reference_confirmation
        if key in history and history[key]!=current and not is_reference_confirmation(before,after):
            raise HTTPException(422,'已锁定声音版本不可覆盖')
        history[key]=current
    if after.get('lockedVersions')!=history:
        raise HTTPException(422,'声音库必须保留已确认历史，不能伪造或删除锁定版本')
    selected=after.get('defaultVersion')
    if selected is not None and (type(selected) is not int or str(selected) not in history):
        raise HTTPException(422,'默认声音须选择已锁定版本')
    if before.get('defaultVersion') is not None and selected is None:
        raise HTTPException(422,'已有默认音色不能静默取消，请明确选择版本')
    if after.get('status')=='draft' and str(after.get('version')) in history:
        raise HTTPException(422,'新试听须使用新的声音版本号')


def validate_state(connection,production_id,content):
    card=content['card'];selected=card.get('voiceVersion')
    if selected is None:return
    if card.get('kind')!='character_state' or type(selected) is not int or selected<1:
        raise HTTPException(422,'仅角色状态可选择已锁定声音版本')
    from .collaboration_document import object_content
    parent=connection.execute('''SELECT content FROM collaboration_objects WHERE production_id=%s
        AND kind='visual_card' AND content::jsonb->'card'->>'id'=%s AND NOT deleted''',
        (production_id,card.get('parentCardId'))).fetchone()
    profile=object_content(parent).get('voice_profile') if parent else None
    if str(selected) not in locked_versions(profile):
        raise HTTPException(422,'基础角色没有这个已锁定声音版本')
    if content.get('voice_profile'):
        raise HTTPException(422,'状态音色引用基础角色锁定版本，不能同时复制试听记录')
