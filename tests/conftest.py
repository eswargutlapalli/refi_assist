"""No-network guard: the whole suite is mocked, so any test that opens a
network socket fails instead of spending credit or hanging on the API."""

import socket
import types

import pytest


def _blocked(*args, **kwargs):
    raise RuntimeError("network socket blocked in tests — pass a fake client")


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


class _PassCompletions:
    """Default claim judge: passes every accepted draft with no spend.

    The ladder always judges (decision 26), so the suite needs a judge
    that never touches the network. Failure paths pass their own
    judge_client; this default only keeps narration tests offline.
    """

    def create(self, **kwargs):
        message = types.SimpleNamespace(
            content='{"passed": true, "problems": []}', tool_calls=None)
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=message)],
            usage=None,
            model="meta-models/muse-spark-open-1026",
        )


@pytest.fixture(autouse=True)
def _passing_judge(monkeypatch):
    import judge as judge_mod

    fake = types.SimpleNamespace(
        chat=types.SimpleNamespace(completions=_PassCompletions()))
    monkeypatch.setattr(judge_mod, "get_baseten_client", lambda: fake)
