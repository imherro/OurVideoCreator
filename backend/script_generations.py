"""Frozen inputs for adaptation-based episode-script generation.

The provider only sees a durable snapshot.  Admission and explicit adoption
both call this module while holding the production and target-script locks, so
changes to earlier episodes or canonical Film Bible objects cannot be hidden by
``accept_stale``.
"""
import copy
import json

from fastapi import HTTPException
from psycopg.errors import LockNotAvailable

from . import owned_content as owned
from .adaptation import (
    SCRIPT_SCHEMA,
    SCRIPT_SYSTEM_PROMPT,
    adaptation_fingerprint,
    protected_episode_nos,
    script_to_api,
)
from .episode_plans import continuity_context
from .production_context import normalize_production_context


def _lock_dependencies(connection, production_id, episode_no, chapter_ids):
    """Take short NOWAIT read locks in the existing production-first order."""
    protected = set(protected_episode_nos(connection, production_id, lock=True))
    if episode_no in protected:
        raise HTTPException(409, '本集已有采纳视频，不能生成或采纳新的正式剧本')
    try:
        connection.execute('''SELECT sc.project_id FROM episode_scripts sc
            JOIN projects p ON p.id=sc.project_id
            WHERE p.production_id=%s AND p.episode_no<%s
            ORDER BY sc.project_id FOR SHARE OF sc NOWAIT''',
            (production_id, episode_no)).fetchall()
        if chapter_ids:
            connection.execute('''SELECT sc.id FROM source_chapters sc
                JOIN source_documents d ON d.id=sc.source_id
                WHERE d.production_id=%s AND sc.id=ANY(%s)
                ORDER BY sc.id FOR SHARE OF d,sc NOWAIT''',
                (production_id, sorted(set(chapter_ids)))).fetchall()
    except LockNotAvailable:
        raise HTTPException(409, '前集、原著或视觉设定正在保存，请稍后重新提交') from None


def frozen_input(connection, project_id, production, script):
    """Build the only accepted server-owned input for a formal script job."""
    production_id = production['id']
    project = connection.execute(
        'SELECT id,episode_no FROM projects WHERE id=%s AND production_id=%s',
        (project_id, production_id),
    ).fetchone()
    if not project:
        raise HTTPException(404, '目标分集不存在')
    context = normalize_production_context(json.loads(production['shared_context']))
    episode_no = project['episode_no']
    plan = next((item for item in context['episodePlans'] if item['episodeNo'] == episode_no), None)
    if context['adaptationPlan']['status'] != 'approved' or not plan or plan['status'] != 'approved':
        raise HTTPException(409, '请先批准当前改编策划及分集规划')

    chapter_ids = list(dict.fromkeys(plan['sourceChapterRefs']))
    _lock_dependencies(connection, production_id, episode_no, chapter_ids)
    chapters = []
    for chapter_id in sorted(chapter_ids):
        chapter = owned.load(connection, production_id, 'chapter', chapter_id)
        chapters.append({key: chapter[key] for key in
            ('id', 'title', 'content', 'revision', 'assignment_epoch')})
    if {item['id'] for item in chapters} != set(chapter_ids):
        raise HTTPException(409, '分集规划引用的原著章节已变化，请先更新规划')

    continuity = continuity_context(connection, project_id, episode_no)
    from .adaptation import source_fingerprint
    marker = {
        'mode': 'adaptation',
        'productionId': production_id,
        'episodeNo': episode_no,
        'scriptRevision': script['revision'],
        'assignmentEpoch': script['assignment_epoch'],
        'adaptationFingerprint': adaptation_fingerprint(context),
        'chapterVersions': [
            {'id': item['id'], 'revision': item['revision'],
             'assignment_epoch': item['assignment_epoch']}
            for item in chapters
        ],
        'continuityFingerprint': source_fingerprint(continuity),
    }
    prompt = (
        '请生成且只生成目标单集剧本。\n已批准分集规划：'
        + json.dumps(plan, ensure_ascii=False)
        + '\n前集与锁定视觉连续性（只读，必须承接而非重演）：'
        + json.dumps(continuity, ensure_ascii=False)
        + '\n原著章节：' + json.dumps(chapters, ensure_ascii=False)
        + '\n本集现有剧本（为空则首次生成）：'
        + json.dumps(script_to_api(script), ensure_ascii=False)
    )
    return {
        'stage': 'script_generation',
        'prompt': prompt,
        'system_prompt': SCRIPT_SYSTEM_PROMPT,
        'response_schema': copy.deepcopy(SCRIPT_SCHEMA),
        'schema_version': 'episode-script/v2',
        'episode_script_generation': marker,
        'continuity_context': continuity,
    }


def freeze_target(connection, project_id, body, production, script):
    """Rebuild submitted fields and reject any dependency snapshot mismatch."""
    submitted = body.input['episode_script_generation']
    current = frozen_input(connection, project_id, production, script)
    marker = current['episode_script_generation']
    if submitted.get('episodeNo') != marker['episodeNo']:
        raise HTTPException(422, '目标分集编号不匹配')
    if submitted.get('adaptationFingerprint') != marker['adaptationFingerprint']:
        raise HTTPException(409, '改编规划已变化，请按新规划重新生成')
    if submitted.get('chapterVersions') != marker['chapterVersions']:
        raise HTTPException(409, '原著章节已变化，请重新提交')
    if submitted.get('continuityFingerprint') != marker['continuityFingerprint']:
        raise HTTPException(409, '前集剧本或 Film Bible 已变化，请重新提交')
    body.input.update(current)
    return {
        'target': {'kind': 'script', 'id': project_id,
                   'revision': script['revision'],
                   'assignment_epoch': script['assignment_epoch']},
        'references': marker['chapterVersions'],
    }


def check_adoption_dependencies(connection, job, production, script):
    """Recheck immutable creative evidence before the explicit write."""
    marker = job['input']['episode_script_generation']
    current = frozen_input(connection, job['project_id'], production, script)
    now = current['episode_script_generation']
    if marker.get('adaptationFingerprint') != now['adaptationFingerprint']:
        raise HTTPException(409, '分集规划已变化，请按新规划重新生成')
    if marker.get('chapterVersions') != now['chapterVersions']:
        raise HTTPException(409, '原著章节已变化，请按新原著重新生成')
    if marker.get('continuityFingerprint') != now['continuityFingerprint']:
        raise HTTPException(409, '前集剧本或 Film Bible 已变化，不能采纳旧候选')
    return current
