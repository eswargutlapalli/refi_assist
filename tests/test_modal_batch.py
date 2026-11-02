"""Suite for the deferred Modal batch wrapper (eval/modal_batch.py).

Offline only: nothing here authenticates, builds an image, or touches the
network (tests/conftest.py blocks sockets). The wrapper itself is deferred
— no live Modal run has happened — so these tests pin the parts that must
be right when that run eventually happens: the exact secret name the README
documents, the fail-loud key check, and the resumable pending/skip split.
"""

import json

import pytest

batch = pytest.importorskip("eval.modal_batch")


def _scenario(path, sid):
    path.write_text(json.dumps({
        "id": sid,
        "priority": "lowest_total_cost",
        "loan_text": "Balance $10,000.",
        "offer_text": "Rate 5%.",
        "true_loan": {},
        "true_offer": {},
    }))


def test_secret_name_is_the_documented_one():
    assert batch.SECRET_NAME == "model-api-key"


def test_require_key_fails_loud_with_setup_command():
    with pytest.raises(RuntimeError, match="model-api-key"):
        batch._require_key({})
    with pytest.raises(RuntimeError, match="modal secret create"):
        batch._require_key({"MODEL_API_KEY": "x"})


def test_require_key_returns_both_keys():
    env = {"MODEL_API_KEY": "meta", "BASETEN_API_KEY": "baseten"}
    assert batch._require_key(env) == ("meta", "baseten")


def test_ignore_mount_drops_worktree_weight():
    from pathlib import Path
    ignore = batch._ignore_mount
    for raw in (".venv", ".venv/bin/python", ".git", ".git/HEAD",
                "eval/runs", "eval/runs/dev-01/a.json",
                "eval/__pycache__/record.pyc", "__pycache__",
                ".agents", ".agents/plans/x.md"):
        assert ignore(Path(raw)), raw
    for raw in ("engine.py", "eval/record.py", "eval/scenarios/clean.json",
                "eval/runs_doc.md", "samples/README.md"):
        assert not ignore(Path(raw)), raw


def test_pending_skips_recorded_until_overwrite(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    _scenario(data / "a.json", "a")
    _scenario(data / "b.json", "b")
    run = tmp_path / "run"
    run.mkdir()
    (run / "a.json").write_text("{}")
    to_record, skipped = batch._pending(data, run, overwrite=False)
    assert [s["id"] for s in to_record] == ["b"]
    assert skipped == ["a"]
    to_record, skipped = batch._pending(data, run, overwrite=True)
    assert [s["id"] for s in to_record] == ["a", "b"]
    assert skipped == []
