"""MiniMax v1 native video API. Source: platform.minimax.io/docs/api-reference/video-generation-t2v."""
import httpx,base64
from pathlib import Path
from PIL import Image
from . import store as s
from . import provider_egress

def payload(inp,provider):
    params={**provider.get('parameters',{}),**inp.get('parameters',{})}
    model=provider.get('model') or 'MiniMax-Hailuo-2.3'
    if model!='MiniMax-Hailuo-2.3':raise ValueError('当前 MiniMax 原生适配器已配置的模型为 MiniMax-Hailuo-2.3')
    duration=params.get('duration',6);resolution=params.get('resolution','768P')
    if duration not in (6,10) or resolution not in ('768P','1080P') or (resolution=='1080P' and duration!=6):raise ValueError('MiniMax 2.3 支持 768P 的 6/10 秒或 1080P 的 6 秒')
    if inp.get('end_asset_id'):raise ValueError('当前 MiniMax 2.3 适配器不支持尾帧')
    if len(inp.get('asset_ids',[]))>1:raise ValueError('MiniMax 图生视频仅接受一张首帧')
    if len(inp['prompt'])>2000:raise ValueError('MiniMax 提示词最多 2000 字符')
    return {'model':model,'prompt':inp['prompt'],'duration':duration,'resolution':resolution,'prompt_optimizer':False}

def first_frame(asset,encode=False):
    path=(s.ASSETS/asset['path']).resolve()
    if not path.is_relative_to(s.ASSETS.resolve()) or not path.is_file():raise ValueError('首帧素材不可用')
    if path.stat().st_size>=20*1024*1024:raise ValueError('MiniMax 首帧必须小于 20MB')
    with Image.open(path) as image:
        width,height=image.size
        if image.format not in ('JPEG','PNG','WEBP'):raise ValueError('MiniMax 首帧需为 JPEG、PNG 或 WebP')
        if min(width,height)<=300 or not .4<=width/height<=2.5:raise ValueError('MiniMax 首帧短边需大于 300px，长宽比需在 2:5 至 5:2 之间')
        mime=Image.MIME[image.format]
        image.verify()
    return 'data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii') if encode else None

def execute(worker,job,provider):
    from .worker import checked,download_result
    def parse(response):
        data=checked(response);base=data.get('base_resp',{})
        if base.get('status_code',0)!=0:raise ValueError('MiniMax 服务错误 '+str(base.get('status_code'))+'：'+str(base.get('status_msg','未知错误')))
        return data
    url=provider['url'].rstrip('/');remote=job.get('provider_job_id')
    with provider_egress.client(origin=provider['url'],timeout=120,headers={'Authorization':'Bearer '+provider.get('api_key','')},trust_env=not provider.get('local',False)) as client:
        if not remote:
            body=payload(job['input'],provider)
            from .worker import assets_for
            references=assets_for(job)
            if references:body['first_frame_image']=first_frame(references[0],True)
            if worker.cancelled(job):raise InterruptedError()
            value=parse(client.post(url+'/video_generation',json=body));remote=value.get('task_id')
            if not remote:raise ValueError('MiniMax 未返回 task_id，请核对供应商记录后再提交')
            s.job_update(job['id'],provider_job_id=str(remote))
        while not worker.halt.wait(10):
            if worker.cancelled(job):raise InterruptedError()
            value=parse(client.get(url+'/query/video_generation',params={'task_id':remote}));status=value.get('status')
            if status not in ('Preparing','Queueing','Processing','Success','Fail'):raise ValueError('MiniMax 返回未知任务状态，请保留任务编号核对：'+str(status))
            worker.progress(job,{'Preparing':'云端准备中','Queueing':'云端排队中','Processing':'云端生成中','Success':'下载云端视频'}.get(status,'查询云端任务'))
            if status=='Fail':raise ValueError('MiniMax 视频生成失败，请核对供应商任务详情')
            if status=='Success':
                if not value.get('file_id'):raise ValueError('MiniMax 成功任务缺少 file_id')
                file=parse(client.get(url+'/files/retrieve',params={'file_id':value['file_id']}))
                target=file.get('file',{}).get('download_url')
                if not target:raise ValueError('MiniMax 未返回视频下载链接')
                return {'assets':[download_result(job,target,'.mp4')]}
    raise InterruptedError()
