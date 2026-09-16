"""Per-call secret protection for provider responses, errors and persistence."""
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import quote, quote_plus

_active = ContextVar('provider_secrets_in_use', default=())


def scrub(value):
    if isinstance(value, str):
        for secret in _active.get():
            value = value.replace(secret, '[REDACTED]')
        return value
    if isinstance(value, dict):
        return {scrub(key): scrub(child) for key, child in value.items()}
    if isinstance(value, list):
        return [scrub(child) for child in value]
    if isinstance(value, tuple):
        return tuple(scrub(child) for child in value)
    return value


@contextmanager
def protect(secret):
    values = tuple(dict.fromkeys((secret, quote(secret, safe=''), quote_plus(secret)))) if secret else ()
    token = _active.set((*_active.get(), *values))
    try:
        yield
    except Exception as exc:
        # Preserve transport/recoverable/cancel types, but never let raw upstream
        # echoes reach the worker's durable error or the web exception handler.
        exc.args = scrub(exc.args)
        raise
    finally:
        _active.reset(token)
