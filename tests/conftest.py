"""No-network guard: the whole suite is mocked, so any test that opens a
network socket fails instead of spending credit or hanging on the API."""

import socket

import pytest


def _blocked(*args, **kwargs):
    raise RuntimeError("network socket blocked in tests — pass a fake client")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
