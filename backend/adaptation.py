"""Phase 3 adaptation and canonical episode-script domain contracts."""
from __future__ import annotations

import copy
import hashlib
import json
import time


WORKFLOW_STATUSES = {'draft', 'review', 'approved', 'stale'}
PAYWALL_ROLES = {'none', 'setup', 'conversion', 'retention', 'major_cliffhanger'}
SCRIPT_FIELDS = {
    'title', 'synopsis', 'body', 'estimatedDuration', 'sourceChapterRefs',
    'storyGoal', 'paywallBeat', 'characters', 'scenes', 'props',
}
LEGACY_DEFAULT_FORMAT = {
    'episodeCount': 60, 'targetDuration': 60, 'ratio': '9:16', 'platform': '红果短剧',
}


def empty_adaptation_context():
    return {
        'adaptationPlan': {
            'status': 'draft',
            'format': {
                'episodeCount': 1,
                'targetDuration': 15,
                'ratio': '16:9',
                'platform': '通用短视频',
            },
            'storyCore': {},
            'storyArc': {},
            'adaptationStrategy': {},
            'sourceEventIds': [],
        },
        'episodePlans': [],
        'monetizationPlan': {
            'mode': 'free_then_paid',
            'freeEpisodes': 1,
            'firstPaywallEpisode': 2,
            'beats': [],
        },
    }


def configure_adaptation_format(context, episode_count, target_duration, ratio, platform):
    """Initialize a complete editable plan from the user's production setup."""
    result = normalize_adaptation_context(context)
    count = max(1, min(500, int(episode_count)))
    duration = max(1, min(3000, float(target_duration)))
    result['adaptationPlan']['format'] = {
        'episodeCount': count, 'targetDuration': duration,
        'ratio': str(ratio), 'platform': str(platform),
    }
    initially_empty = not result['episodePlans'] and not result['monetizationPlan'].get('beats')
    old = {item.get('episodeNo'): item for item in result['episodePlans'] if isinstance(item, dict)}
    result['episodePlans'] = [copy.deepcopy(old.get(number) or {
        'episodeNo': number, 'sourceChapterRefs': [], 'logline': '', 'coreConflict': '',
        'emotionalBeat': '', 'hook': '', 'cliffhanger': '', 'paywallRole': 'none',
        'targetDuration': duration, 'status': 'draft',
    }) for number in range(1, count + 1)]
    money = result['monetizationPlan']
    money['freeEpisodes'] = min(3, count) if initially_empty else min(int(money.get('freeEpisodes', 0)), count)
    money['firstPaywallEpisode'] = min(4, count + 1) if initially_empty else min(max(1, int(money.get('firstPaywallEpisode', 1))), count + 1)
    money['beats'] = [beat for beat in money.get('beats', []) if beat.get('episodeNo', 0) <= count]
    return result


def has_legacy_default_format(context):
    result = normalize_adaptation_context(context)
    adaptation = result['adaptationPlan']
    return (
        adaptation['format'] == LEGACY_DEFAULT_FORMAT
        and not result['episodePlans'] and not adaptation.get('sourceEventIds')
        and all(not adaptation.get(group) for group in ('storyCore', 'storyArc', 'adaptationStrategy'))
        and not result['monetizationPlan'].get('beats')
    )


def normalize_adaptation_context(value):
    source = value if isinstance(value, dict) else {}
    result = empty_adaptation_context()
    plan = source.get('adaptationPlan')
    if isinstance(plan, dict):
        result['adaptationPlan'].update(copy.deepcopy(plan))
        supplied_format = plan.get('format')
        if isinstance(supplied_format, dict):
            result['adaptationPlan']['format'] = {
                **empty_adaptation_context()['adaptationPlan']['format'],
                **copy.deepcopy(supplied_format),
            }
    if isinstance(source.get('episodePlans'), list):
        result['episodePlans'] = copy.deepcopy(source['episodePlans'])
    money = source.get('monetizationPlan')
    if isinstance(money, dict):
        result['monetizationPlan'].update(copy.deepcopy(money))
    return result


def _string(value, label, *, allow_empty=True):
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f'{label} 必须是字符串' + ('' if allow_empty else '且不能为空'))
    return value.strip()


def _strings(value, label):
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f'{label} 必须是非空字符串数组')
    normalized = [item.strip() for item in value]
    if len(set(normalized)) != len(normalized):
        raise ValueError(f'{label} 不能包含重复编号')
    return normalized


