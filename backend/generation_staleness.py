"""Reconcile saved generation provenance against current project semantics."""
from __future__ import annotations

import copy

from .production_context import compose_project_document

from .generation_fingerprint import (
    PROMPT_COMPILER_VERSION,
    build_generation_fingerprint,
    fingerprint_status,
)


def _image_node_id(shot):
    return shot.get('imageNode') or (shot.get('pipeline') or {}).get('imageNodeId')


def _video_node_id(shot):
    return shot.get('videoNode') or (shot.get('pipeline') or {}).get('videoNodeId')


def _resolved_image_target(node, providers, saved):
    data = node.get('data') or {}
    inputs = saved.get('inputs') or {}
    return '', str(data.get('model_id') or inputs.get('model_id') or '')


def _descendants(edges, roots):
    found = set(roots)
    pending = list(roots)
    while pending:
        source = pending.pop()
        for edge in edges:
            if edge.get('source') == source and edge.get('target') not in found:
                found.add(edge['target'])
                pending.append(edge['target'])
    return found


def reconcile_generation_staleness(
    document, providers=(), prompt_compiler_version=PROMPT_COMPILER_VERSION,
    production_context=None,
):
    """Return a copy annotated from fingerprint comparison, without side effects."""
    value = (
        compose_project_document(document, production_context)
        if production_context is not None
        else copy.deepcopy(document)
    )
    nodes = {item.get('id'): item for item in value.get('nodes') or []}
    stale_roots = set()
    stale_shot_outputs = set()
    for shot in value.get('shots') or []:
        image_id = _image_node_id(shot)
        node = nodes.get(image_id)
        saved = ((node or {}).get('data') or {}).get('generationFingerprint')
        if not isinstance(saved, dict) or not saved.get('hash'):
            continue
        provider_id, model_id = _resolved_image_target(node, providers, saved)
        current = build_generation_fingerprint(
            value, shot, provider_id, model_id, prompt_compiler_version,
        )
        status = fingerprint_status(saved, current)
        data = node.setdefault('data', {})
        data['generationStatus'] = status
        data['currentGenerationFingerprint'] = current
        if status == 'stale':
            data['stale'] = True
            data['staleReason'] = 'generation-fingerprint-mismatch'
            stale_roots.add(image_id)
            stale_shot_outputs.update(filter(None, (image_id, _video_node_id(shot))))
        else:
            # The fingerprint is the canonical comparison of shot variables,
            # visual bindings, style version, provider, and model. Clear stale
            # flags left by older clients that compared a compiled prompt with
            # the shorter editable node prompt.
            data['stale'] = False
            data.pop('staleReason', None)
    affected = _descendants(value.get('edges') or [], stale_roots) | stale_shot_outputs
    for node_id in affected - stale_roots:
        node = nodes.get(node_id)
        data = (node or {}).get('data') or {}
        if data.get('assetId') or data.get('resultJob') or data.get('generationFingerprint'):
            data['stale'] = True
            data['staleReason'] = 'upstream-generation-stale'
    return value
