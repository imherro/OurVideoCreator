import json,time
import pytest
from backend import store as s
from backend.generation_policy import (default_model_pool,default_platform_policy,
    require_model_in_pool,resolve_generation_target,validate_generation_policy,
    validate_model_pool,validate_policy_in_pool)
from backend.project_schema import CURRENT_SCHEMA_VERSION,migrate_document,new_document

def test_legacy_migration_is_lossless_and_idempotent():
    old={'nodes':[{'id':'n'}],'edges':[{'id':'e'}],'shots':[{'id':'shot-001'}],
         'timeline':[{'id':'clip'}],'characters':[{'name':'旧角色'}],'editor':{'timeline':{'tracks':[]}},'custom':{'kept':True}}
    migrated=migrate_document(old)
    assert migrated['schemaVersion']==CURRENT_SCHEMA_VERSION
    assert migrated['nodes']==old['nodes'] and migrated['edges']==old['edges']
    assert migrated['shots'][0]['id']==old['shots'][0]['id'] and migrated['shots'][0]['uid'].startswith('shot-')
    assert migrated['timeline']==old['timeline']
    assert migrated['editor']==old['editor'] and migrated['characters']==old['characters']
    assert migrated['custom']==old['custom']
    assert migrated['filmBible']=={'visual':{'cards':{},'versions':{}},'continuity':{},'style':{},'styleVersion':1,'story':{},'voices':{'profiles':{}}}
    assert migrated['generationPolicy']=={'text':None,'image':None,'video':None}
    assert migrated['videoResolution']=='720p'
    assert migrated['videoRatio']=='16:9'
    assert migrated['videoDuration']==-1
    assert migrated['videoFormat']=='mp4'
    assert migrate_document(migrated)==migrated
    assert migrate_document(old)['shots'][0]['uid']==migrated['shots'][0]['uid']
    assert 'schemaVersion' not in old

@pytest.mark.parametrize('version',[CURRENT_SCHEMA_VERSION+1,-1,1.5,True,'1'])
def test_invalid_or_future_schema_is_rejected(version):
    message='更新版本' if version==CURRENT_SCHEMA_VERSION+1 else '版本无效'
    with pytest.raises(ValueError,match=message):
        migrate_document({'schemaVersion':version,'nodes':[]})

def test_generation_policy_precedence_requires_explicit_external_target():
    providers=[{'id':kind,'kind':kind,'is_default':True} for kind in ('text','image','video')] + [{'id':'special','kind':'image'}]
    policy=default_platform_policy(providers)
    assert resolve_generation_target('image',None,policy,providers)['model_id']=='image'
    override={'mode':'override','model_id':'special'}
    assert resolve_generation_target('image',override,policy,providers)=={'model_id':'special','source':'override'}
    with pytest.raises(ValueError,match='不会自动选择'):
        resolve_generation_target('image',None,{'text':None,'image':None,'video':None},providers)
    with pytest.raises(ValueError,match='自动切换'):
        resolve_generation_target('video',None,{'video':{'model_id':'deleted'}},providers)
    with pytest.raises(ValueError,match='已停用'):
        validate_generation_policy({'text':None,'image':{'model_id':'deleted'},'video':None},providers)

def test_new_document_can_receive_platform_defaults():
    providers=[{'id':kind,'kind':kind,'is_default':True} for kind in ('text','image','video')]
    document=new_document(default_platform_policy(providers))
    assert document['schemaVersion']==CURRENT_SCHEMA_VERSION
    assert document['generationPolicy']['video']=={'model_id':'video'}

def test_project_model_pool_uses_only_public_platform_ids_and_enforces_scope():
    models=[{'id':kind,'kind':kind,'is_default':kind!='audio'}
            for kind in ('text','image','video','audio')]
    pool=default_model_pool(models)
    assert pool=={kind:[{'model_id':kind}] for kind in ('text','image','video','audio')}
    assert validate_model_pool(pool,models)==pool
    validate_policy_in_pool(default_platform_policy(models),pool)
    require_model_in_pool('storyboard','text',pool)
    with pytest.raises(ValueError,match='可用模型范围'):
        require_model_in_pool('image','another-image',pool)
    with pytest.raises(ValueError,match='用途不匹配'):
        validate_model_pool({**pool,'image':[{'model_id':'video'}]},models)
    with pytest.raises(ValueError,match='必须先加入'):
        validate_policy_in_pool({'text':None,'image':{'model_id':'image'},'video':None},
                                {**pool,'image':[]})