def validate_adaptation_bundle(value, *, generated=False):
    if not isinstance(value, dict) or set(value) != {'adaptationPlan', 'episodePlans', 'monetizationPlan'}:
        raise ValueError('改编方案必须严格包含 adaptationPlan、episodePlans、monetizationPlan')
    adaptation = value['adaptationPlan']
    expected_adaptation = {'format', 'storyCore', 'storyArc', 'adaptationStrategy', 'sourceEventIds'}
    if not generated:
        expected_adaptation.add('status')
    if not isinstance(adaptation, dict) or set(adaptation) != expected_adaptation:
        raise ValueError('adaptationPlan 字段不完整或包含未知字段')
    format_value = adaptation['format']
    if not isinstance(format_value, dict) or set(format_value) != {'episodeCount', 'targetDuration', 'ratio', 'platform'}:
        raise ValueError('format 字段不完整或包含未知字段')
    episode_count = format_value['episodeCount']
    target_duration = format_value['targetDuration']
    if isinstance(episode_count, bool) or not isinstance(episode_count, int) or not 1 <= episode_count <= 500:
        raise ValueError('总集数应为 1–500 的整数')
    if isinstance(target_duration, bool) or not isinstance(target_duration, (int, float)) or not 1 <= target_duration <= 3000:
        raise ValueError('单集目标时长应为 1–3000 秒')
    normalized_adaptation = {
        'format': {
            'episodeCount': episode_count,
            'targetDuration': float(target_duration),
            'ratio': _string(format_value['ratio'], '画幅', allow_empty=False),
            'platform': _string(format_value['platform'], '平台', allow_empty=False),
        },
        'storyCore': copy.deepcopy(adaptation['storyCore']),
        'storyArc': copy.deepcopy(adaptation['storyArc']),
        'adaptationStrategy': copy.deepcopy(adaptation['adaptationStrategy']),
        'sourceEventIds': _strings(adaptation['sourceEventIds'], 'sourceEventIds') if adaptation['sourceEventIds'] else [],
    }
    for key in ('storyCore', 'storyArc', 'adaptationStrategy'):
        if not isinstance(normalized_adaptation[key], dict):
            raise ValueError(f'{key} 必须是对象')
        if generated:
            expected = {
                'storyCore': {'premise', 'theme', 'protagonist', 'goal', 'stakes'},
                'storyArc': {'opening', 'development', 'turningPoint', 'climax', 'ending'},
                'adaptationStrategy': {'audience', 'tone', 'changes', 'constraints'},
            }[key]
            if set(normalized_adaptation[key]) != expected or not all(
                isinstance(item, str) for item in normalized_adaptation[key].values()
            ):
                raise ValueError(f'{key} 不符合生成 Schema')
    if generated:
        normalized_adaptation['status'] = 'review'
    else:
        status = adaptation['status']
        if status not in WORKFLOW_STATUSES:
            raise ValueError('改编状态无效')
        normalized_adaptation['status'] = status

    plans = value['episodePlans']
    if not isinstance(plans, list) or len(plans) != episode_count:
        raise ValueError('分集规划数量必须与总集数一致')
    expected_plan = {
        'episodeNo', 'sourceChapterRefs', 'logline', 'coreConflict',
        'emotionalBeat', 'hook', 'cliffhanger', 'paywallRole',
        'targetDuration',
    }
    if not generated:
        expected_plan.add('status')
    normalized_plans = []
    for index, plan in enumerate(plans, 1):
        if not isinstance(plan, dict) or set(plan) != expected_plan:
            raise ValueError(f'第 {index} 集规划字段不完整或包含未知字段')
        if plan['episodeNo'] != index:
            raise ValueError('分集编号必须从 1 开始连续排列')
        duration = plan['targetDuration']
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 1 <= duration <= 3000:
            raise ValueError(f'第 {index} 集目标时长无效')
        paywall_role = plan['paywallRole']
        if paywall_role not in PAYWALL_ROLES:
            raise ValueError(f'第 {index} 集付费角色无效')
        normalized = {
            'episodeNo': index,
            'sourceChapterRefs': _strings(plan['sourceChapterRefs'], f'第 {index} 集原著引用') if plan['sourceChapterRefs'] else [],
            'logline': _string(plan['logline'], f'第 {index} 集一句话梗概'),
            'coreConflict': _string(plan['coreConflict'], f'第 {index} 集核心冲突'),
            'emotionalBeat': _string(plan['emotionalBeat'], f'第 {index} 集情绪节拍'),
            'hook': _string(plan['hook'], f'第 {index} 集开场钩子'),
            'cliffhanger': _string(plan['cliffhanger'], f'第 {index} 集悬念'),
            'paywallRole': paywall_role,
            'targetDuration': float(duration),
            'status': 'review' if generated else plan['status'],
        }
        if normalized['status'] not in WORKFLOW_STATUSES:
            raise ValueError(f'第 {index} 集状态无效')
        normalized_plans.append(normalized)

    money = value['monetizationPlan']
    expected_money = {'mode', 'freeEpisodes', 'firstPaywallEpisode', 'beats'}
    if not isinstance(money, dict) or set(money) != expected_money:
        raise ValueError('monetizationPlan 字段不完整或包含未知字段')
    free_episodes = money['freeEpisodes']
    first_paywall = money['firstPaywallEpisode']
    if isinstance(free_episodes, bool) or not isinstance(free_episodes, int) or not 0 <= free_episodes <= episode_count:
        if generated and isinstance(free_episodes, int) and not isinstance(free_episodes, bool):
            free_episodes = min(max(0, free_episodes), episode_count)
        else:
            raise ValueError('免费集数无效')
    if isinstance(first_paywall, bool) or not isinstance(first_paywall, int) or not 1 <= first_paywall <= episode_count + 1:
        if generated and isinstance(first_paywall, int) and not isinstance(first_paywall, bool):
            # Monetization is advisory output. Do not discard an otherwise
            # valid story plan because the model chose an episode outside the
            # requested format. episode_count + 1 explicitly means no paywall.
            first_paywall = min(max(1, first_paywall), episode_count + 1)
        else:
            raise ValueError('首个付费集编号无效')
    beats = money['beats']
    if not isinstance(beats, list):
        raise ValueError('付费卡点 beats 必须是数组')
    normalized_beats = []
    beat_fields = {'episodeNo', 'type', 'setup', 'cliffhanger', 'expectedEmotion', 'rationale'}
    for beat in beats:
        if not isinstance(beat, dict) or set(beat) != beat_fields:
            raise ValueError('付费卡点字段不完整或包含未知字段')
        episode_no = beat['episodeNo']
        if isinstance(episode_no, bool) or not isinstance(episode_no, int) or not 1 <= episode_no <= episode_count:
            if generated:
                # A beat outside the requested series has no meaningful place
                # in the plan, so omit only that optional commercial note.
                continue
            raise ValueError('付费卡点集数无效')
        normalized_beats.append({
            'episodeNo': episode_no,
            'type': _string(beat['type'], '卡点类型', allow_empty=False),
            'setup': _string(beat['setup'], '卡点铺垫'),
            'cliffhanger': _string(beat['cliffhanger'], '卡点悬念'),
            'expectedEmotion': _string(beat['expectedEmotion'], '卡点预期情绪'),
            'rationale': _string(beat['rationale'], '卡点理由'),
        })
    return {
        'adaptationPlan': normalized_adaptation,
        'episodePlans': normalized_plans,
        'monetizationPlan': {
            'mode': _string(money['mode'], '付费模式', allow_empty=False),
            'freeEpisodes': free_episodes,
            'firstPaywallEpisode': first_paywall,
            'beats': normalized_beats,
        },
    }


