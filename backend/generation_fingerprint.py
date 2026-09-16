"""Deterministic provenance for Film Bible shot generations."""
from __future__ import annotations

import hashlib
import json

from .production_context import compose_project_document


FINGERPRINT_VERSION = 1
PROMPT_COMPILER_VERSION = 1
SHOT_VARIABLE_FIELDS = (
    'scene', 'characters', 'action', 'emotion', 'camera', 'audio',
    'image_prompt', 'video_prompt', 'duration',
)


def _style_version(document):
    film_bible = document.get('filmBible') or {}
    explicit = film_bible.get('styleVersion')
    if explicit is not None:
        return explicit
    style = film_bible.get('style')
    if isinstance(style, dict) and style.get('version') is not None:
        return style['version']
    return 1


def _bound_versions(document, shot):
    bindings = shot.get('assetBindings') or {}
    visual = ((document.get('filmBible') or {}).get('visual') or {})
    cards = visual.get('cards') or {}
    versions = visual.get('versions') or {}
    result = []
    for item in bindings.get('characters') or []:
        version = versions.get(str(item.get('versionId') or '')) or {}
        if (cards.get(version.get('cardId')) or {}).get('status') == 'deprecated':
            continue
        result.append({
            'group': 'character',
            'role': str(item.get('role') or ''),
            'versionId': str(item.get('versionId') or ''),
        })
    scene = bindings.get('scene')
    if isinstance(scene, dict) and scene.get('versionId'):
        version = versions.get(str(scene['versionId'])) or {}
        if (cards.get(version.get('cardId')) or {}).get('status') != 'deprecated':
            result.append({'group': 'scene', 'role': '', 'versionId': str(scene['versionId'])})
    for item in bindings.get('props') or []:
        version = versions.get(str(item.get('versionId') or '')) or {}
        if (cards.get(version.get('cardId')) or {}).get('status') == 'deprecated':
            continue
        result.append({
            'group': 'prop',
            'role': str(item.get('role') or ''),
            'versionId': str(item.get('versionId') or ''),
        })
    return result


def generation_fingerprint_payload(
    document, shot, provider_id, model_id,
    prompt_compiler_version=PROMPT_COMPILER_VERSION, production_context=None,
):
    """Return only generation-semantic, JSON-canonical inputs."""
    if production_context is not None:
        document = compose_project_document(document, production_context)
    return {
        'shotVariables': {key: shot.get(key) for key in SHOT_VARIABLE_FIELDS},
        'boundVisualVersions': _bound_versions(document, shot),
        'styleVersion': _style_version(document),
        'promptCompilerVersion': prompt_compiler_version,
        'model_id': str(model_id or ''),
    }


def build_generation_fingerprint(
    document, shot, provider_id, model_id,
    prompt_compiler_version=PROMPT_COMPILER_VERSION, production_context=None,
):
    payload = generation_fingerprint_payload(
        document, shot, provider_id, model_id, prompt_compiler_version,
        production_context,
    )
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    )
    return {
        'version': FINGERPRINT_VERSION,
        'algorithm': 'sha256',
        'hash': hashlib.sha256(canonical.encode('utf-8')).hexdigest(),
        'inputs': payload,
    }


def fingerprint_status(saved, current):
    if not isinstance(saved, dict) or not saved.get('hash'):
        return 'unknown'
    return 'current' if saved.get('hash') == current.get('hash') else 'stale'
