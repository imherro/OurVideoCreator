"""Read-only role inbox projected from existing production state."""
from fastapi import APIRouter
from . import store as s
from .workflow_routes import view
from .workflow_reviews import inbox
from .sample_reviews import state as review_state

router=APIRouter(prefix='/api/productions/{production_id}/workflow')


@router.get('/tasks')
def tasks(production_id:str):
    with s.db() as c:
        staff=view(c,production_id)
        if not staff['enabled']:return {'enabled':False,'tasks':[]}
        reviews=inbox(c,production_id);roles=staff['my_roles'];actor=staff['actor_id'];items=[]
        def add(role,title,next_step,stage,episode=None,recipient=''):
            items.append({'role':role,'title':title,'next_step':next_step,'stage':stage,
                'project_id':episode['id'] if episode else None,'episode_no':episode['episode_no'] if episode else None,'recipient':recipient})
        if 'producer' in roles:
            for role in ('writer','artist','editor'):
                if not staff['effective_defaults'][role]:
                    name={'writer':'编剧','artist':'资产师','editor':'剪辑师'}[role]
                    add('producer',f'默认{name}待安排','请明确作品默认分工，避免新内容无人负责','staff')
        for script in reviews['scripts']:
            if 'producer' in roles and script['status']=='review':add('producer',f"第 {script['episode_no']} 集剧本待验收",'阅读当前版本后批准或退回','reviews',script,'编剧')
            if 'writer' in roles and script['assignee_id']==actor:
                add('writer',f"第 {script['episode_no']} 集剧本",{'approved':'此版本已批准；后续修改需重新提交','review':'等待制片人验收','returned':'按退回意见修改后重新提交'}.get(script['status'],'完成剧本并提交制片人验收'),'script',script,'制片人')
        if 'writer' in roles:
            chapters=[item for item in staff['items'] if item['kind']=='chapter' and item['assignee_id']==actor]
            if chapters:add('writer',f'负责 {len(chapters)} 个原著章节','整理章节，作为改编与分集剧本依据','source')
            if staff['effective_defaults']['writer']==actor:add('writer','原著与改编策划','导入原著、整理改编方向和分集规划','adaptation',recipient='制片人')
        assets=reviews['assets']
        if 'producer' in roles:
            pending=sum(row['status']=='pending_review' for row in assets)
            if pending:add('producer',f'{pending} 项共享资产待验收','核对资产内容和参考素材后验收','reviews',recipient='资产师')
        if 'artist' in roles:
            owned=[row for row in assets if row['assignee_id']==actor]
            if owned:add('artist',f'负责 {len(owned)} 项共享资产','完善角色、场景、服装、道具与音色，提交制片人验收','art',recipient='制片人')
            if staff['effective_defaults']['artist']==actor:add('artist','共享资产建立与分镜新资产','建立新资产，接手抽卡师分镜中的新资产候选','asset-candidates',recipient='抽卡师 / 制片人')
        for ep in staff['episodes']:
            delivery=c.execute('SELECT id FROM episode_deliveries WHERE project_id=%s ORDER BY version DESC LIMIT 1',(ep['id'],)).fetchone()
            sample=c.execute('SELECT id,version FROM episode_samples WHERE project_id=%s ORDER BY version DESC LIMIT 1',(ep['id'],)).fetchone()
            review=review_state(c,ep['id'],sample['id']) if sample else None
            if 'producer' in roles:
                if not ep['generator_id']:add('producer',f"第 {ep['episode_no']} 集待分配抽卡师",'安排本集制作负责人','staff',ep)
                if sample and review['status']!='approve':add('producer',f"第 {ep['episode_no']} 集样片 V{sample['version']} 待审查",'按秒帧批注，核对修改结果并批准明确版本','samples',ep,'剪辑师')
            if 'generator' in roles and ep['generator_id']==actor:
                add('generator',f"第 {ep['episode_no']} 集制作",'已交付素材；需要补镜时继续制作并生成新交付版本' if delivery else '拆镜、绑定已批准资产、生成并采纳视频，再交付剪辑素材包','storyboard',ep,'剪辑师')
            if 'editor' in roles and ep['effective_editor_id']==actor:
                next_step='等待抽卡师交付素材'
                if delivery:next_step='下载素材包，在剪映或达芬奇初剪后上传样片'
                if sample:next_step={'approve':'此版本已批准，可下载保留；新修改需上传新版本','return':'查看秒帧批注，线下修改并上传新版本、回复修改结果'}.get(review['status'],'等待制片人审查；查看并回复已有批注')
                add('editor',f"第 {ep['episode_no']} 集剪辑",next_step,'samples' if sample else 'deliveries',ep,'制片人' if delivery else '抽卡师')
        return {'enabled':True,'roles':roles,'tasks':items}
