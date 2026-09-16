"""Production Source Library domain operations and event extraction contract."""
from __future__ import annotations

import json
import re
import time

from . import store as s

SOURCE_TYPES = {'txt', 'markdown', 'manual'}
IMPORT_HEADING = re.compile(r'(?m)^(?:#{1,6}\s+.+|第[0-9一二三四五六七八九十百千万零〇两]+[章节回].*)$')
EVENT_SCHEMA = {
    'type': 'object', 'additionalProperties': False,
    'properties': {'events': {'type': 'array', 'items': {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'characters': {'type': 'array', 'items': {'type': 'string'}},
            'summary': {'type': 'string'},
            'importance': {'type': 'string', 'enum': ['low', 'medium', 'high']},
            'emotion': {'type': 'string'},
            'continuity': {'type': 'object'},
        },
        'required': ['characters', 'summary', 'importance', 'emotion', 'continuity'],
    }}},
    'required': ['events'],
}
SYSTEM_PROMPT = (
    '你是影视改编资料分析员。只提取原文明确发生的事件，不续写、不改编。'
    '按发生顺序输出结构化事件；人物使用原文姓名；continuity 记录会影响后续章节的状态。'
)


def split_chapters(content: str):
    text = content.replace('\r\n', '\n').strip()
    if not text:
        raise ValueError('原著内容不能为空')
    matches = list(IMPORT_HEADING.finditer(text))
    if not matches:
        return [('正文', text)]
    chapters = []
    prefix = text[:matches[0].start()].strip()
    if prefix:
        chapters.append(('前言', prefix))
    for index, match in enumerate(matches):
        title = match.group(0).lstrip('#').strip()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        chapters.append((title, body))
    return chapters


def validate_events(value):
    if not isinstance(value, dict) or set(value) != {'events'}:
        raise ValueError('事件提取结果顶层只能包含 events')
    rows = value['events']
    if not isinstance(rows, list):
        raise ValueError('事件提取结果缺少 events 数组')
    result = []
    required = {'characters', 'summary', 'importance', 'emotion', 'continuity'}
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError('事件字段必须严格包含 characters、summary、importance、emotion、continuity')
        if not isinstance(row['summary'], str) or not row['summary'].strip():
            raise ValueError('事件摘要不能为空')
        if not isinstance(row['emotion'], str):
            raise ValueError('事件情绪必须是字符串')
        characters = row['characters']
        continuity = row['continuity']
        importance = row['importance']
        if not isinstance(characters, list) or not all(isinstance(item, str) for item in characters):
            raise ValueError('事件人物格式无效')
        if not isinstance(continuity, dict) or importance not in ('low', 'medium', 'high'):
            raise ValueError('事件重要性或连续性格式无效')
        result.append({
            'characters': [item.strip() for item in characters if item.strip()],
            'summary': row['summary'].strip(), 'importance': importance,
            'emotion': row['emotion'].strip(), 'continuity': continuity,
        })
    return result


def replace_events(job, rows):
    marker = job['input'].get('source_event_extraction') or {}
    chapter_id = marker.get('chapterId'); production_id = marker.get('productionId')
    expected_revision = marker.get('chapterRevision')
    validated = validate_events({'events': rows})
    now = time.time()
    with s.db() as connection:
        active = connection.execute(
            "SELECT status FROM jobs WHERE id=%s", (job['id'],)
        ).fetchone()
        if not active or active['status'] != 'running':
            raise ValueError('事件提取任务已失效，未写入提取结果')
        chapter = connection.execute('''SELECT c.id,c.revision,d.production_id FROM source_chapters c
            JOIN source_documents d ON d.id=c.source_id WHERE c.id=%s
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='source' AND x.item_id=d.id)
            AND NOT EXISTS(SELECT 1 FROM deleted_items x WHERE x.kind='chapter' AND x.item_id=c.id)''',(chapter_id,)).fetchone()
        if not chapter or chapter['production_id'] != production_id:
            raise ValueError('事件提取任务的章节归属已失效')
        if chapter['revision'] != expected_revision:
            raise ValueError('章节已在提取期间更新，旧结果未写入；请重新提取')
        previous_ids = [row['id'] for row in connection.execute(
            'SELECT id FROM source_events WHERE chapter_id=%s', (chapter_id,)
        ).fetchall()]
        connection.execute('DELETE FROM source_events WHERE chapter_id=%s',(chapter_id,))
        for order, row in enumerate(validated, 1):
            connection.execute('INSERT INTO source_events VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(
                s.uid('source-event-'),production_id,chapter_id,order,s.dumps(row['characters']),
                row['summary'],row['importance'],row['emotion'],s.dumps(row['continuity']),
                job['id'],now,now,
            ))
        from .adaptation import mark_adaptation_stale
        production_revision = mark_adaptation_stale(
            connection, production_id, chapter_ids=[chapter_id], event_ids=previous_ids,
        )
        if production_revision is not None:
            s.event(job['project_id'], {'type': 'production', 'revision': production_revision}, connection=connection)
    return validated
