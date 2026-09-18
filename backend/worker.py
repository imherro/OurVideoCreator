"""Durable single-process worker for external Providers and FFmpeg jobs."""
import base64
import json
import mimetypes
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import quote
import httpx
from . import store as s
from . import platform_models, provider_egress
from .provider_redaction import protect, scrub
from .prompts import TEMPLATES, SHOT_SCHEMA, validate_shots
from .media import ffmpeg_executable,probe
from .database import WorkerAdvisoryLock
from .editor_renderer import EditorRenderCompiler
from .providers.common import RecoverableProviderError,assets_for,checked,download_result,register

class Worker:
    def __init__(self, concurrency=4):
        self.halt=threading.Event()
        self.threads=[]
        self.busy=False
        self.concurrency=max(1,int(concurrency))
        self.activity_lock=threading.Lock()
        self.active_count=0
        self.serial_execution_lock=threading.Lock()
        self.process_lock=WorkerAdvisoryLock()
        self.ownership_gate=threading.Lock()
        self.failed=threading.Event()
        self.fatal_error=None
        self.failure_lock=threading.Lock()
    def start(self):
        self.process_lock.acquire()
        try:
            with s.db() as c:
                # Reconcile only after proving this process owns the queue.
                c.execute("""UPDATE jobs SET status='interrupted',phase=CASE
                    WHEN provider_job_id IS NULL THEN '服务已重启，原任务输入已保留；点击待恢复可重新排队'
                    ELSE '服务已重启，点击待恢复可继续查询上游任务' END,updated=%s
                    WHERE status='running'""",(time.time(),))
                c.execute("""UPDATE jobs SET phase='原任务输入已保留；点击待恢复可重新排队'
                    WHERE status='interrupted' AND provider_job_id IS NULL
                    AND phase='服务已重启，可凭上游任务编号恢复查询'""")
            self.halt.clear()
            self.failed.clear()
            self.fatal_error=None
            self.threads=[
                threading.Thread(target=self.loop,daemon=True,name=f'studio-worker-{index + 1}')
                for index in range(self.concurrency)
            ]
            self.threads.append(
                threading.Thread(target=self.monitor_lock,daemon=True,name='studio-worker-lock-monitor')
            )
            for thread in self.threads:thread.start()
        except BaseException:
            self.process_lock.release()
            raise
    def stop(self):
        self.halt.set()
        for thread in self.threads:thread.join(timeout=3)
        stopped=not any(thread.is_alive() for thread in self.threads)
        self.threads=[]
        # If an HTTP provider is still unwinding, retain process ownership;
        # the OS releases the lock at process exit and no second worker can
        # start against the same queue in the meantime.
        if stopped:self.process_lock.release()

    def fail(self, exc):
        with self.failure_lock:
            if self.fatal_error is None:
                self.fatal_error=exc
        self.failed.set()
        self.halt.set()

    def raise_if_failed(self):
        if self.failed.is_set():
            raise RuntimeError('Worker stopped after a fatal queue-ownership or database failure.') from self.fatal_error

    def monitor_lock(self):
        try:
            while not self.halt.wait(0.25):
                with self.ownership_gate:
                    self.process_lock.assert_held()
        except BaseException as exc:
            self.fail(exc)

    def mark_active(self,delta):
        with self.activity_lock:
            self.active_count=max(0,self.active_count+delta)
            self.busy=self.active_count>0

    def ark_job(self,job):
        with s.db() as c:
            row=c.execute("""SELECT cv.config FROM job_private j
                JOIN provider_config_versions cv ON cv.id=j.config_version_id WHERE j.job_id=%s""",
                (job['id'],)).fetchone()
        return bool(row and json.loads(row['config']).get('type') in ('volcengine_ark','volcengine_speech'))
    def loop(self):
        try:
            self._loop()
        except BaseException as exc:
            self.fail(exc)

    def _loop(self):
        while not self.halt.is_set():
            failed=[]
            row=None
            # Claims and the ownership monitor share a gate. If the monitor
            # observes loss, no claimant can pass this point afterwards.
            with self.ownership_gate:
                if self.halt.is_set():
                    break
                self.process_lock.assert_held()
                with s.db() as c:
                    candidates=c.execute(
                        "SELECT * FROM jobs WHERE status='queued' ORDER BY created LIMIT 500 "
                        'FOR UPDATE SKIP LOCKED'
                    ).fetchall()
                    for candidate in candidates:
                        dependencies=json.loads(candidate['input']).get('upstream_job_ids',[])
                        states=[c.execute('SELECT status FROM jobs WHERE id=%s',(dep,)).fetchone() for dep in dependencies]
                        if any(not state or state['status'] in ('failed','cancelled') for state in states):
                            c.execute("UPDATE jobs SET status='failed',phase='上游任务未完成',error='上游任务失败或取消，请修复上游后重新执行此分支',finished=%s,updated=%s WHERE id=%s",(time.time(),time.time(),candidate['id']))
                            failed.append(candidate)
                            continue
                        if any(state['status']!='succeeded' for state in states): continue
                        row=candidate;break
                    if row:
                        claimed=c.execute(
                            "UPDATE jobs SET status='running',started=COALESCE(started,%s),updated=%s "
                            "WHERE id=%s AND status='queued' RETURNING id",
                            (time.time(),time.time(),row['id']),
                        ).fetchone()
                        if not claimed:row=None
                    for item in failed:
                        s.event(item['project_id'],{'type':'job','id':item['id']},connection=c)
            if not row:
                self.halt.wait(1)
                continue
            job=s.unpack(row); self.mark_active(1)
            try:
                if self.ark_job(job):
                    result=self.execute(job)
                else:
                    # P1 deliberately keeps one Worker process. Providers not
                    # explicitly proven concurrent stay serialized until P6.
                    with self.serial_execution_lock:result=self.execute(job)
                if not self.cancelled(job): s.job_update(job['id'],status='succeeded',result=result,progress=100,phase='已完成')
            except InterruptedError:
                if self.halt.is_set():
                    s.job_update(job['id'],status='interrupted',phase='服务停止，保留上游任务编号供恢复核对')
                else:
                    s.job_update(job['id'],status='cancelled',phase='已取消')
            except RecoverableProviderError as exc:
                s.job_update(job['id'],status='interrupted',error=str(exc)[:1200],phase='供应商暂时不可用，保留上游任务编号；可恢复查询')
            except Exception as exc:
                message=str(exc)
                if isinstance(exc,(httpx.ConnectError,httpx.ConnectTimeout)):
                    message='无法连接模型服务，请确认服务已启动、地址正确。'
                if 'out of memory' in message.lower(): message='显存不足。请降低分辨率、时长或换用更小模型。'
                if self.halt.is_set() or isinstance(exc,(httpx.TransportError,provider_egress.EgressDenied)):
                    s.job_update(job['id'],status='interrupted',error=message[:1200],phase='连接中断，保留输入与上游任务编号；可恢复查询')
                else:
                    s.job_update(job['id'],status='failed',error=message[:1200],phase='生成失败')
            finally:
                self.mark_active(-1)
    def cancelled(self,job):
        with s.db() as c:
            row=c.execute('SELECT status FROM jobs WHERE id=%s',(job['id'],)).fetchone()
        return self.halt.is_set() or not row or row['status']=='cancelled'
    def progress(self,job,phase,percent=None):
        if self.cancelled(job): raise InterruptedError()
        s.job_update(job['id'],phase=phase,progress=percent)
    def execute(self,job):
        inp=dict(job['input']); kind=job['kind']
        if kind=='video':
            from .state_review import require_video_source_reviews
            from .production_context import read_project_state
            with s.db() as c:
                saved=read_project_state(c,job['project_id'])
            if saved:
                # A queued batch may have produced its still before the browser
                # can persist a review acknowledgement. Do not let that race
                # send an unchecked opening frame to a video model.
                require_video_source_reviews(saved['document'],job['node_id'],include_pending=True)
        upstream_text=[];asset_ids=list(inp.get('asset_ids',[]));upstream_results={}
        for dependency in inp.get('upstream_job_ids',[]):
            with s.db() as c: previous=c.execute('SELECT * FROM jobs WHERE id=%s AND project_id=%s',(dependency,job['project_id'])).fetchone()
            if not previous or previous['status']!='succeeded': raise ValueError('上游任务尚未完成')
            result=json.loads(previous['result'] or '{}')
            upstream_results[dependency]=result
            if result.get('text'): upstream_text.append(result['text'])
            if 'image_reference_sources' not in inp:
                asset_ids.extend(a['id'] for a in result.get('assets',[]) if a.get('kind')=='image')
        if 'image_reference_sources' in inp:
            asset_ids=[]
            for source in inp['image_reference_sources']:
                if source.get('type')=='asset' and source.get('asset_id'):
                    asset_ids.append(source['asset_id'])
                elif source.get('type')=='upstream_job' and source.get('job_id') in upstream_results:
                    resolved_images = [
                        a['id'] for a in upstream_results[source['job_id']].get('assets',[])
                        if a.get('kind')=='image' and a.get('id')
                    ]
                    if inp.get('motion_compiler') and len(resolved_images) != 1:
                        raise ValueError('多模态待生成图片参考须产生恰好一张图片，避免改变冻结编号；请明确选择素材后重新提交')
                    asset_ids.extend(resolved_images)
                else:
                    raise ValueError('批次图像参考来源已损坏，请重新运行画布')
        if upstream_text and not inp.get('reference_compiler'):
            inp['prompt']=inp['prompt']+'\n\n上游创作内容：\n'+'\n\n'.join(upstream_text)
        inp['asset_ids']=(
            asset_ids
            if inp.get('reference_compiler')
            else list(dict.fromkeys(asset_ids))
        )
        job={**job,'input':inp}
        self.progress(job,'准备任务')
        if kind=='export':
            return self.export(job)
        with s.db() as c:
            provider=platform_models.load_job_provider(c,job['id'],remote=bool(job.get('provider_job_id')))
        platform_models.validate_capabilities(provider['capabilities'],inp)
        # Only immutable, server-validated parameters drive the protocol.
        inp={**inp,**provider['job_parameters'],'parameters':dict(provider['job_parameters'])}
        job={**job,'input':inp}
        with protect(provider.get('api_key','')), provider_egress.before_call(lambda: platform_models.check_job_call(job['id'])):
            return scrub(self.dispatch(job,provider))

    def dispatch(self,job,provider):
        kind=job['kind']
        if provider['type']=='replicate':
            from .replicate_api import execute
            return execute(self,job,provider)
        if kind in ('text','storyboard'):
            if provider['type']=='volcengine_ark':
                from .providers.volcengine_ark import model_for
                provider={**provider,'model':model_for(provider,'text')}
            elif provider['type']=='hc_atom':
                from .providers.hc_atom import model_for, text_base_url
                provider={**provider,'url':text_base_url(provider),'model':model_for(provider,'text')}
            elif provider['type']=='runninghub':
                from .providers.runninghub import model_for, text_base_url
                provider={**provider,'url':text_base_url(provider),'model':model_for(provider,'text')}
            return self.text(job,provider)
        if kind=='audio' and provider['type']=='volcengine_speech':
            from .providers.volcengine_speech import synthesize
            return synthesize(self,job,provider)
        if provider['type']=='maestro': return self.maestro(job,provider)
        if provider['type']=='comfy': return self.comfy(job,provider)
        if kind=='image' and provider['type']=='openai': return self.image(job,provider)
        if kind=='video' and provider['type']=='minimax':
            from .minimax_video import execute
            return execute(self,job,provider)
        if kind=='video' and provider['type']=='video_api': return self.video_api(job,provider)
        if provider['type']=='volcengine_ark':
            from .providers.volcengine_ark import execute
            return execute(self,job,provider)
        if provider['type']=='hc_atom':
            from .providers.hc_atom import execute
            return execute(self,job,provider)
        if provider['type']=='runninghub':
            from .providers.runninghub import execute
            return execute(self,job,provider)
        raise ValueError('所选服务不支持此任务类型，请更换模型服务。')

    def _chat_text(self,job,p,system_prompt,user_prompt,schema=None,phase='生成文本'):
        inp=job['input']
        headers={'Authorization':'Bearer '+p['api_key']} if p.get('api_key') else {}
        if schema and not p.get('structured'):
            user_prompt+='\n\n必须严格输出以下 JSON Schema 对应的单个 JSON 值，不要输出 Markdown 或解释：\n'+json.dumps(schema,ensure_ascii=False)
        body={'model':p.get('model',''),'messages':[{'role':'system','content':system_prompt},{'role':'user','content':user_prompt}], 'temperature':inp.get('temperature',0.6),'max_tokens':int(inp.get('max_tokens',4096)),'stream':True}
        if 'top_p' in inp: body['top_p']=inp['top_p']
        if schema and p.get('structured'):
            body['response_format']={'type':'json_schema','json_schema':{'name':'structured_result','strict':True,'schema':schema}}
        self.progress(job,phase)
        chunks=[]; last=0
        with provider_egress.client(origin=p['url'],timeout=httpx.Timeout(3600,connect=10),trust_env=not p.get('local',False)) as client:
            with client.stream('POST',p['url'].rstrip('/')+'/chat/completions',headers=headers,json=body) as response:
                if not response.is_success:
                    response.read(); checked(response)
                for line in response.iter_lines():
                    if self.cancelled(job): raise InterruptedError()
                    if not line.startswith('data:'): continue
                    data=line[5:].strip()
                    if data=='[DONE]': break
                    try:
                        part=json.loads(data).get('choices',[{}])[0].get('delta',{}).get('content')
                        if part: chunks.append(part)
                    except (ValueError,IndexError,AttributeError): continue
                    if time.time()-last>1:
                        s.job_update(job['id'],result={'text':''.join(chunks)})
                        last=time.time()
        text=''.join(chunks).strip()
        if not text: raise ValueError('文本模型没有返回正文，请检查模型聊天模板或切换模型。')
        return scrub(text)

    def text(self,job,p):
        inp=job['input']; kind=job['kind']
        if kind=='text' and inp.get('adaptation_generation'):
            from .adaptation import ADAPTATION_SCHEMA, ADAPTATION_SYSTEM_PROMPT
            from .job_candidates import adaptation_value
            raw=self._chat_text(job,p,inp.get('system_prompt') or ADAPTATION_SYSTEM_PROMPT,inp['prompt'],inp.get('response_schema') or ADAPTATION_SCHEMA,'生成改编策划')
            try:value=json.loads(raw.strip())
            except json.JSONDecodeError as exc:raise ValueError('改编策划结果不是严格 JSON：'+str(exc)) from exc
            result=adaptation_value(job,value)
            return {'text':s.dumps(result),'adaptation':result}
        if kind=='text' and inp.get('episode_script_generation'):
            from .adaptation import SCRIPT_SCHEMA, SCRIPT_SYSTEM_PROMPT, validate_generated_script
            raw=self._chat_text(job,p,inp.get('system_prompt') or SCRIPT_SYSTEM_PROMPT,inp['prompt'],inp.get('response_schema') or SCRIPT_SCHEMA,'生成本集剧本')
            try:value=json.loads(raw.strip())
            except json.JSONDecodeError as exc:raise ValueError('逐集剧本结果不是严格 JSON：'+str(exc)) from exc
            result=validate_generated_script(value)
            return {'text':result['body'],'script':result}
        if kind=='text' and inp.get('source_event_extraction'):
            from .source_library import EVENT_SCHEMA, SYSTEM_PROMPT, validate_events
            raw=self._chat_text(job,p,inp.get('system_prompt') or SYSTEM_PROMPT,inp['prompt'],inp.get('response_schema') or EVENT_SCHEMA,'提取原著事件')
            try:rows=validate_events(json.loads(raw.strip()))
            except (ValueError,TypeError,json.JSONDecodeError) as exc:
                raise ValueError('事件提取结果校验失败：'+str(exc)) from exc
            return {'text':s.dumps({'events':rows}),'events':rows}
        if kind=='storyboard' and inp.get('film_bible'):
            from .film_bible import extract_storyboard
            prompt_trace=[]
            def publish_trace():
                s.job_update(job['id'],telemetry={'prompt_stages':prompt_trace})
            def request_stage(system,user,schema,phase,stage_id):
                entry={
                    'id':stage_id,'phase':phase,'system_prompt':system,
                    'user_prompt':user,'response_schema':schema,'status':'running',
                    'started':time.time(),
                }
                prompt_trace.append(entry);publish_trace()
                try:return self._chat_text(job,p,system,user,schema,phase)
                except Exception as exc:
                    entry.update(status='request_failed',finished=time.time(),error=str(exc)[:1200]);publish_trace();raise
                finally:
                    if entry['status']=='running':
                        entry.update(status='response_received',finished=time.time());publish_trace()
            def report_stage(stage_id,status,error=None):
                entry=next((item for item in reversed(prompt_trace) if item['id']==stage_id),None)
                if entry:
                    entry['status']=status
                    if error:entry['validation_error']=error[:1200]
                    publish_trace()
            return extract_storyboard(
                inp['prompt'],inp.get('target_duration'),'',
                inp.get('model_id',''),
                request_stage,inp.get('prompt_stages'),report_stage,
                existing_visual=(inp.get('storyboard_visual_context') or {}).get('visual'),
            )
        prompt=inp['prompt']
        if kind=='text' and inp.get('target_duration'):
            duration=float(inp['target_duration'])
            duration_label=f'{duration:g}'
            end_time=f'{int(duration)//60}:{duration%60:04.1f}'
            prompt+=(
                f'\n\n成片目标总时长严格为 {duration_label} 秒。'
                f'剧本必须能在 0:00–{end_time} 内完整拍完，'
                '从开场、发展到结尾都不得超出该时长；控制人物、场景、对白和动作数量，'
                '不要扩写成长片、分钟级短片或完整系列故事。请在标题下明确标注目标总时长。'
            )
        if kind=='storyboard' and inp.get('target_duration'):
            prompt+=f'\n镜头总时长必须为 {inp["target_duration"]} 秒，误差不超过 0.5 秒。'
        text=self._chat_text(
            job,p,inp.get('system_prompt') or TEMPLATES[kind],prompt,
            inp.get('response_schema') or (SHOT_SCHEMA if kind=='storyboard' else None),
            '生成剧本' if kind=='text' else '拆解分镜',
        )
        if kind=='storyboard':
            start=text.find('{'); end=text.rfind('}')
            try: result=validate_shots(json.loads(text[start:end+1]),inp.get('target_duration'))
            except (ValueError,TypeError) as exc:
                if inp.get('_repair_attempt'):raise ValueError('分镜修正后仍不符合要求：'+str(exc)) from exc
                self.progress(job,'校验分镜并修正一次')
                repaired={**inp,'_repair_attempt':True,'prompt':inp['prompt']+'\n\n上次结果未通过校验：'+str(exc)+'\n请保持故事内容，修正后重新输出完整 JSON。上次结果：\n'+text[:24000]}
                return self.text({**job,'input':repaired},p)
            return {'text':s.dumps(result),**result,'repair_count':int(bool(inp.get('_repair_attempt')))}
        return {'text':text}

    def image(self,job,p):
        if assets_for(job): raise ValueError('此图像服务当前为文生图接口，图生图请选择 ComfyUI 或 Maestro。')
        inp=job['input']; headers={'Authorization':'Bearer '+p['api_key']} if p.get('api_key') else {}
        self.progress(job,'云端生成图像')
        with provider_egress.client(origin=p['url'],timeout=600,trust_env=not p.get('local',False)) as client:
            result=checked(client.post(p['url'].rstrip('/')+'/images/generations',headers=headers,json={'model':p.get('model'),'prompt':inp['prompt'],'n':inp.get('n',1),'size':inp.get('size','1024x1024')}))
        outputs=[]
        for item in result.get('data',[]):
            if self.cancelled(job): raise InterruptedError()
            if item.get('b64_json'):
                path=s.DATA/(s.uid()+'.png')
                try:
                    path.write_bytes(base64.b64decode(item['b64_json']))
                    outputs.append(register(job,path,'分镜图.png'))
                finally: path.unlink(missing_ok=True)
            elif item.get('url'): outputs.append(download_result(job,item['url'],'.png'))
        if not outputs: raise ValueError('服务未返回图像')
        return {'assets':outputs}

    def maestro(self,job,p):
        inp=job['input']; url=p['url'].rstrip('/')
        with provider_egress.client(origin=p['url'],timeout=httpx.Timeout(3600,connect=10),trust_env=not p.get('local',False)) as client:
            remote=job.get('provider_job_id')
            if not remote:
                model=p.get('model')
                if not model: raise ValueError('请先选择 Maestro 模型')
                from .capabilities import maestro_model,validate_media
                catalogue=checked(client.get(url+'/api/v1/models')).get('models',[])
                entry=next((m for m in catalogue if m['model_type']==model),None)
                if not entry:raise ValueError('所选模型不在已连接的 Maestro API 目录中，请刷新模型列表')
                validate_media(maestro_model(entry),job['kind'],inp)
                defaults=checked(client.get(url+'/api/v1/defaults/'+quote(model,safe='')))
                if 'defaults' in defaults: defaults=defaults['defaults']
                body={**defaults,**p.get('parameters',{}),**inp.get('parameters',{}),'model_type':model,'prompt':inp['prompt'],'_client_submission_id':job['submission_id']}
                body['image_mode']=1 if job['kind']=='image' else 0
                body['video_prompt_type']=''
                body['image_prompt_type']=''
                body.pop('image_refs',None)
                body.pop('image_start',None)
                body.pop('image_end',None)
                body['resolution']=inp.get('resolution','832x480')
                if job['kind']=='video': body['video_length']=int(inp.get('frames',121))
                else: body['video_length']=1
                body['seed']=int(inp.get('seed',-1))
                refs=assets_for(job)
                if refs:
                    paths=[]
                    for ref in refs:
                        with (s.ASSETS/ref['path']).open('rb') as file:
                            uploaded=checked(client.post(url+'/api/v1/upload',files={'file':(ref['name'],file,ref['mime'])}))
                        paths.append(uploaded['path'])
                    if job['kind']=='image':
                        body['image_refs']=paths
                        body['video_prompt_type']='KI'
                    else:
                        # MiniMax H3 treats a still as an I2V start frame.
                        # ``video_prompt_type=I`` is for image_refs and gets
                        # stripped by the native engine when only image_start
                        # is present, silently turning this into T2V.
                        body['image_start']=paths[0]
                        body['image_prompt_type']='S'
                if inp.get('end_asset_id'):
                    tail=assets_for({**job,'input':{'asset_ids':[inp['end_asset_id']]}})[0]
                    if tail['kind']!='image':raise ValueError('尾帧必须是图像素材')
                    with (s.ASSETS/tail['path']).open('rb') as file:
                        uploaded=checked(client.post(url+'/api/v1/upload',files={'file':(tail['name'],file,tail['mime'])}))
                    body['image_end']=uploaded['path']
                    body['image_prompt_type']+='E'
                self.progress(job,'提交 Maestro API 任务')
                result=checked(client.post(url+'/api/v1/generate',json=body))
                remote=result.get('job_id') or result.get('id')
                if not remote: raise ValueError('Maestro 未返回任务编号')
                s.job_update(job['id'],provider_job_id=remote)
            while not self.halt.wait(2):
                if self.cancelled(job):
                    client.post(url+'/api/v1/cancel/'+remote)
                    raise InterruptedError()
                status=checked(client.get(url+'/api/v1/status/'+remote))
                s.job_update(job['id'],telemetry={key:status.get(key) for key in ('step','total_steps','generation_eta_seconds','eta_confidence','current_clip','total_clips','current_window','total_windows')})
                self.progress(job,status.get('message') or status.get('phase') or 'Maestro API 生成中',status.get('progress'))
                if status['status'] in ('failed','cancelled'): raise ValueError(status.get('error') or status.get('message') or ('Maestro API 生成失败' if status['status']=='failed' else 'Maestro API 任务已取消'))
                if status['status']=='completed':
                    outputs=[]
                    for output in status.get('output_files',[]):
                        name=output if isinstance(output,str) else output.get('name') or output.get('filename')
                        if not name: continue
                        output_kind=(mimetypes.guess_type(name)[0] or '').split('/')[0]
                        if output_kind!=job['kind']: continue
                        output_name=name.replace('\\','/').rsplit('/',1)[-1]
                        downloaded=client.get(url+'/api/v1/uploads/'+quote(output_name,safe=''))
                        downloaded.raise_for_status()
                        suffix='.'+output_name.rsplit('.',1)[-1] if '.' in output_name else ''
                        temp=s.DATA/(s.uid()+suffix)
                        try:
                            temp.write_bytes(downloaded.content); outputs.append(register(job,temp,output_name))
                        finally: temp.unlink(missing_ok=True)
                    if not outputs: raise ValueError('Maestro API 任务完成，但没有可下载的输出文件')
                    return {'assets':outputs}
        raise InterruptedError()

    def comfy(self,job,p):
        inp=job['input']; template=p.get('workflow')
        if inp.get('end_asset_id'):raise ValueError('当前 ComfyUI 适配器未配置尾帧输入，请清除尾帧或改用支持尾帧的外部 Provider')
        if not isinstance(template,dict): raise ValueError('请在模型服务中配置 ComfyUI API 工作流 JSON')
        refs=assets_for(job); url=p['url'].rstrip('/')
        width,height=(int(v) for v in inp.get('resolution','832x480').split('x'))
        values={'prompt':inp['prompt'],'seed':int(inp.get('seed',0)),'width':width,'height':height,'frames':int(inp.get('frames',121)),'image':''}
        with provider_egress.client(origin=p['url'],timeout=120,trust_env=not p.get('local',False)) as client:
            remote=job.get('provider_job_id')
            if not remote:
                if refs:
                    ref=refs[0]
                    with (s.ASSETS/ref['path']).open('rb') as file:
                        upload=checked(client.post(url+'/upload/image',files={'image':(ref['name'],file,ref['mime'])}))
                        values['image']=upload['name']
                def replace(value):
                    if isinstance(value,dict): return {k:replace(v) for k,v in value.items()}
                    if isinstance(value,list): return [replace(v) for v in value]
                    if isinstance(value,str):
                        for key,replacement in values.items():
                            if value=='{{'+key+'}}': return replacement
                            value=value.replace('{{'+key+'}}',str(replacement))
                    return value
                remote=checked(client.post(url+'/prompt',json={'prompt':replace(template),'client_id':job['id']})).get('prompt_id')
                if not remote: raise ValueError('ComfyUI 没有返回任务编号')
                s.job_update(job['id'],provider_job_id=remote)
            self.progress(job,'ComfyUI 排队或生成中')
            while not self.halt.wait(2):
                if self.cancelled(job):
                    # /interrupt affects all users of a ComfyUI instance, so don't call it blindly.
                    client.post(url+'/queue',json={'delete':[remote]})
                    raise InterruptedError('已取消本工作室任务；正在运行的共享引擎任务可能继续完成')
                history=checked(client.get(url+'/history/'+remote)).get(remote)
                if not history: continue
                if history.get('status',{}).get('status_str')=='error': raise ValueError('ComfyUI 执行失败，请检查引擎日志和工作流节点')
                outputs=[]
                for output in history.get('outputs',{}).values():
                    for key in ('images','gifs','videos','audio'):
                        for file in output.get(key,[]):
                            response=client.get(url+'/view',params={k:file[k] for k in ('filename','subfolder','type') if k in file})
                            response.raise_for_status()
                            temp=s.DATA/(s.uid()+Path(file['filename']).suffix)
                            try: temp.write_bytes(response.content); outputs.append(register(job,temp,file['filename']))
                            finally: temp.unlink(missing_ok=True)
                if not outputs: raise ValueError('工作流未保存媒体输出，请添加保存图像或视频节点')
                return {'assets':outputs}
        raise InterruptedError()

    def video_api(self,job,p):
        """Configurable async JSON video gateway. Explicit routes avoid false universal compatibility."""
        inp=job['input']; url=p['url'].rstrip('/')
        if inp.get('end_asset_id'):raise ValueError('当前视频网关未配置尾帧协议，请清除尾帧或选择支持尾帧的外部 Provider')
        headers={'Authorization':'Bearer '+p['api_key']} if p.get('api_key') else {}
        body={**p.get('request_defaults',{}),**inp.get('parameters',{}),'model':p.get('model'),'prompt':inp['prompt']}
        if assets_for(job): raise ValueError('此视频网关尚未配置媒体上传协议，请使用文生视频或本地参考图适配器')
        with provider_egress.client(origin=p['url'],timeout=120,headers=headers,trust_env=not p.get('local',False)) as client:
            remote=job.get('provider_job_id')
            if not remote:
                result=checked(client.post(url+p.get('submit_path','/videos'),json=body))
                remote=result.get('id') or result.get('task_id')
                if not remote: raise ValueError('视频网关必须返回 id 或 task_id')
                s.job_update(job['id'],provider_job_id=remote)
            while not self.halt.wait(3):
                if self.cancelled(job): raise InterruptedError()
                status=checked(client.get(url+p.get('status_path','/videos/{id}').replace('{id}',quote(str(remote),safe=''))))
                self.progress(job,status.get('status','云端生成中'),status.get('progress'))
                if status.get('status') in ('failed','error','cancelled'): raise ValueError(str(status.get('error','视频生成失败')))
                if status.get('status') in ('completed','succeeded','success'):
                    target=status.get('url') or status.get('video_url') or (status.get('output') or {}).get('url')
                    if not target: raise ValueError('视频网关未返回 url/video_url/output.url')
                    return {'assets':[download_result(job,target,'.mp4')]}
        raise InterruptedError()

    def export(self,job):
        inp=job['input']
        if inp.get('editor_timeline') is not None:
            return self.export_editor(job)
        items=inp.get('timeline',[])
        if not items: raise ValueError('时间线没有镜头')
        executable=ffmpeg_executable()
        work=Path(tempfile.mkdtemp(prefix=f"{job['id']}-a{job.get('attempt_number',0)}-",dir=s.DATA))
        try:
            def production_asset(asset_id):
                with s.db() as c:
                    return c.execute('''SELECT a.* FROM assets a
                        JOIN projects origin ON origin.id=a.project_id
                        JOIN projects target ON target.id=%s
                        WHERE a.id=%s AND COALESCE(a.production_id,origin.production_id,origin.id)=COALESCE(target.production_id,target.id)
                        AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='asset' AND d.item_id=a.id)
                    ''',(job['project_id'],asset_id)).fetchone()
            files=[]
            width,height=(int(x) for x in inp.get('resolution','1280x720').split('x'))
            if width<64 or height<64 or width>4096 or height>4096: raise ValueError('导出分辨率无效')
            for i,item in enumerate(items):
                row=production_asset(item['asset_id'])
                if not row or row['kind'] not in ('image','video'): raise ValueError('时间线引用了无效的图像或视频')
                duration=max(0.1,min(float(item.get('duration',5)),600)); start=max(0,float(item.get('start',0)))
                info=probe(s.ASSETS/row['path']) if row['kind']=='video' else {'has_audio':False}
                if row['kind']=='video' and start+duration>info['duration']+.08:
                    raise ValueError(f'第 {i+1} 个片段超出素材时长 {info["duration"]:.2f} 秒，请缩短裁剪范围')
                target=work/f'{i:04d}.mp4'
                args=[executable,'-y']
                if row['kind']=='image': args+=['-loop','1']
                else: args+=['-ss',str(start)]
                args+=['-i',str(s.ASSETS/row['path'])]
                if not info['has_audio']:args+=['-f','lavfi','-i','anullsrc=r=48000:cl=stereo']
                volume=max(0,min(float(item.get('volume',1)),2))
                fade=min(.3,duration/4)
                video_filter=f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=24,setpts=PTS-STARTPTS'
                if inp.get('transition')=='fade':video_filter+=f',fade=t=in:st=0:d={fade},fade=t=out:st={duration-fade}:d={fade}'
                args+=['-map','0:v:0','-map','0:a:0' if info['has_audio'] else '1:a:0','-t',str(duration),'-vf',video_filter,'-af',f'aresample=48000,apad,atrim=duration={duration},asetpts=PTS-STARTPTS,volume={volume}','-c:v','libx264','-preset','fast','-pix_fmt','yuv420p','-c:a','aac','-ac','2','-ar','48000',str(target)]
                self.run_process(job,args,work/f'{i}.log',f'合成镜头 {i+1}/{len(items)}')
                files.append(target)
            listing=work/'concat.txt'; listing.write_text('\n'.join(f"file '{p.name}'" for p in files),encoding='utf-8')
            output=work/'成片.mp4'
            args=[executable,'-y','-f','concat','-safe','0','-i',str(listing)]
            audio_id=inp.get('audio_id')
            subtitle_id=inp.get('subtitle_id')
            if audio_id:
                audio=production_asset(audio_id)
                if not audio or audio['kind']!='audio': raise ValueError('配乐素材无效')
                music_volume=max(0,min(float(inp.get('music_volume',.3)),2))
                args+=['-stream_loop','-1','-i',str(s.ASSETS/audio['path']),'-filter_complex',f'[1:a]volume={music_volume}[music];[0:a][music]amix=inputs=2:duration=first:normalize=0[mix]','-map','0:v:0','-map','[mix]']
            else:args+=['-map','0:v:0','-map','0:a:0']
            if subtitle_id:
                subtitle=production_asset(subtitle_id)
                if not subtitle or subtitle['kind']!='subtitle':raise ValueError('字幕素材无效')
                shutil.copyfile(s.ASSETS/subtitle['path'],work/'subtitles.srt')
                args+=['-vf',"subtitles=filename=subtitles.srt:force_style='FontName=Microsoft YaHei,FontSize=24,Outline=2,MarginV=24'",'-c:v','libx264','-preset','fast']
            else:args+=['-c:v','copy']
            args+=['-c:a','aac','-movflags','+faststart',str(output)]
            self.run_process(job,args,work/'export.log','输出 MP4')
            return {'assets':[register(job,output,'成片.mp4')]}
        finally:
            # This exact directory belongs to this execution only. A late
            # attempt must never remove a replacement's FFmpeg intermediates.
            if work.parent==s.DATA: shutil.rmtree(work,ignore_errors=True)

    def export_editor(self,job):
        inp=job['input']; executable=ffmpeg_executable()
        with s.db() as c:
            target=c.execute('SELECT COALESCE(production_id,id) AS production_id FROM projects WHERE id=%s',
                             (job['project_id'],)).fetchone()
        if not target:raise ValueError('导出项目不存在')
        work=Path(tempfile.mkdtemp(prefix=f"{job['id']}-a{job.get('attempt_number',0)}-",dir=s.DATA))
        try:
            width,height=(int(x) for x in inp.get('resolution','1280x720').split('x'))
            def lookup(asset_id):
                with s.db() as c:
                    row=c.execute('''SELECT a.*, COALESCE(a.production_id,origin.production_id,origin.id) AS resolved_production_id FROM assets a
                        JOIN projects origin ON origin.id=a.project_id
                        JOIN projects target ON target.id=%s
                        WHERE a.id=%s AND COALESCE(a.production_id,origin.production_id,origin.id)=COALESCE(target.production_id,target.id)
                        AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='asset' AND d.item_id=a.id)
                    ''',(job['project_id'],asset_id)).fetchone()
                if not row:return None
                result=dict(row);result['absolute_path']=str(s.ASSETS/result['path'])
                result['production_id']=result.pop('resolved_production_id')
                return result
            output=work/'成片.mp4'
            compiler=EditorRenderCompiler(
                job['project_id'],inp['editor_timeline'],(width,height),work,lookup,probe,
                production_id=target['production_id']
            )
            plan=compiler.compile(executable,output)
            self.run_process(
                job,plan.args,work/'editor-export.log',
                f'合成高级时间线：{plan.visual_count} 个画面，{plan.audio_count} 路声音，{plan.text_count} 条文字'
            )
            return {'assets':[register(job,output,'成片.mp4')], 'render':{
                'mode':'editor','duration':plan.duration,'visual_count':plan.visual_count,
                'audio_count':plan.audio_count,'text_count':plan.text_count,
            }}
        finally:
            if work.parent==s.DATA:shutil.rmtree(work,ignore_errors=True)
    def run_process(self,job,args,log_path,phase):
        self.progress(job,phase)
        with log_path.open('w',encoding='utf-8') as log:
            proc=subprocess.Popen(args,cwd=log_path.parent,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            try:
                while proc.poll() is None:
                    if self.cancelled(job):raise InterruptedError()
                    time.sleep(0.3)
            finally:
                # Includes DB errors, not only a user cancellation.
                # Popen identifies the one child this invocation owns.
                if proc.poll() is None:
                    proc.terminate()
                    try:proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill();proc.wait(timeout=10)
        if proc.returncode: raise ValueError('导出失败：'+log_path.read_text(encoding='utf-8',errors='replace')[-600:])