def adaptation_fingerprint(value):
    normalized = normalize_adaptation_context(value)
    payload = {key: normalized[key] for key in ('adaptationPlan', 'episodePlans', 'monetizationPlan')}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def source_snapshot(connection, production_id):
    rows = connection.execute('''SELECT e.*,c.revision chapter_revision FROM source_events e
        JOIN source_chapters c ON c.id=e.chapter_id
        JOIN source_documents d ON d.id=c.source_id
        WHERE d.production_id=%s AND NOT EXISTS(
            SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id
        ) AND NOT EXISTS(
            SELECT 1 FROM deleted_items x WHERE x.kind='chapter' AND x.item_id=c.id
        ) ORDER BY d.created,c.sort_order,e.event_order,e.id''',(production_id,)).fetchall()
    result = []
    for row in rows:
        result.append({
            'id': row['id'], 'chapterId': row['chapter_id'],
            'chapterRevision': row['chapter_revision'],
            'characters': json.loads(row['characters']), 'summary': row['summary'],
            'importance': row['importance'], 'emotion': row['emotion'],
            'continuity': json.loads(row['continuity']),
        })
    return result


def source_fingerprint(rows):
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _persist_production_context(connection, production, context):
    from . import store as s
    now = time.time()
    connection.execute(
        'INSERT INTO production_revisions(id,production_id,revision,shared_context,created) VALUES(%s,%s,%s,%s,%s)',
        (s.uid(), production['id'], production['revision'], production['shared_context'], now),
    )
    revision = production['revision'] + 1
    connection.execute(
        'UPDATE productions SET revision=%s,shared_context=%s,updated=%s WHERE id=%s',
        (revision, s.dumps(context), now, production['id']),
    )
    return revision


