"""Resolve the effective locked voice without copying state-owned audio records."""
from copy import deepcopy


def voice_snapshot(profile):
    return {key:deepcopy(value) for key,value in (profile or {}).items() if key not in ('lockedVersions','defaultVersion')}


def locked_versions(profile):
    profile=profile or {};versions=deepcopy(profile.get('lockedVersions') or {})
    if profile.get('status')=='locked':versions[str(profile['version'])]=voice_snapshot(profile)
    return versions


def effective_profile(profile):
    profile=profile or {};selected=profile.get('defaultVersion')
    if selected is None:return profile
    result=locked_versions(profile).get(str(selected))
    if not result:raise ValueError('默认音色版本不存在，请重新选择已锁定版本')
    return result


def voice_document(rows):
    from .collaboration_document import object_content
    visual={'cards':{},'versions':{}};profiles={}
    for row in rows:
        if row['kind']!='visual_card':continue
        content=object_content(row);card=content['card'];visual['cards'][card['id']]=card
        visual['versions'].update(content['versions'])
        if content.get('voice_profile'):profiles[card['id']]=content['voice_profile']
    return {'filmBible':{'visual':visual,'voices':{'profiles':profiles}}}


def voice_card_id(document,shot,dialogue):
    film=document.get('filmBible') or {};visual=film.get('visual') or {}
    cards=visual.get('cards') or {};versions=visual.get('versions') or {}
    cid=dialogue.get('characterCardId') or '';card=cards.get(cid) or {}
    base=card.get('parentCardId') if card.get('kind')=='character_state' else cid
    if card.get('kind')=='character_state':return cid if card.get('voiceVersion') is not None else base
    choices=set()
    for binding in (shot.get('assetBindings') or {}).get('characters') or []:
        sid=(versions.get(binding.get('versionId')) or {}).get('cardId');state=cards.get(sid) or {}
        if state.get('kind')=='character_state' and state.get('parentCardId')==base and state.get('voiceVersion') is not None:
            choices.add(sid)
    if len(choices)>1:raise ValueError('同一镜头绑定了多个不同音色的角色状态，请明确说话状态')
    return next(iter(choices),base or cid)


def resolved_voice(document,shot,dialogue):
    cid=voice_card_id(document,shot,dialogue);film=document.get('filmBible') or {}
    cards=(film.get('visual') or {}).get('cards') or {};profiles=(film.get('voices') or {}).get('profiles') or {}
    card=cards.get(cid) or {}
    if card.get('kind')=='character_state' and card.get('voiceVersion') is not None:
        profile=locked_versions(profiles.get(card.get('parentCardId'))).get(str(card['voiceVersion']))
        if not profile:raise ValueError('角色状态选择的音色版本不存在，请重新选择')
        return cid,profile
    return cid,effective_profile(profiles.get(cid))


def shot_voice_signature(document,shot):
    result=[]
    for line in shot.get('dialogues') or []:
        if not str(line.get('text') or '').strip():continue
        try:
            cid,profile=resolved_voice(document,shot,line)
            result.append([cid,*[profile.get(key) for key in ('status','version','model_id','voiceType','referenceAssetId','referenceVersion')]])
        except ValueError as error:result.append(['invalid',str(error)])
    return result
