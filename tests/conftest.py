"""Pytest safeguards for the hermetic default test suite."""

from pathlib import Path
import socket

from tests.live import live_tests_enabled


_LIVE_SCRIPT_NAMES = {"functional_test.py", "e2e_test.py"}
_ORIGINAL_SOCKET_CONNECT = socket.socket.connect
_ORIGINAL_SOCKET_CONNECT_EX = socket.socket.connect_ex
_ORIGINAL_CREATE_CONNECTION = socket.create_connection


def pytest_ignore_collect(collection_path, config):
    """Keep standalone live scripts out of the default pytest collection."""
    return (
        not live_tests_enabled()
        and Path(str(collection_path)).name in _LIVE_SCRIPT_NAMES
    )


def _is_network_socket(sock: socket.socket) -> bool:
    return sock.family in (socket.AF_INET, socket.AF_INET6)


def _blocked_connect(sock: socket.socket, address):
    if _is_network_socket(sock):
        raise AssertionError(
            "Outbound network access is disabled for the default test suite; "
            "set PAPER_SEARCH_MCP_RUN_LIVE_TESTS=1 to run live tests."
        )
    return _ORIGINAL_SOCKET_CONNECT(sock, address)


def _blocked_connect_ex(sock: socket.socket, address):
    if _is_network_socket(sock):
        raise AssertionError(
            "Outbound network access is disabled for the default test suite; "
            "set PAPER_SEARCH_MCP_RUN_LIVE_TESTS=1 to run live tests."
        )
    return _ORIGINAL_SOCKET_CONNECT_EX(sock, address)


def _blocked_create_connection(
    address,
    timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
    source_address=None,
):
    raise AssertionError(
        "Outbound network access is disabled for the default test suite; "
        "set PAPER_SEARCH_MCP_RUN_LIVE_TESTS=1 to run live tests."
    )


def pytest_configure(config):
    """Install the guard before test modules and their decorators import."""
    if live_tests_enabled():
        return
    socket.socket.connect = _blocked_connect
    socket.socket.connect_ex = _blocked_connect_ex
    socket.create_connection = _blocked_create_connection


def pytest_unconfigure(config):
    """Restore the process-global socket methods after the pytest session."""
    socket.socket.connect = _ORIGINAL_SOCKET_CONNECT
    socket.socket.connect_ex = _ORIGINAL_SOCKET_CONNECT_EX
    socket.create_connection = _ORIGINAL_CREATE_CONNECTION