def _script_snapshot(row):
    return {
        'revision': row['revision'], 'status': row['status'], 'title': row['title'],
        'synopsis': row['synopsis'], 'sourceChapterRefs': json.loads(row['source_chapter_refs']),
        'storyGoal': row['story_goal'], 'paywallBeat': json.loads(row['paywall_beat']),
        'body': row['body'], 'estimatedDuration': row['estimated_duration'],
        'characters': json.loads(row['characters']), 'scenes': json.loads(row['scenes']),
        'props': json.loads(row['props']), 'generationJobId': row['generation_job_id'],
        'metadata': json.loads(row['metadata']),
        **{key: row[key] for key in ('assignee_id','assignment_epoch','created_by','updated_by')},
    }


def _stale_scripts(connection, production_id, *, chapter_ids=None):
    from . import store as s
    now = time.time()
    rows = connection.execute('''SELECT sc.* FROM episode_scripts sc JOIN projects p ON p.id=sc.project_id
        WHERE p.production_id=%s AND sc.status IN ('review','approved')
        ORDER BY sc.project_id FOR UPDATE OF sc''',(production_id,)).fetchall()
    changed=False
    for row in rows:
        if chapter_ids is not None:
            if not set(json.loads(row['source_chapter_refs'])).intersection(chapter_ids):continue
        elif json.loads(row['metadata']).get('adaptationLinked') is False:
            continue
        changed=True
        connection.execute(
            'INSERT INTO episode_script_revisions VALUES(%s,%s,%s,%s,%s)',
            (s.uid('script-revision-'), row['project_id'], row['revision'], s.dumps(_script_snapshot(row)), now),
        )
        connection.execute(
            "UPDATE episode_scripts SET status='stale',revision=revision+1,updated=%s WHERE project_id=%s",
            (now, row['project_id']),
        )
    return changed


def mark_adaptation_stale(connection, production_id, *, chapter_ids=(), event_ids=()):
    """Mark derived planning/scripts stale after Source Library changes."""
    from .production_context import normalize_production_context
    production = connection.execute('SELECT * FROM productions WHERE id=%s FOR UPDATE',(production_id,)).fetchone()
    if not production or not production['shared_context']:
        return None
    context = normalize_production_context(json.loads(production['shared_context']))
    adaptation = context['adaptationPlan']
    changed_chapters=set(chapter_ids)
    if event_ids:
        marks=','.join('%s' for _ in event_ids)
        changed_chapters.update(row['chapter_id'] for row in connection.execute(
            f'SELECT chapter_id FROM source_events WHERE production_id=%s AND id IN ({marks})',[production_id,*event_ids]))
    scripts_changed=_stale_scripts(connection,production_id,chapter_ids=changed_chapters) if changed_chapters else False
    relevant_chapters = {ref for plan in context['episodePlans'] for ref in plan.get('sourceChapterRefs', [])}
    relevant_events = set(adaptation.get('sourceEventIds') or [])
    if (chapter_ids or event_ids) and not (
        relevant_chapters.intersection(chapter_ids) or relevant_events.intersection(event_ids)
    ):
        return production['revision'] if scripts_changed else None
    meaningful = bool(context['episodePlans'] or adaptation.get('sourceEventIds') or any(
        adaptation.get(key) for key in ('storyCore', 'storyArc', 'adaptationStrategy')
    ))
    if not meaningful:
        return production['revision'] if scripts_changed else None
    changed = False
    if adaptation['status'] in ('review', 'approved'):
        adaptation['status'] = 'stale'; changed = True
    for plan in context['episodePlans']:
        if plan.get('status') in ('review', 'approved'):
            plan['status'] = 'stale'; changed = True
    _stale_scripts(connection, production_id)
    return _persist_production_context(connection, production, context) if changed else production['revision'] if scripts_changed else None


