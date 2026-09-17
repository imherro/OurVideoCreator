import json
from .models import VISUAL_BIBLE_SCHEMA,BOUND_STORYBOARD_SCHEMA,VISUAL_EXTRACTOR_PROMPT,STORYBOARD_DIRECTOR_PROMPT
from .reuse import normalize_reusable_visual,visual_user_prompt
from .validate import normalize_bound_storyboard

def _json(text,label):
    value=text.strip()
    if value.startswith('```'):
        value=value[value.find('\n')+1:]
        if value.rstrip().endswith('```'):value=value.rstrip()[:-3].rstrip()
    starts=[position for position in (value.find('{'),value.find('[')) if position>=0]
    if not starts:raise ValueError(label+'没有返回 JSON 值')
    try:return json.JSONDecoder().raw_decode(value[min(starts):])[0]
    except json.JSONDecodeError as exc:raise ValueError(label+' JSON 格式无效') from exc

def _visual(value):
    if isinstance(value,list):return {'cards':value}
    if isinstance(value,dict) and not isinstance(value.get('cards'),list):
        for key in ('visual_bible','visualBible','entities'):
            if isinstance(value.get(key),list):return {'cards':value[key]}
    return value

def _contract(contracts, stage_id, system_prompt, response_schema):
    stage=next((item for item in contracts or [] if item.get('id')==stage_id),{})
    return stage.get('system_prompt') or system_prompt,stage.get('response_schema') or response_schema


def extract_storyboard(script,target_duration,provider_id,model_id,request,contracts=None,report=None,existing_visual=None):
    """One user action, two internal text passes. No media provider is called."""
    visual_system,visual_schema=_contract(contracts,'visual_bible',VISUAL_EXTRACTOR_PROMPT,VISUAL_BIBLE_SCHEMA)
    storyboard_system,storyboard_schema=_contract(contracts,'bound_storyboard',STORYBOARD_DIRECTOR_PROMPT,BOUND_STORYBOARD_SCHEMA)
    visual_user=visual_user_prompt(script,existing_visual)
    visual_text=request(visual_system,visual_user,visual_schema,'提取视觉圣经','visual_bible')
    try:
        bible,key_ids=normalize_reusable_visual(_visual(_json(visual_text,'视觉圣经')),existing_visual,provider_id,model_id);visual_repair_count=0
        if report:report('visual_bible','validated')
    except (ValueError,TypeError) as exc:
        if report:report('visual_bible','needs_repair',str(exc))
        repair=visual_user+'\n\n上次视觉圣经未通过校验：'+str(exc)+'\n请修正并输出完整 JSON。上次结果：\n'+visual_text[:24000]
        visual_text=request(visual_system,repair,visual_schema,'修正视觉圣经','visual_bible_repair')
        try:
            bible,key_ids=normalize_reusable_visual(_visual(_json(visual_text,'视觉圣经')),existing_visual,provider_id,model_id);visual_repair_count=1
            if report:report('visual_bible_repair','validated')
        except (ValueError,TypeError) as final:raise ValueError('视觉圣经修正后仍不符合要求：'+str(final)) from final
    allowed=[{'key':key,'kind':bible['cards'][card_id]['kind'],'name':bible['cards'][card_id]['name'],'spec':bible['versions'][version_id]['spec'],'invariants':bible['versions'][version_id]['invariants']} for key,(card_id,version_id) in key_ids.items()]
    duration=f'\n镜头总时长必须为 {target_duration} 秒，误差不超过 0.5 秒。' if target_duration else ''
    user='剧本：\n'+script+'\n\n只允许引用以下视觉卡：\n'+json.dumps(allowed,ensure_ascii=False)+duration
    text=request(storyboard_system,user,storyboard_schema,'基于视觉圣经拆解分镜','bound_storyboard')
    try:
        storyboard=normalize_bound_storyboard(_json(text,'分镜'),bible,key_ids,target_duration);repair_count=0
        if report:report('bound_storyboard','validated')
    except (ValueError,TypeError) as exc:
        if report:report('bound_storyboard','needs_repair',str(exc))
        repair=user+'\n\n上次分镜未通过绑定校验：'+str(exc)+'\n请保持剧情并修正完整 JSON。上次结果：\n'+text[:24000]
        text=request(storyboard_system,repair,storyboard_schema,'修正分镜视觉绑定','bound_storyboard_repair')
        try:
            storyboard=normalize_bound_storyboard(_json(text,'分镜'),bible,key_ids,target_duration);repair_count=1
            if report:report('bound_storyboard_repair','validated')
        except (ValueError,TypeError) as final:raise ValueError('分镜修正后仍不符合要求：'+str(final)) from final
    return {'text':json.dumps(storyboard,ensure_ascii=False),'filmBible':{'visual':bible},**storyboard,
      'repair_count':visual_repair_count+repair_count,'visual_repair_count':visual_repair_count,'storyboard_repair_count':repair_count}
