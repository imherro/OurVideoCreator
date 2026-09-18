"""P5 ownership for the two EXISTING relational content sources.

No duplicate script/chapter payloads in collaboration_objects. Reuses P3's
identity lock and P5 version/epoch checks. Callers hold one short transaction.
"""
import time
from fastapi import HTTPException
from . import collaboration as collab, identity, store as s


def production_scope(c,production_id,needed='viewer',*,write=False):
    if write:collab.lock_identity(c)
    actor=collab.live_principal(c)
    if needed in {'writer', 'source_writer'}:
        from . import business_roles
        identity.require_production(c,actor,production_id,'viewer')
        business_roles.require_writer(c,production_id,planning=needed=='writer')
    else:
        identity.require_production(c,actor,production_id,needed)
    return c.execute('SELECT id,workspace_id FROM productions WHERE id=%s',(production_id,)).fetchone()


def load(c,production_id,kind,target_id,*,write=False):
    scope=production_scope(c,production_id,write=write)
    if kind=='script':
        sql='''SELECT sc.*,sc.project_id id,p.production_id FROM episode_scripts sc
            JOIN projects p ON p.id=sc.project_id WHERE p.production_id=%s AND sc.project_id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id)'''
    elif kind=='chapter':
        if write:
            # Deleting a whole source takes UPDATE on its parent first. KEY SHARE
            # allows unrelated chapter edits while preventing a parent deletion race.
            c.execute('''SELECT d.id FROM source_documents d JOIN source_chapters sc ON sc.source_id=d.id
                WHERE sc.id=%s AND d.production_id=%s FOR KEY SHARE OF d''',(target_id,production_id)).fetchone()
        sql='''SELECT sc.*,d.production_id FROM source_chapters sc JOIN source_documents d ON d.id=sc.source_id
            WHERE d.production_id=%s AND sc.id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id)
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='chapter' AND x.item_id=sc.id)'''
    else:raise ValueError('Unsupported owned content kind')
    row=c.execute(sql+(' FOR UPDATE OF sc' if write else ''),(production_id,target_id)).fetchone()
    collab.live_principal(c)
    if not row:raise HTTPException(404,'内容不存在')
    if write:
        # NOT EXISTS in the locking SELECT may have used a snapshot from before
        # waiting. Recheck tombstones after we actually own the row lock.
        targets=[('project',target_id)] if kind=='script' else [('chapter',target_id),('source',row['source_id'])]
        for deleted_kind,deleted_id in targets:
            if c.execute('SELECT 1 FROM deleted_items WHERE kind=%s AND item_id=%s',(deleted_kind,deleted_id)).fetchone():
                raise HTTPException(404,'内容已移入回收站')
    return {**dict(row),'kind':kind,'workspace_id':scope['workspace_id']}


def authorize(c,row,revision,assignment_epoch,*,reviewer=False):
    if reviewer:identity.require_production(c,collab.live_principal(c),row['production_id'],'manager')
    else:collab.editable(c,row)
    collab.expected(row,revision,assignment_epoch)


def snapshot(row):
    if row['kind']=='script':
        from .adaptation import _script_snapshot
        return _script_snapshot(row)
    return {key:row[key] for key in ('id','source_id','chapter_no','title','content','sort_order','revision',
        'status','assignee_id','assignment_epoch','created_by','updated_by','created','updated')}


def history_before(c,row,action):
    now=time.time();value=snapshot(row)
    if row['kind']=='script':
        c.execute('INSERT INTO episode_script_revisions(id,project_id,revision,snapshot,created) VALUES(%s,%s,%s,%s,%s)',
                  (s.uid('script-revision-'),row['id'],row['revision'],s.dumps(value),now))
    else:
        c.execute('''INSERT INTO source_chapter_revisions(chapter_id,revision,snapshot,actor_user_id,action,created)
            VALUES(%s,%s,%s,%s,%s,%s)''',(row['id'],row['revision'],s.dumps(value),identity.current().user_id,action,now))


