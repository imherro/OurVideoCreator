"""Normalize engine-reported capabilities to the operations our adapter supports."""
def maestro_model(model):
    director=model.get('director') or {}
    image=bool((director.get('image') or {}).get('compatible'))
    video=any(v.get('compatible') for v in (director.get('video') or {}).values()) or bool(model.get('is_i2v') or model.get('is_t2v'))
    return {'id':model['model_type'],'name':model.get('name',model['model_type']),
        'kinds':(['image'] if image else [])+(['video'] if video else []),
        'installed':model.get('is_downloaded'),
        'capabilities':{'fps':model.get('fps'), 'min_frames':director.get('clip_min_frames'),
            'max_frames':director.get('clip_max_frames'),'frame_step':director.get('clip_frame_step'),
            'image_reference':bool(model.get('supports_ref_images') or model.get('supports_image_edit') or video),
            'requires_reference':bool(model.get('requires_image_reference')),
            'end_frame':bool(video and model.get('supports_end_frame')),
            'max_references':1 if video else director.get('max_image_refs'),
            'audio_output':bool(model.get('generates_audio'))}}

def validate_media(model,kind,inp):
    if kind not in model['kinds']:raise ValueError('所选模型不支持当前节点类型，请选择适用模型')
    if model.get('installed') is False:raise ValueError('所选模型在已连接的 Maestro API 中不可用，请由该服务管理员安装所需权重')
    cap=model['capabilities'];refs=inp.get('asset_ids',[])
    if inp.get('end_asset_id') and (kind!='video' or not cap.get('end_frame')):raise ValueError('所选模型不支持尾帧控制')
    if cap.get('requires_reference') and not refs:raise ValueError('此模型需要参考图，请先引用图像素材')
    if refs and not cap.get('image_reference'):raise ValueError('此模型不支持参考图')
    if cap.get('max_references') and len(refs)>cap['max_references']:raise ValueError(f'当前适配器最多支持 {cap["max_references"]} 张参考图，请移除多余引用')
    if kind=='video':
        frames=inp.get('frames',121)
        if not isinstance(frames,int) or isinstance(frames,bool):raise ValueError('视频帧数必须为整数')
        minimum=cap.get('min_frames') or 1;maximum=cap.get('max_frames');step=cap.get('frame_step')
        if frames<minimum or (maximum and frames>maximum):raise ValueError(f'帧数必须在 {minimum} 到 {maximum or "模型支持的最大值"} 范围内')
        if step and (frames-minimum)%step:raise ValueError(f'此模型帧数从 {minimum} 开始，每次增加 {step}，例如 {minimum}、{minimum+step}')
