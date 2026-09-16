"""Replicate prediction adapter using its asynchronous HTTP API.

Official protocol references:
https://replicate.com/docs/topics/predictions/create-a-prediction
https://replicate.com/docs/topics/predictions/input-files
"""
import base64
import copy
import mimetypes
from urllib.parse import quote
import httpx
from . import store as s
from . import provider_egress


def _data_uri(asset):
    path=(s.ASSETS/asset['path']).resolve()
    if not path.is_relative_to(s.ASSETS.resolve()) or not path.is_file():
        raise ValueError('参考素材不可用')
    mime=asset.get('mime') or mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    return 'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii')


def _replace(value,variables):
    if isinstance(value,str):
        if value in variables:return variables[value]
        for key,replacement in variables.items():
            if isinstance(replacement,str):value=value.replace(key,replacement)
        return value
    if isinstance(value,list):return [_replace(item,variables) for item in value]
    if isinstance(value,dict):return {key:_replace(item,variables) for key,item in value.items()}
    return value


def prediction_input(job,provider,assets):
    template=copy.deepcopy(provider.get('parameters',{}).get('input',{'prompt':'{{prompt}}'}))
    if not isinstance(template,dict):raise ValueError('Replicate 输入模板必须是 JSON 对象')
    images=[_data_uri(asset) for asset in assets]
    from .prompts import TEMPLATES
    resolved = _replace(template,{
        '{{prompt}}':job['input']['prompt'],
        '{{system_prompt}}':job['input'].get('system_prompt') or TEMPLATES.get(job['kind'],''),
        '{{target_duration}}':job['input'].get('target_duration',''),
        '{{image}}':images[0] if images else None,
        '{{images}}':images,
    })
    return {**resolved, **job['input'].get('parameters',{})}


def _endpoint(provider):
    model=str(provider.get('model','')).strip()
    if not model:raise ValueError('请填写 Replicate 模型 ID')
    root=provider.get('url','https://api.replicate.com/v1').rstrip('/')
    if ':' in model:return root+'/predictions',{'version':model}
    pieces=model.split('/')
    if len(pieces)!=2 or not all(pieces):raise ValueError('Replicate 官方模型 ID 应为 owner/model；社区模型请使用 owner/model:版本 ID')
    return root+'/models/'+quote(pieces[0],safe='')+'/'+quote(pieces[1],safe='')+'/predictions',{}


def _media_url(value,kind):
    candidates=[]
    def walk(item):
        if isinstance(item,str):candidates.append(item)
        elif isinstance(item,list):
            for child in item:walk(child)
        elif isinstance(item,dict):
            for child in item.values():walk(child)
    walk(value)
    if kind=='video':
        return next((url for url in candidates if url.lower().split('?')[0].endswith(('.mp4','.webm','.mov','.mkv'))),None) or (candidates[0] if candidates else None)
    return next((url for url in candidates if url.startswith(('http://','https://'))),None)


def _text(value):
    if isinstance(value,str):return value
    if isinstance(value,list) and all(isinstance(item,str) for item in value):return '\n'.join(value)
    raise ValueError('Replicate 未返回可用文本结果')


def execute(worker,job,provider):
    from .worker import assets_for,checked,download_result
    remote=job.get('provider_job_id');root=provider.get('url','https://api.replicate.com/v1').rstrip('/')
    headers={'Authorization':'Bearer '+provider.get('api_key',''),'Content-Type':'application/json'}
    with provider_egress.client(origin=provider['url'],timeout=120,headers=headers,trust_env=not provider.get('local',False)) as client:
        if not remote:
            endpoint,body=_endpoint(provider)
            body['input']=prediction_input(job,provider,assets_for(job))
            if worker.cancelled(job):raise InterruptedError()
            value=checked(client.post(endpoint,json=body));remote=value.get('id')
            if not remote:raise ValueError('Replicate 未返回 prediction ID，请核对供应商记录后再提交')
            s.job_update(job['id'],provider_job_id=str(remote))
        while not worker.halt.wait(5):
            if worker.cancelled(job):raise InterruptedError()
            value=checked(client.get(root+'/predictions/'+quote(str(remote),safe='')))
            status=value.get('status')
            if status not in ('starting','processing','succeeded','failed','canceled','aborted'):
                raise ValueError('Replicate 返回未知任务状态，请保留任务编号核对：'+str(status))
            worker.progress(job,{'starting':'云端准备中','processing':'云端生成中','succeeded':'下载云端结果'}.get(status,'查询云端任务'))
            if status in ('failed','canceled','aborted'):
                raise ValueError('Replicate 任务'+({'failed':'生成失败','canceled':'已取消','aborted':'已中止'}[status])+'：'+str(value.get('error') or '请核对供应商任务详情'))
            if status=='succeeded':
                if job['kind']=='text':return {'text':_text(value.get('output'))}
                if job['kind']=='storyboard':
                    import json
                    from .prompts import validate_shots
                    text=_text(value.get('output')).strip()
                    if text.startswith('```'):
                        text=text.split('\n',1)[-1].rsplit('```',1)[0].strip()
                    shots=validate_shots(json.loads(text),job['input'].get('target_duration'))
                    return {'text':text,'shots':shots}
                target=_media_url(value.get('output'),job['kind'])
                if not target:raise ValueError('Replicate 成功任务未返回可下载的媒体地址')
                return {'assets':[download_result(job,target,'.mp4' if job['kind']=='video' else '.png')]}
    raise InterruptedError()


def cancel(job,provider):
    remote=job.get('provider_job_id')
    if not remote:return
    root=provider.get('url','https://api.replicate.com/v1').rstrip('/')
    headers={'Authorization':'Bearer '+provider.get('api_key','')}
    try:
        with provider_egress.client(origin=provider['url'],timeout=20,headers=headers,trust_env=not provider.get('local',False)) as client:
            client.post(root+'/predictions/'+quote(str(remote),safe='')+'/cancel')
    except httpx.HTTPError:
        # Local cancellation still wins, even when the remote service is unreachable.
        return
