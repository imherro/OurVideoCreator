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
    raise ValueError('Worker 自动回写原著事件已退役；请通过候选采纳命令写入')


def write_candidate_events(connection,job,rows):
    """Only called inside the candidate command after chapter ACL/version lock."""
    marker=job['input']['source_event_extraction']
    chapter_id=marker['chapterId'];production_id=marker['productionId']
    validated=validate_events({'events':rows});now=time.time()
    previous_ids=[row['id'] for row in connection.execute('SELECT id FROM source_events WHERE chapter_id=%s',(chapter_id,))]
    connection.execute('DELETE FROM source_events WHERE chapter_id=%s',(chapter_id,))
    for order,row in enumerate(validated,1):
        connection.execute('INSERT INTO source_events VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',(
            s.uid('source-event-'),production_id,chapter_id,order,s.dumps(row['characters']),row['summary'],
            row['importance'],row['emotion'],s.dumps(row['continuity']),job['id'],now,now))
    from .adaptation import mark_adaptation_stale
    revision=mark_adaptation_stale(connection,production_id,chapter_ids=[chapter_id],event_ids=previous_ids)
    if revision is not None:
        for project in connection.execute('SELECT id FROM projects WHERE production_id=%s',(production_id,)):
            s.event(project['id'],{'type':'production','revision':revision},connection=connection)
    return validated
