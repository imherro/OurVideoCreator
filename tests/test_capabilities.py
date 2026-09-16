import pytest
from backend.capabilities import maestro_model,validate_media

def catalogue():
    return maestro_model({'model_type':'ltx','name':'LTX','is_downloaded':True,'fps':25,'generates_audio':True,
        'director':{'video':{'short_film_story':{'compatible':True}},'clip_min_frames':17,'clip_frame_step':8}})

def test_engine_director_capabilities_override_legacy_video_flags():
    model=catalogue()
    assert model['kinds']==['video']
    assert model['capabilities']['fps']==25
    assert model['capabilities']['audio_output']
    validate_media(model,'video',{'frames':49,'asset_ids':['reference']})

@pytest.mark.parametrize('frames',[0,16,50,49.5,True])
def test_invalid_frame_count_fails_before_submission(frames):
    with pytest.raises(ValueError):validate_media(catalogue(),'video',{'frames':frames})

def test_uninstalled_and_excess_references_rejected():
    model=catalogue()
    with pytest.raises(ValueError,match='最多支持 1'):validate_media(model,'video',{'frames':49,'asset_ids':['a','b']})
    model['installed']=False
    with pytest.raises(ValueError,match='Maestro API 中不可用'):validate_media(model,'video',{'frames':49})

def test_h3_uses_its_own_frame_offset():
    model=catalogue();model['capabilities'].update(min_frames=124,max_frames=345,frame_step=17)
    for frames in (124,141,345):validate_media(model,'video',{'frames':frames})
    with pytest.raises(ValueError):validate_media(model,'video',{'frames':137})
