"""Canonical Production context and Episode document projections."""
from __future__ import annotations

import copy
import json

from .project_schema import empty_film_bible, empty_generation_policy, migrate_document
from .adaptation import empty_adaptation_context, normalize_adaptation_context


CONTEXT_SCHEMA_VERSION = 2
SHARED_DOCUMENT_KEYS = ('filmBible', 'generationPolicy', 'style')
PRODUCTION_ONLY_KEYS = SHARED_DOCUMENT_KEYS + (
    'adaptationPlan', 'episodePlans', 'monetizationPlan',
)


def new_production_context(generation_policy=None):
    return {
        'schemaVersion': CONTEXT_SCHEMA_VERSION,
        'filmBible': empty_film_bible(),
        'generationPolicy': copy.deepcopy(
            generation_policy or empty_generation_policy()
        ),
        'style': '电影写实',
        **empty_adaptation_context(),
    }


def normalize_production_context(value, generation_policy=None):
    source = value if isinstance(value, dict) else {}
    result = new_production_context(generation_policy)
    film_bible = source.get('filmBible')
    if isinstance(film_bible, dict):
        result['filmBible'] = copy.deepcopy(film_bible)
    film_bible = result['filmBible']
    visual = film_bible.setdefault('visual', {})
    visual.setdefault('cards', {})
    visual.setdefault('versions', {})
    for key in ('continuity', 'style', 'story'):
        film_bible.setdefault(key, {})
    voices = film_bible.setdefault('voices', {})
    voices.setdefault('profiles', {})
    film_bible.setdefault('styleVersion', 1)
    policy = source.get('generationPolicy')
    if isinstance(policy, dict):
        result['generationPolicy'] = copy.deepcopy(policy)
    for kind in ('text', 'image', 'video'):
        result['generationPolicy'].setdefault(kind, None)
    if 'style' in source:
        result['style'] = copy.deepcopy(source['style'])
    adaptation = normalize_adaptation_context(source)
    for key in ('adaptationPlan', 'episodePlans', 'monetizationPlan'):
        result[key] = adaptation[key]
    return result


def production_context_from_document(document, generation_policy=None):
    value = migrate_document(document)
    return normalize_production_context(
        {key: value.get(key) for key in SHARED_DOCUMENT_KEYS},
        generation_policy,
    )


def episode_document_from_document(document):
    value = migrate_document(document)
    for key in PRODUCTION_ONLY_KEYS:
        value.pop(key, None)
    return value


def compose_project_document(episode_document, production_context):
    value = migrate_document(episode_document)
    context = normalize_production_context(production_context)
    for key in SHARED_DOCUMENT_KEYS:
        value[key] = copy.deepcopy(context[key])
    return value


def merge_migration_contexts(documents, generation_policy=None):
    """Merge Phase 1A Episode contexts without silently choosing one Episode.

    Blank/default Episodes do not conflict with an explicitly customized value.
    Distinct Visual IDs are unioned. Every conflicting non-default shared value
    aborts migration so the source documents remain available for manual repair.
    """
    contexts = [
        production_context_from_document(document, generation_policy)
        for document in documents
    ]
    if not contexts:
        return new_production_context(generation_policy)
    default = new_production_context(generation_policy)
    merged = copy.deepcopy(default)

    def resolve(label, values, default_value):
        custom = [value for value in values if value != default_value]
        if not custom:
            return copy.deepcopy(default_value)
        candidate = custom[0]
        if any(value != candidate for value in custom[1:]):
            raise ValueError(f'Production 共享资料迁移发现冲突：{label}')
        return copy.deepcopy(candidate)

    merged['style'] = resolve(
        'style', [context['style'] for context in contexts], default['style'],
    )
    merged['generationPolicy'] = resolve(
        'generationPolicy',
        [context['generationPolicy'] for context in contexts],
        default['generationPolicy'],
    )
    film_keys = set(default['filmBible'])
    for context in contexts:
        film_keys.update(context['filmBible'])
    for key in sorted(film_keys - {'visual'}):
        baseline = default['filmBible'].get(key)
        merged['filmBible'][key] = resolve(
            f'filmBible.{key}',
            [context['filmBible'].get(key, baseline) for context in contexts],
            baseline,
        )
    target_visual = merged['filmBible']['visual']
    for context in contexts:
        visual = context['filmBible']['visual']
        for collection in ('cards', 'versions'):
            target = target_visual[collection]
            for item_id, item in visual[collection].items():
                if item_id in target and target[item_id] != item:
                    raise ValueError(
                        f'Production 共享 Film Bible 迁移发现冲突的视觉编号 {item_id}'
                    )
                target.setdefault(item_id, copy.deepcopy(item))
    return merged


def read_project_state(connection, project_id, *, for_update=False):
    suffix = ' FOR UPDATE' if for_update else ''
    project = connection.execute(
        'SELECT * FROM projects WHERE id=%s' + suffix, (project_id,)
    ).fetchone()
    if not project:
        return None
    production = connection.execute(
        'SELECT * FROM productions WHERE id=%s' + suffix, (project['production_id'],)
    ).fetchone()
    if not production or not production['shared_context']:
        raise ValueError('项目缺少 Production 共享上下文')
    episode_document = json.loads(project['document'])
    context = normalize_production_context(json.loads(production['shared_context']))
    return {
        'project': project,
        'production': production,
        'episode_document': episode_document,
        'production_context': context,
        'document': compose_project_document(episode_document, context),
    }
