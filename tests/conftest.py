import os
import ipaddress
import socket
import tempfile
import pytest
from pathlib import Path
from tests.postgres_test_db import create_isolated_database, drop_isolated_database

# Installed before collection imports backend.store, including single-file runs.
os.environ['MVC_DATA_DIR']=tempfile.mkdtemp(prefix='mvc-tests-')
_ROOT = Path(__file__).resolve().parents[1]
_TEST_DATABASE_NAME, _TEST_DATABASE_URL = create_isolated_database(_ROOT)


@pytest.fixture(scope='session', autouse=True)
def synthetic_platform_master():
    # One explicitly generated test-only key for this isolated database. Tests
    # still override/delete it to exercise fail-closed deployment behavior.
    from tests.platform_model_helpers import MASTER
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('OVC_PROVIDER_MASTER_KEY', MASTER)
        patch.setenv('OVC_PROVIDER_MASTER_KEY_ID', 'p4-test')
        yield


def pytest_sessionfinish(session, exitstatus):
    from backend.database import engine
    engine().dispose()
    drop_isolated_database(_TEST_DATABASE_NAME, _TEST_DATABASE_URL)


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