def seed_episode_scripts(connection, project_id):
    from . import store as s, identity
    rows = connection.execute('''SELECT p.* FROM projects p LEFT JOIN episode_scripts sc ON sc.project_id=p.id
        WHERE p.id=%s AND sc.project_id IS NULL''',(project_id,)).fetchall()
    for project in rows:
        document = json.loads(project['document'])
        # New episode initialization only; never import another episode's legacy payload.
        body = ''
        metadata = {
            'projectionNodeId': 'script-projection-' + project['id'],
        }
        if document.get('creationMode')=='direct':metadata.update({'origin':'manual','adaptationLinked':False})
        now = project['updated'] or time.time()
        connection.execute('''INSERT INTO episode_scripts(project_id,revision,status,title,synopsis,
            source_chapter_refs,story_goal,paywall_beat,body,estimated_duration,characters,scenes,props,
            generation_job_id,metadata,created,updated,assignee_id,created_by,updated_by)
            VALUES(%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',(
            project['id'], 'review' if body else 'draft', project['episode_title'] or project['name'], '',
            '[]', '', '{}', body, float(document.get('duration') or 60), '[]', '[]', '[]', None,
            s.dumps(metadata), project['created'], now,
            identity.current().user_id,identity.current().user_id,identity.current().user_id,
        ))


def script_row(connection, project_id):
    row = connection.execute('SELECT * FROM episode_scripts WHERE project_id=%s',(project_id,)).fetchone()
    return script_to_api(row) if row else None


def script_to_api(row):
    if not row:
        return None
    return {
        'project_id': row['project_id'], 'revision': row['revision'], 'status': row['status'],
        'title': row['title'], 'synopsis': row['synopsis'],
        'sourceChapterRefs': json.loads(row['source_chapter_refs']),
        'storyGoal': row['story_goal'], 'paywallBeat': json.loads(row['paywall_beat']),
        'body': row['body'], 'estimatedDuration': row['estimated_duration'],
        'characters': json.loads(row['characters']), 'scenes': json.loads(row['scenes']),
        'props': json.loads(row['props']), 'generationJobId': row['generation_job_id'],
        'metadata': json.loads(row['metadata']), 'created': row['created'], 'updated': row['updated'],
        **{key: row[key] for key in ('assignee_id','assignment_epoch','created_by','updated_by')},
    }


def validate_script(value):
    if not isinstance(value, dict) or set(value) != SCRIPT_FIELDS:
        raise ValueError('剧本必须严格包含正文、概要、来源、目标、卡点、时长与资产清单字段')
    duration = value['estimatedDuration']
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 1 <= duration <= 3000:
        raise ValueError('剧本预计时长应为 1–3000 秒')
    result = {
        'title': _string(value['title'], '剧本标题', allow_empty=False),
        'synopsis': _string(value['synopsis'], '本集概要'),
        'body': _string(value['body'], '剧本正文'),
        'estimatedDuration': float(duration),
        'sourceChapterRefs': _strings(value['sourceChapterRefs'], '剧本原著引用') if value['sourceChapterRefs'] else [],
        'storyGoal': _string(value['storyGoal'], '剧情目标'),
        'paywallBeat': copy.deepcopy(value['paywallBeat']),
        'characters': _strings(value['characters'], '角色') if value['characters'] else [],
        'scenes': _strings(value['scenes'], '场景') if value['scenes'] else [],
        'props': _strings(value['props'], '道具') if value['props'] else [],
    }
    if not isinstance(result['paywallBeat'], dict):
        raise ValueError('剧本付费卡点必须是对象')
    return result


def validate_generated_script(value):
    expected = {'title', 'synopsis', 'body', 'estimatedDuration', 'characters', 'scenes', 'props'}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError('模型剧本结果字段不完整或包含未知字段')
    for key, label in (('title','标题'),('synopsis','概要'),('body','正文')):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ValueError(f'模型剧本{label}不能为空')
    return validate_script({
        **value, 'sourceChapterRefs': [], 'storyGoal': '', 'paywallBeat': {},
    })


def project_script_to_document(connection, project_id, document, *, snapshot=None):
    row = snapshot if snapshot is not None else connection.execute('SELECT * FROM episode_scripts WHERE project_id=%s',(project_id,)).fetchone()
    if not row:
        return document
    value = copy.deepcopy(document)
    metadata = json.loads(row['metadata'])
    node_id = metadata.get('projectionNodeId') or 'script-projection-' + project_id
    nodes = value.setdefault('nodes', [])
    projections = [node for node in nodes if node.get('id') == node_id or (
        isinstance(node.get('data'), dict) and node['data'].get('canonicalScriptProjection')
    )]
    existing = next((node for node in projections if node.get('id') == node_id), projections[0] if projections else None)
    projection_ids = {node.get('id') for node in projections}
    nodes[:] = [node for node in nodes if node not in projections]
    if not row['body'].strip():
        value['edges'] = [edge for edge in value.get('edges', [])
            if edge.get('source') not in projection_ids and edge.get('target') not in projection_ids]
        return value
    text_target = (value.get('generationPolicy') or {}).get('text') or {}
    inherited_target = {}
    if text_target.get('model_id'):
        inherited_target = {
            'model_id': text_target['model_id'],
            'generationPolicyInherited': True,
        }
    data = {
        'kind': 'text', 'label': '剧本（剧本工作区投影）', 'text': row['body'],
        'canonicalScriptProjection': True, 'scriptRevision': row['revision'],
        'scriptStatus': row['status'], 'scriptOrigin': metadata.get('origin','workflow'), **inherited_target,
    }
    node = existing or {'id': node_id, 'type': 'media', 'position': {'x': 80, 'y': 80}, 'data': {}}
    # Preserve a deliberate node override.  Older projections had neither
    # field, so they inherit the production policy on their next read.
    old_data = node.get('data', {})
    if old_data.get('model_id') and old_data.get('generationPolicyInherited') is not True:
        data['model_id'] = old_data['model_id']
        data['generationPolicyInherited'] = False
    node = {**node, 'id': node_id, 'data': {**old_data, **data}}
    nodes.append(node)
    removed_ids = projection_ids - {node_id}
    if removed_ids:
        value['edges'] = [edge for edge in value.get('edges', [])
            if edge.get('source') not in removed_ids and edge.get('target') not in removed_ids]
    return value


ADAPTATION_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['adaptationPlan', 'episodePlans', 'monetizationPlan'],
    'properties': {
        'adaptationPlan': {
            'type': 'object', 'additionalProperties': False,
            'required': ['format', 'storyCore', 'storyArc', 'adaptationStrategy', 'sourceEventIds'],
            'properties': {
                'format': {'type': 'object', 'additionalProperties': False,
                    'required': ['episodeCount', 'targetDuration', 'ratio', 'platform'],
                    'properties': {
                        'episodeCount': {'type': 'integer', 'minimum': 1, 'maximum': 500},
                        'targetDuration': {'type': 'number', 'minimum': 1, 'maximum': 3000},
                        'ratio': {'type': 'string'}, 'platform': {'type': 'string'},
                    }},
                'storyCore': {'type': 'object', 'additionalProperties': False,
                    'required': ['premise', 'theme', 'protagonist', 'goal', 'stakes'],
                    'properties': {key: {'type': 'string'} for key in ('premise','theme','protagonist','goal','stakes')}},
                'storyArc': {'type': 'object', 'additionalProperties': False,
                    'required': ['opening', 'development', 'turningPoint', 'climax', 'ending'],
                    'properties': {key: {'type': 'string'} for key in ('opening','development','turningPoint','climax','ending')}},
                'adaptationStrategy': {'type': 'object', 'additionalProperties': False,
                    'required': ['audience', 'tone', 'changes', 'constraints'],
                    'properties': {key: {'type': 'string'} for key in ('audience','tone','changes','constraints')}},
                'sourceEventIds': {'type': 'array', 'items': {'type': 'string'}},
            },
        },
        'episodePlans': {'type': 'array', 'minItems': 1, 'maxItems': 500, 'items': {
            'type': 'object', 'additionalProperties': False,
            'required': ['episodeNo','sourceChapterRefs','logline','coreConflict','emotionalBeat','hook','cliffhanger','paywallRole','targetDuration'],
            'properties': {
                'episodeNo': {'type': 'integer'},
                'sourceChapterRefs': {'type': 'array', 'items': {'type': 'string'}},
                **{key: {'type': 'string'} for key in ('logline','coreConflict','emotionalBeat','hook','cliffhanger')},
                'paywallRole': {'type': 'string', 'enum': sorted(PAYWALL_ROLES)},
                'targetDuration': {'type': 'number'},
            },
        }},
        'monetizationPlan': {'type': 'object', 'additionalProperties': False,
            'required': ['mode','freeEpisodes','firstPaywallEpisode','beats'],
            'properties': {
                'mode': {'type': 'string'}, 'freeEpisodes': {'type': 'integer', 'minimum': 0},
                'firstPaywallEpisode': {'type': 'integer', 'minimum': 1},
                'beats': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                    'required': ['episodeNo','type','setup','cliffhanger','expectedEmotion','rationale'],
                    'properties': {'episodeNo': {'type': 'integer', 'minimum': 1}, **{key: {'type': 'string'} for key in ('type','setup','cliffhanger','expectedEmotion','rationale')}}}},
            }},
    },
}


SCRIPT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'required': ['title','synopsis','body','estimatedDuration','characters','scenes','props'],
    'properties': {
        'title': {'type': 'string'}, 'synopsis': {'type': 'string'},
        'body': {'type': 'string'},
        'estimatedDuration': {'type': 'number', 'minimum': 1, 'maximum': 3000},
        **{key: {'type': 'array', 'items': {'type': 'string'}} for key in ('characters','scenes','props')},
    },
}


ADAPTATION_SYSTEM_PROMPT = (
    '你是短剧总编剧。只依据提供的原著事件创建可人工审核的故事骨架、改编策略、连续分集规划和剧情商业卡点。'
    '不得编造 sourceEventIds 或 sourceChapterRefs；分集编号必须连续，数量和时长严格服从 format。'
)
SCRIPT_SYSTEM_PROMPT = (
    '你是中文短剧编剧。严格依据给定的已批准分集规划、原著章节和付费卡点，写本集可拍摄剧本。'
    '以场景标题、可见动作和对白推进，保持角色与状态连续，不写分析过程。'
)


def adaptation_bundle(context):
    normalized = normalize_adaptation_context(context)
    return {key: normalized[key] for key in ('adaptationPlan', 'episodePlans', 'monetizationPlan')}


def validate_source_references(connection, production_id, chapter_ids):
    unique = list(dict.fromkeys(chapter_ids))
    if not unique:
        return
    placeholders = ','.join('%s' for _ in unique)
    rows = connection.execute(f'''SELECT c.id FROM source_chapters c
        JOIN source_documents d ON d.id=c.source_id
        WHERE d.production_id=%s AND c.id IN ({placeholders})
        AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id)
        AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='chapter' AND x.item_id=c.id)''',[production_id,*unique]).fetchall()
    if {row['id'] for row in rows} != set(unique):
        raise ValueError('分集规划引用了不存在或属于其他 Production 的原著章节')


def prepare_manual_adaptation(current_context, submitted):
    """Manual edits invalidate approval; status-only promotion is ignored."""
    old = adaptation_bundle(current_context)
    new = validate_adaptation_bundle(submitted)
    old_adaptation_content = {key:value for key,value in old['adaptationPlan'].items() if key!='status'}
    new_adaptation_content = {key:value for key,value in new['adaptationPlan'].items() if key!='status'}
    old_plans = {plan['episodeNo']:plan for plan in old['episodePlans']}
    changed = (
        old_adaptation_content != new_adaptation_content
        or old['monetizationPlan'] != new['monetizationPlan']
        or len(old['episodePlans']) != len(new['episodePlans'])
    )
    for plan in new['episodePlans']:
        previous = old_plans.get(plan['episodeNo'])
        previous_content = {key:value for key,value in previous.items() if key!='status'} if previous else None
        current_content = {key:value for key,value in plan.items() if key!='status'}
        if previous_content != current_content:
            plan['status'] = 'draft'; changed = True
        else:
            plan['status'] = previous['status']
    new['adaptationPlan']['status'] = 'draft' if changed else old['adaptationPlan']['status']
    return new, changed


def validate_approval_ready(connection, production_id, bundle):
    value = validate_adaptation_bundle(bundle)
    adaptation = value['adaptationPlan']
    for key in ('storyCore', 'storyArc', 'adaptationStrategy'):
        if not adaptation[key] or not any(str(item).strip() for item in adaptation[key].values()):
            raise ValueError(f'{key} 尚未完成，不能批准')
    all_refs = []
    for plan in value['episodePlans']:
        if not plan['sourceChapterRefs']:
            raise ValueError(f'第 {plan["episodeNo"]} 集缺少原著章节引用')
        for key in ('logline', 'coreConflict', 'hook', 'cliffhanger'):
            if not plan[key]:
                raise ValueError(f'第 {plan["episodeNo"]} 集的 {key} 尚未完成')
        all_refs.extend(plan['sourceChapterRefs'])
    validate_source_references(connection, production_id, all_refs)
    return value


def apply_adaptation_generation(job, generated):
    raise ValueError('Worker 自动回写已退役；请通过候选采纳命令写入')


def ensure_episode_for_plan(connection, production_id, episode_no):
    from . import store as s
    from .project_schema import new_document
    from .production_context import episode_document_from_document, normalize_production_context
    row = connection.execute('''SELECT p.*,EXISTS(
        SELECT 1 FROM deleted_items d WHERE d.kind='project' AND d.item_id=p.id
    ) deleted FROM projects p WHERE p.production_id=%s AND p.episode_no=%s''',(production_id,episode_no)).fetchone()
    if row and row['deleted']:
        raise ValueError(f'第 {episode_no:02d} 集已在回收站，请先恢复后再操作')
    if row:
        if not connection.execute('SELECT 1 FROM episode_scripts WHERE project_id=%s',(row['id'],)).fetchone():
            raise ValueError('既有分集缺少正式剧本，请由管理者检查；不会自动导入旧内容')
        return row
    production = connection.execute('SELECT * FROM productions WHERE id=%s',(production_id,)).fetchone()
    if not production:
        raise ValueError('Production 不存在')
    context = normalize_production_context(json.loads(production['shared_context']))
    plan = next((item for item in context['episodePlans'] if item['episodeNo']==episode_no),None)
    if not plan:
        raise ValueError(f'第 {episode_no:02d} 集不在当前分集规划中')
    project_id = s.uid('project-'); title = f'第 {episode_no:02d} 集'
    document = new_document(context['generationPolicy'])
    document['duration'] = plan['targetDuration']; document['ratio'] = context['adaptationPlan']['format']['ratio']
    now = time.time()
    connection.execute('''INSERT INTO projects(id,name,revision,document,created,updated,production_id,episode_no,episode_title)
        VALUES(%s,%s,1,%s,%s,%s,%s,%s,%s)''',(
        project_id,title,s.dumps(episode_document_from_document(document)),now,now,production_id,episode_no,title,
    ))
    seed_episode_scripts(connection,project_id)
    from .collaboration import initialize_episode
    initialize_episode(connection, project_id)
    return connection.execute('SELECT *,0 deleted FROM projects WHERE id=%s',(project_id,)).fetchone()


def script_default_from_plan(project_id, plan):
    return {
        'project_id': project_id, 'revision': 0, 'status': 'draft',
        'assignee_id': None, 'assignment_epoch': 0, 'created_by': None, 'updated_by': None,
        'title': f'第 {plan["episodeNo"]:02d} 集', 'synopsis': plan['logline'],
        'sourceChapterRefs': list(plan['sourceChapterRefs']), 'storyGoal': plan['coreConflict'],
        'paywallBeat': {
            'role': plan['paywallRole'], 'hook': plan['hook'], 'cliffhanger': plan['cliffhanger'],
        },
        'body': '', 'estimatedDuration': plan['targetDuration'],
        'characters': [], 'scenes': [], 'props': [], 'generationJobId': None,
        'metadata': {},
    }


def save_script_row(connection, row, value, *, status='draft', generation_job_id=None, actor_id=None):
    from . import store as s
    normalized = validate_script(value)
    now = time.time()
    connection.execute(
        'INSERT INTO episode_script_revisions VALUES(%s,%s,%s,%s,%s)',
        (s.uid('script-revision-'), row['project_id'], row['revision'], s.dumps(_script_snapshot(row)), now),
    )
    connection.execute('''UPDATE episode_scripts SET revision=revision+1,status=%s,title=%s,synopsis=%s,
        source_chapter_refs=%s,story_goal=%s,paywall_beat=%s,body=%s,estimated_duration=%s,characters=%s,scenes=%s,props=%s,
        generation_job_id=%s,updated=%s,updated_by=COALESCE(%s,updated_by) WHERE project_id=%s''',(
        status,normalized['title'],normalized['synopsis'],s.dumps(normalized['sourceChapterRefs']),
        normalized['storyGoal'],s.dumps(normalized['paywallBeat']),normalized['body'],normalized['estimatedDuration'],
        s.dumps(normalized['characters']),s.dumps(normalized['scenes']),s.dumps(normalized['props']),
        generation_job_id,now,actor_id,row['project_id'],
    ))
    return script_row(connection, row['project_id'])


def apply_episode_script_generation(job, generated):
    raise ValueError('Worker 自动回写已退役；请通过候选采纳命令写入')
