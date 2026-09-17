"""DEFERRED old P6 quota experiment; disconnected from SINGLE-01 runtime.

All mutation callers hold job_admission.lock BEFORE object/model/job locks.
Counters are derived from persistent reservations; no process-local counters.
"""
import copy
import json

from fastapi import HTTPException

from . import job_admission, job_execution, store as s

KINDS=('text','image','video','audio')
DEFAULTS={
    'daily_user':{'text':1000,'image':500,'video':100,'audio':1000},
    'daily_team':{'text':10000,'image':5000,'video':1000,'audio':10000},
    'queue_user':1000,'queue_team':10000,
    'concurrency_global':16,'concurrency_provider':8,'concurrency_team':8,'concurrency_user':4,
    'ffmpeg_slots':2,'max_queue_age_seconds':86400,'timezone':'UTC',
    'paused':False,'paused_providers':[],
}


def settings(c):
    row=c.execute('SELECT revision,settings FROM job_limit_settings WHERE singleton=1').fetchone()
    return {'revision':row['revision'],'settings':{**copy.deepcopy(DEFAULTS),**json.loads(row['settings'])}}


def configure(c,revision,changes):
    job_admission.lock(c)
    old=settings(c)
    if revision!=old['revision']:raise HTTPException(409,'任务额度配置已更新，请刷新后重试')
    if not isinstance(changes,dict) or set(changes)-DEFAULTS.keys():raise ValueError('任务额度配置字段无效')
    value={**old['settings'],**changes}
    for key,default in DEFAULTS.items():
        item=value[key]
        if key in ('daily_user','daily_team'):
            if not isinstance(item,dict) or set(item)!=set(KINDS):raise ValueError('每日额度必须包含四种生成类型')
            if any(type(n) is not int or not 0<=n<=1000000 for n in item.values()):raise ValueError('每日额度必须为非负整数')
        elif type(default) is int:
            minimum=1 if key=='max_queue_age_seconds' else 0
            if type(item) is not int or not minimum<=item<=1000000:raise ValueError('任务资源上限无效')
        elif key=='paused' and type(item) is not bool:raise ValueError('暂停开关必须为布尔值')
        elif key=='paused_providers':
            if not isinstance(item,list) or len(item)>1000 or any(not isinstance(p,str) or not p for p in item):
                raise ValueError('暂停的供应商列表无效')
            value[key]=sorted(set(item))
        elif key=='timezone':
            if not isinstance(item,str) or not c.execute('SELECT 1 FROM pg_timezone_names WHERE name=%s',(item,)).fetchone():
                raise ValueError('配额时区无效')
    c.execute('UPDATE job_limit_settings SET revision=revision+1,settings=%s WHERE singleton=1',(s.dumps(value),))
    return {'revision':revision+1,'settings':value}


def initial_plan(kind,inp,provider=None):
    if kind=='storyboard' and inp.get('film_bible') and (provider or {}).get('type')!='replicate':
        return [{'name':name,'kind':'text','units':1} for name in ('visual_bible','bound_storyboard')]
    quota_kind='text' if kind=='storyboard' else kind
    parameters=(provider or {}).get('job_parameters',{})
    units=1
    if kind=='image' and (provider or {}).get('type') not in ('volcengine_ark','runninghub'):
        units=parameters.get('n',parameters.get('count',1))
    if type(units) is not int or not 1<=units<=1000:raise ValueError('规划的图片数量无效')
    return [{'name':'generate' if kind!='export' else 'export','kind':quota_kind,'units':units}]


def _denied(reason):
    raise HTTPException(429,{'type':'job_limit','reason':reason})


def assert_unpaused(config,provider_id):
    if config['paused'] or provider_id in config['paused_providers']:
        _denied('平台或供应商已暂停新调用')


