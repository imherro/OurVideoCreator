"""Fake sockets underneath the real DNS/origin/redirect guard, never around it."""
import ipaddress
import socket
import httpx
from backend import provider_egress

_GUARD_INIT = provider_egress.GuardedTransport.__init__
_RESOLVE = socket.getaddrinfo


def public_test_dns(monkeypatch):
    def resolve(host, port, *args, **kwargs):
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if host != 'localhost':
                return [(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',port))]
        return _RESOLVE(host,port,*args,**kwargs)
    monkeypatch.setattr(provider_egress.socket,'getaddrinfo',resolve)


def mock_egress(monkeypatch, handler):
    public_test_dns(monkeypatch)
    def protocol(request):
        # Guard already resolved/pinned/checked this destination. Restore the
        # Host only for protocol assertions inside MockTransport; no socket opens.
        origin=httpx.URL(str(request.url)).copy_with(host=request.headers['Host'].split(':')[0])
        return handler(httpx.Request(request.method,origin,headers=request.headers,
                                     content=request.read(),extensions=request.extensions))
    def initialize(self, *, origin=None, transport=None):
        _GUARD_INIT(self,origin=origin,transport=httpx.MockTransport(protocol))
    monkeypatch.setattr(provider_egress.GuardedTransport,'__init__',initialize)
