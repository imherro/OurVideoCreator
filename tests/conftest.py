import os
import ipaddress
import socket
import tempfile
import pytest
# Installed before collection imports backend.store, including single-file runs.
os.environ['MVC_DATA_DIR']=tempfile.mkdtemp(prefix='mvc-tests-')


@pytest.fixture(autouse=True)
def block_non_loopback_network(monkeypatch):
    """Tests may use MockTransport or loopback fakes, never commercial APIs."""
    original = socket.socket.connect

    def guarded(instance, address):
        if not isinstance(address, tuple):
            return original(instance, address)
        host = str(address[0]).split('%', 1)[0]
        if host == 'localhost':
            return original(instance, address)
        try:
            if ipaddress.ip_address(host).is_loopback:
                return original(instance, address)
        except ValueError:
            pass
        raise AssertionError(f'test network egress blocked: {host}')

    monkeypatch.setattr(socket.socket, 'connect', guarded)