def notify(c,row,action):
    identity.audit(c,row['kind']+'.'+action,row['kind'],row['id'],workspace_id=row['workspace_id'],
        production_id=row['production_id'],payload={'revision':row['revision'],'assignment_epoch':row['assignment_epoch']})
    targets=([row['id']] if row['kind']=='script' else [item['id'] for item in c.execute(
        'SELECT id FROM projects WHERE production_id=%s',(row['production_id'],))])
    for pid in targets:s.event(pid,{'type':row['kind'],'id':row['id'],'action':action,
        'revision':row['revision'],'assignment_epoch':row['assignment_epoch']},connection=c)


def public(row):
    if row['kind']=='script':
        from .adaptation import script_to_api
        return script_to_api(row)
    return {key:value for key,value in row.items() if key not in {'workspace_id','kind','production_id'}}


def assign(c,production_id,kind,target_id,revision,assignment_epoch,assignee_id):
    row=load(c,production_id,kind,target_id,write=True)
    authorize(c,row,revision,assignment_epoch,reviewer=True)
    if assignee_id is not None:
        user=c.execute('SELECT * FROM users WHERE id=%s AND is_active',(assignee_id,)).fetchone()
        actor=identity.Principal(assignee_id,'','','user','',0)
        if not user or not identity.can_production(c,actor,production_id,'editor'):
            raise HTTPException(422,'负责人必须是有效作品编辑成员')
        from . import business_roles
        if business_roles.workflow(c,production_id):
            business_roles.require_role(c,production_id,'writer',user_id=assignee_id)
    history_before(c,row,'assign')
    table,key=('episode_scripts','project_id') if kind=='script' else ('source_chapters','id')
    c.execute(f'''UPDATE {table} SET assignee_id=%s,assignment_epoch=assignment_epoch+1,
        revision=revision+1,updated_by=%s,updated=%s WHERE {key}=%s''',
        (assignee_id,identity.current().user_id,time.time(),target_id))
    latest=load(c,production_id,kind,target_id)
    notify(c,latest,'assign')
    from . import business_roles
    if business_roles.workflow(c,production_id):
        business_roles._changed(c,production_id,'advanced.assign',{'kind':kind,'id':target_id})
    return public(latest)


def revoke(c,user_id,*,production_id=None,workspace_id=None,lost_access_only=False):
    """Under P3 EXCLUSIVE identity lock, preserve content and invalidate epochs."""
    target=identity.Principal(user_id,'','','user','',0)
    for kind in ('script','chapter'):
        relation=('episode_scripts sc JOIN projects parent ON parent.id=sc.project_id'
                  if kind=='script' else 'source_chapters sc JOIN source_documents parent ON parent.id=sc.source_id')
        key='project_id' if kind=='script' else 'id'
        rows=c.execute(f'''SELECT sc.*,sc.{key} target_id,parent.production_id,p.workspace_id
            FROM {relation} JOIN productions p ON p.id=parent.production_id WHERE sc.assignee_id=%s
            AND (%s::text IS NULL OR p.id=%s) AND (%s::text IS NULL OR p.workspace_id=%s)
            ORDER BY sc.{key} FOR UPDATE OF sc''',(user_id,production_id,production_id,workspace_id,workspace_id)).fetchall()
        for value in rows:
            if lost_access_only and identity.can_production(c,target,value['production_id'],'editor'):continue
            row={**dict(value),'id':value['target_id'],'kind':kind}
            history_before(c,row,'revoke')
            table='episode_scripts' if kind=='script' else 'source_chapters'
            updated=c.execute(f'''UPDATE {table} SET assignee_id=NULL,assignment_epoch=assignment_epoch+1,
                revision=revision+1,updated_by=%s,updated=%s WHERE {key}=%s RETURNING *''',
                (identity.current().user_id,time.time(),row['id'])).fetchone()
            notify(c,{**row,**dict(updated),'id':row['id']},'revoke')
