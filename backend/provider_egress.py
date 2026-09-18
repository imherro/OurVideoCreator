"""Small, DNS-pinned HTTP boundary shared by adapters and result downloads.

Private exceptions are exact deployment-owned {scheme, host, ip, port} tuples,
not user input or an SSRF-disable switch. Every redirect traverses this transport.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from .provider_redaction import scrub
from urllib.parse import urlsplit

import httpx

EXCEPTIONS_ENV = 'OVC_PROVIDER_EGRESS_EXCEPTIONS'
_PREFLIGHT = ContextVar('provider_call_preflight', default=None)


@contextmanager
def before_call(check):
    token = _PREFLIGHT.set(check)
    try:
        yield
    finally:
        _PREFLIGHT.reset(token)


class EgressDenied(ValueError):
    pass


def parse_url(value):
    try:
        raw = str(value)
        if any(ord(c) < 33 or ord(c) == 127 for c in raw) or '\\' in raw:
            raise ValueError()
        parsed = urlsplit(raw)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or
                parsed.username is not None or parsed.password is not None or parsed.fragment):
            raise ValueError()
        host = parsed.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        if '%' in host or '*' in host:
            raise ValueError()
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
        return parsed.scheme, host, port
    except (ValueError, UnicodeError):
        raise EgressDenied('模型地址无效：仅接受无内嵌凭证的 HTTP(S) 地址') from None


def _exceptions():
    try:
        values = json.loads(os.environ.get(EXCEPTIONS_ENV, '[]'))
        if not isinstance(values, list) or len(values) > 100:
            raise ValueError()
        result = set()
        for item in values:
            if not isinstance(item, dict) or set(item) != {'scheme', 'host', 'ip', 'port'}:
                raise ValueError()
            host = item['host']
            if not isinstance(host, str) or any(c in host for c in '/@*?#\\%'):
                raise ValueError()
            port = item['port']
            if type(port) is not int:
                raise ValueError()
            address = str(ipaddress.ip_address(item['ip']))
            bracketed = f'[{host}]' if ':' in host else host
            origin = parse_url(f"{item['scheme']}://{bracketed}:{port}")
            result.add((*origin, address))
        return result
    except (ValueError, TypeError, KeyError):
        raise EgressDenied('部署出站例外配置无效；必须指定精确 scheme/host/IP/port') from None


def _public(address):
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped or ip.sixtofour or ip.teredo:
            return False
    return ip.is_global and not (ip.is_multicast or ip.is_unspecified or ip.is_reserved)


def validate_url(value, *, resolve=False):
    origin = parse_url(value)
    scheme, host, port = origin
    exceptions = _exceptions()
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        if not resolve:
            # Syntax-only saves never claim connectivity/authentication success.
            return origin, []
        try:
            addresses = list(dict.fromkeys(
                str(ipaddress.ip_address(item[4][0]))
                for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
            ))
        except (OSError, ValueError):
            raise EgressDenied('模型地址无法安全解析，调用已阻止') from None
    if not addresses or any(not _public(ip) and (*origin, ip) not in exceptions for ip in addresses):
        raise EgressDenied(f'模型出站已拒绝：目标不是公网地址，且无精确部署例外（域名：{host}）')
    return origin, addresses


class GuardedTransport(httpx.BaseTransport):
    def __init__(self, *, origin=None, transport=None):
        self.origin = parse_url(origin) if origin else None
        self._test_transport = transport
        self._transports = {}
        self._lock = threading.Lock()

    def handle_request(self, request):
        if scrub(str(request.url)) != str(request.url):
            raise EgressDenied('模型地址包含凭证，出站已阻止')
        check = _PREFLIGHT.get()
        if check is not None and self.origin is not None:
            check()
        origin, addresses = validate_url(str(request.url), resolve=True)
        # All requests (including redirects) made by a credentialed provider
        # client stay on its original origin. Media downloads use a separate,
        # credential-free client and may follow public redirects.
        if self.origin is not None and origin != self.origin:
            raise EgressDenied('模型认证请求不得跳转到其他来源')
        if self.origin is None and any(
            key.lower() in {'authorization', 'proxy-authorization', 'cookie', 'x-api-key', 'x-api-access-key'}
            for key in request.headers
        ):
            raise EgressDenied('携带凭证的模型请求必须绑定来源')
        headers = request.headers.copy()
        headers['Host'] = request.url.netloc.decode('ascii')
        pinned = httpx.Request(
            request.method, request.url.copy_with(host=addresses[0]), headers=headers,
            stream=request.stream, extensions={**request.extensions, 'sni_hostname': origin[1]},
        )
        # Pin the actual socket target, not only a preflight DNS check. Isolate
        # pools by original origin to prevent TLS connections shared by two
        # virtual hosts on one address from being reused with the wrong SNI.
        with self._lock:
            inner = self._test_transport
            if inner is None:
                inner = self._transports.get(origin)
                if inner is None:
                    inner = self._transports[origin] = httpx.HTTPTransport(trust_env=False)
        try:
            return inner.handle_request(pinned)
        except httpx.HTTPError:
            raise httpx.TransportError('模型网络调用失败，请核对服务状态；凭证及请求详情不写入错误') from None

    def close(self):
        if self._test_transport is not None:
            self._test_transport.close()
        for inner in self._transports.values():
            inner.close()


def client(*, origin=None, **kwargs):
    # Environment proxies could bypass the checked destination. No silent
    # proxy/transport override is accepted at this production boundary.
    kwargs.pop('trust_env', None)
    if 'transport' in kwargs or 'mounts' in kwargs or 'proxy' in kwargs:
        raise ValueError('受控模型客户端不接受出站传输覆盖')
    return httpx.Client(transport=GuardedTransport(origin=origin), trust_env=False, **kwargs)
