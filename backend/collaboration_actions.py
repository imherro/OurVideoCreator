"""Two existing editor actions that cross a small, explicit object boundary."""
import json
from fastapi import APIRouter, HTTPException
from pydantic import Field
from . import collaboration as collab, owned_content as owned, identity, store as s
from .collaboration_routes import StrictBody,Version
from .collaboration_validation import object_content, envelope

router=APIRouter(prefix='/api/projects/{pid}')


class ObjectVersion(Version):
    id:str


class Promotion(StrictBody):
    node:ObjectVersion
    graph:ObjectVersion
    script_revision:int=Field(ge=1)
    script_assignment_epoch:int=Field(ge=1)


@router.post('/script-promotion')
def promote(pid:str,body:Promotion):
    from .adaptation import save_script_row,script_to_api,SCRIPT_FIELDS
    with s.db() as c:
        collab.lock_identity(c);scope=collab.project_scope(c,pid,'editor')
        script=owned.load(c,scope['production_id'],'script',pid,write=True)
        owned.authorize(c,script,body.script_revision,body.script_assignment_epoch)
        # commands below obtains ordered row locks and checks the exact versions
        # used here. Any intervening change rolls this entire transaction back.
        node=collab.load(c,pid,body.node.id);graph=collab.load(c,pid,body.graph.id)
        if node['kind']!='node' or graph['kind']!='graph':raise HTTPException(422,'只能提升本集自由文本节点')
        source=object_content(node)['node'];data=source['data']
        if data.get('kind')!='text' or not str(data.get('text') or '').strip():raise HTTPException(422,'请先填写文本节点正文')
        collab.editable(c,node);collab.expected(node,body.node.expected_revision,body.node.assignment_epoch)
        previous=json.loads(script['metadata']).get('projectionNodeId')
        metadata={**json.loads(script['metadata']),'origin':'canvas','projectionNodeId':source['id']}
        value=script_to_api(script);payload={key:value[key] for key in SCRIPT_FIELDS}
        payload['body']=data['text'].strip()
        save_script_row(c,script,payload,actor_id=identity.current().user_id)
        c.execute('UPDATE episode_scripts SET metadata=%s WHERE project_id=%s',(s.dumps(metadata),pid))
        structure=object_content(graph)
        if previous!=source['id']:
            structure['positions'].pop(previous,None)
            structure['nodeOrder']=[nid for nid in structure['nodeOrder'] if nid!=previous]
        # A canonical projection is a source, never a downstream editable target.
        structure['edges']=[edge for edge in structure['edges']
            if edge['target']!=source['id'] and previous not in (edge['source'],edge['target'])]
        result=collab.commands(c,pid,creates=[],updates=[{**body.graph.model_dump(),'content':structure}],
            deletes=[body.node.model_dump()],_action='script_promote',_promote_node_id=node['id'])
        latest=owned.load(c,scope['production_id'],'script',pid)
        owned.notify(c,latest,'promote')
        return {'script':owned.public(latest),'objects':result}


class Capture(StrictBody):
    director:ObjectVersion
    graph:ObjectVersion
    asset_id:str
    node:dict


@router.post('/director-captures')
def capture(pid:str,body:Capture):
    with s.db() as c:
        collab.lock_identity(c);scope=collab.project_scope(c,pid,'editor')
        # Order matches commands. No image upload/decoding or network in this transaction.
        rows={oid:collab.load(c,pid,oid,write=True) for oid in sorted({body.director.id,body.graph.id})}
        director,graph=rows[body.director.id],rows[body.graph.id]
        if director['kind']!='director' or graph['kind']!='graph':raise HTTPException(422,'导演台或结构对象无效')
        collab.editable(c,director);collab.expected(director,body.director.expected_revision,body.director.assignment_epoch)
        collab.expected(graph,body.graph.expected_revision,body.graph.assignment_epoch)
        asset=c.execute('''SELECT * FROM assets a WHERE a.id=%s AND a.project_id=%s AND a.kind='image'
            AND NOT EXISTS(SELECT 1 FROM deleted_items d WHERE d.kind='asset' AND d.item_id=a.id)''',(body.asset_id,pid)).fetchone()
        if not asset:raise HTTPException(422,'截图须为当前分集已上传的图片素材')
        node=body.node
        envelope('node',{'node':node})
        if not isinstance(node.get('data'),dict) or node['data'].get('kind')!='image':raise HTTPException(422,'截图目标必须是新图像节点')
        node={**node,'data':{**node['data'],'asset_ids':[body.asset_id],
            'director_capture':{'object_id':director['id'],'revision':director['revision'],
                                'assignment_epoch':director['assignment_epoch'],'asset_id':body.asset_id}}}
        structure=object_content(graph)
        structure['nodeOrder'].append(node['id'])
        result=collab.commands(c,pid,creates=[{'kind':'node','content':{'node':node}}],
            updates=[{**body.graph.model_dump(),'content':structure}],deletes=[],_action='director_capture')
        identity.audit(c,'director.capture','director',director['id'],workspace_id=scope['workspace_id'],
            production_id=scope['production_id'],payload={'revision':director['revision'],'asset_id':body.asset_id})
        return result
