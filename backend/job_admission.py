"""Short PostgreSQL admission transactions; no provider I/O here.

Lock order: identity barrier, admission gate, existing object/model locks, then
job rows. Batch callers take the gate before locking any objects.
The gate serializes short submission writes, not Worker execution or quotas.
"""
import json
import hashlib

from fastapi import HTTPException

from . import collaboration, identity, model_validation, platform_models, store as s

ADMISSION_LOCK = 0x4F56435F4A4F4236
ENTRYPOINTS = {'job','audio-batch','canvas-run','source-extraction','adaptation','script-generation'}


def lock(connection):
    collaboration.lock_identity(connection)
    connection.execute('SELECT pg_advisory_xact_lock(%s)',(ADMISSION_LOCK,))


def scope(connection, project_id, entrypoint):
    if entrypoint not in ENTRYPOINTS:raise ValueError('任务入口命名空间无效')
    owner=collaboration.project_scope(connection,project_id,'editor')
    actor=identity.current()
    return owner,actor


def batch_members(connection, project_id, entrypoint, submission_id, members):
    """Freeze a batch's member keys; per-job validation still checks all inputs.

    The caller holds the admission transaction gate. This receipt rolls back
    with any rejected member and prevents extending/reducing a replayed batch.
    """
    owner,actor=scope(connection,project_id,entrypoint)
    value=json.dumps(members,sort_keys=True,separators=(',',':'))
    connection.execute('''INSERT INTO job_submission_batches
        (workspace_id,actor_user_id,namespace,submission_id,project_id,members)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING''',
        (owner['workspace_id'],actor.user_id,entrypoint,submission_id,project_id,value))
    row=connection.execute('''SELECT project_id,members FROM job_submission_batches
        WHERE workspace_id=%s AND actor_user_id=%s AND namespace=%s AND submission_id=%s''',
        (owner['workspace_id'],actor.user_id,entrypoint,submission_id)).fetchone()
    if row['project_id']!=project_id or json.loads(row['members'])!=members:
        raise HTTPException(409,'同一批次提交标识不能改变目标或成员')


def compiler_catalog(project_id, entrypoint, submission_id, *, batch=False):
    """Prepare a replay with its original safe compiler rules, never new keys.

    Current object authorization is still checked before returning any job.
    No provider URL or credential is decrypted/exposed by this helper.
    """
    catalog={item['id']:item for item in platform_models.compiler_catalog()}
    with s.db() as c:
        owner,actor=scope(c,project_id,entrypoint)
        condition='left(j.submission_id,length(%s))=%s' if batch else 'j.submission_id=%s'
        keys=(submission_id+':',submission_id+':') if batch else (submission_id,)
        rows=c.execute('''SELECT j.kind,v.model_id,v.definition,cv.config FROM jobs j
            JOIN job_private p ON p.job_id=j.id JOIN model_versions v ON v.id=p.model_version_id
            JOIN provider_config_versions cv ON cv.id=p.config_version_id
            WHERE j.project_id=%s AND j.workspace_id=%s AND j.actor_user_id=%s
            AND j.submission_namespace=%s AND '''+condition,
            (project_id,owner['workspace_id'],actor.user_id,entrypoint,*keys)).fetchall()
        for row in rows:
            definition=json.loads(row['definition'])
            catalog[row['model_id']]={'id':row['model_id'],'kind':'text' if row['kind']=='storyboard' else row['kind'],
                'type':json.loads(row['config'])['type'],
                **{key:definition[key] for key in ('name','capabilities','defaults','rules')}}
    return list(catalog.values())


def effective_input(value, parameters):
    # Top-level and nested parameter spellings represent the same effective
    # request after P4 validation. Server-frozen defaults participate too.
    result={key:child for key,child in value.items() if key not in model_validation.PARAMETERS and key!='parameters'}
    result['parameters']=parameters
    return result


def fingerprint(project_id, body, target, binding):
    private=None if binding is None else {
        'model_version_id':binding.model_version_id,
        'config_version_id':binding.config_version_id,
        'credential_version_id':binding.credential_version_id,
    }
    parameters=binding.parameters if binding is not None else {}
    # Export inputs have no platform inference parameter defaults to normalize.
    value=effective_input(body.input,parameters) if binding is not None else body.input
    request={'project_id':project_id,'node_id':body.node_id,
        'kind':body.kind,'input':value,'target':target,'binding':private}
    canonical=json.dumps(request,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def replay_binding(connection, old, body, document):
    """Normalize against the ORIGINAL model version, never today's rotated key.

    Replaying an admitted request only reads its record, not a new generation
    authorization. Actual new paid steps must still pass current P4 checks.
    """
    if body.kind=='export':return None
    from .platform_models import Binding
    row=connection.execute('''SELECT p.*,v.model_id,v.definition,cv.config FROM job_private p
        JOIN model_versions v ON v.id=p.model_version_id
        JOIN provider_config_versions cv ON cv.id=p.config_version_id WHERE p.job_id=%s''',(old['id'],)).fetchone()
    if not row:raise HTTPException(409,'原任务缺少固定模型版本，请人工核对')
    if body.input.get('model_id')!=row['model_id']:raise HTTPException(409,'同一提交标识不能更换平台模型')
    submitted=body.input.get('parameters',{})
    if not isinstance(submitted,dict):raise ValueError('生成参数必须为对象')
    submitted=dict(submitted)
    for name in model_validation.PARAMETERS:
        if name in body.input:
            if name in submitted and submitted[name]!=body.input[name]:raise ValueError('生成参数存在重复冲突')
            submitted[name]=body.input[name]
    if body.kind=='image' and json.loads(old['input']).get('image_spec',{}).get('version')=='platform-image-settings/v1':
        from .image_settings import resolve
        parameters,_=resolve(json.loads(row['definition']),submitted,document,body.node_id,
            json.loads(row['config']),body.input.get('imageSettings'),freeze=True,
            frozen_seed=json.loads(row['parameters']).get('seed'))
    else:
        parameters=model_validation.shot_parameters(json.loads(row['definition']),submitted,
            'text' if body.kind=='storyboard' else body.kind,document,body.node_id)
    return Binding(row['model_id'],row['model_version_id'],row['config_version_id'],row['credential_version_id'],parameters)