def _check_daily(c,reservation,steps,config):
    amounts={kind:sum(step['units'] for step in steps if step['kind']==kind) for kind in KINDS}
    for dimension,column,value in (('user','actor_user_id',reservation['actor_user_id']),
                                    ('team','workspace_id',reservation['workspace_id'])):
        rows=c.execute(f'''SELECT u.kind,SUM(u.units) used FROM job_step_usage u
            JOIN job_reservations r ON r.job_id=u.job_id
            WHERE r.{column}=%s AND r.quota_day=%s AND u.state!='released' GROUP BY u.kind''',
            (value,reservation['quota_day'])).fetchall()
        used={row['kind']:row['used'] for row in rows}
        for kind,amount in amounts.items():
            if amount and used.get(kind,0)+amount>config['daily_'+dimension][kind]:
                _denied(f'{dimension} 每日 {kind} 提交额度不足')


def reserve(c,job,steps,provider_id=None):
    """Same transaction as jobs/private binding/step plan and event inserts."""
    config=settings(c)['settings']
    assert_unpaused(config,provider_id)
    for dimension,column,value in (('user','actor_user_id',job['actor_user_id']),
                                    ('team','workspace_id',job['workspace_id'])):
        queued=c.execute(f"SELECT COUNT(*) n FROM jobs WHERE {column}=%s AND status='queued' AND id!=%s",
                         (value,job['id'])).fetchone()['n']
        if queued>=config['queue_'+dimension]:_denied(f'{dimension} 排队上限已满')
    stamp=job_execution.now(c)
    day=c.execute('SELECT (to_timestamp(%s) AT TIME ZONE %s)::date day',(stamp,config['timezone'])).fetchone()['day']
    reservation={**job,'quota_day':day}
    _check_daily(c,reservation,steps,config)
    c.execute('''INSERT INTO job_reservations(job_id,workspace_id,actor_user_id,provider_id,
        quota_day,quota_timezone,admitted_at,queue_expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)''',
        (job['id'],job['workspace_id'],job['actor_user_id'],provider_id,day,config['timezone'],stamp,
         stamp+config['max_queue_age_seconds']))
    job_execution.plan_steps(c,job['id'],steps)
    for step in steps:
        c.execute('INSERT INTO job_step_usage(job_id,name,kind,units) VALUES(%s,%s,%s,%s)',
                  (job['id'],step['name'],step['kind'],step['units']))


def reserve_repair(c,job_id,name):
    """Only known optional text repair steps; called AFTER current ACL checks."""
    prerequisites={'generate_repair':'generate','visual_bible_repair':'visual_bible',
                   'bound_storyboard_repair':'bound_storyboard'}
    if name not in prerequisites:raise ValueError('未声明的新增付费步骤')
    job=job_execution.guard(c,job_id)
    reservation=c.execute('SELECT * FROM job_reservations WHERE job_id=%s',(job_id,)).fetchone()
    if not reservation:raise ValueError('任务没有原始预占记录，禁止新增付费步骤')
    prior=c.execute('SELECT * FROM job_steps WHERE job_id=%s AND name=%s',
                    (job_id,prerequisites[name])).fetchone()
    if not prior or prior['kind']!='text' or prior['state']!='completed':raise ValueError('前序文本步骤尚未完成')
    if c.execute('SELECT 1 FROM job_step_usage WHERE job_id=%s AND name=%s',(job_id,name)).fetchone():return
    config=settings(c)['settings'];assert_unpaused(config,reservation['provider_id'])
    step={'name':name,'kind':'text','units':1}
    _check_daily(c,reservation,[step],config)
    job_execution.plan_steps(c,job_id,[step])
    c.execute("INSERT INTO job_step_usage(job_id,name,kind,units) VALUES(%s,%s,'text',1)",(job_id,name))


def release_unsent(c,job_id):
    # Never refund submitted/unknown steps just because a local attempt stops.
    c.execute("UPDATE job_step_usage SET state='released' WHERE job_id=%s AND state='reserved'",(job_id,))
