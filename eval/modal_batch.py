"""eval/modal_batch.py — batch scenario runs on Modal (Stage 2, STEP 4).

DEFERRED: written and offline-tested, never live-run — this machine has
no Modal authentication, so no cloud execution has happened yet. Setup
and the deferral are stated in the README ("Batch evaluation on Modal").

Shape mirrors the local split: one Modal container records one scenario
(record_scenario over the scenario dict, clients built from the Modal
secret), the local entrypoint gathers the records into a run folder, and
score_run writes REPORT.md next to them — so a Modal run folder scores
identically to a local one.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import modal

APP_NAME = "refi-batch"
# One Modal secret holding both keys the recording chain needs:
#   modal secret create model-api-key \
#     MODEL_API_KEY=$MODEL_API_KEY BASETEN_API_KEY=$BASETEN_API_KEY
# The judge runs inside record_scenario, so its key is required too.
SECRET_NAME = "model-api-key"

REPO_ROOT = Path(__file__).resolve().parent.parent

# Worktree weight that must never ride to Modal: the environment, VCS
# history, recorded runs (gitignored, and the point of the batch is to
# produce them remotely), bytecode caches, and the agent plans folder.
# Modal calls the predicate with repo-relative paths; True means exclude.
# Directories prune before descent, so excluding a dir skips its subtree.
_MOUNT_EXCLUDED_TOP = (".venv", ".git", ".agents")
_MOUNT_EXCLUDED_SUBTREE = ("eval", "runs")


def _ignore_mount(rel: Path) -> bool:
    parts = rel.parts
    if not parts:
        return False
    if parts[0] in _MOUNT_EXCLUDED_TOP:
        return True
    if tuple(parts[:2]) == _MOUNT_EXCLUDED_SUBTREE:
        return True
    return "__pycache__" in parts


app = modal.App(APP_NAME)
image = (
    modal.Image.debian_slim()
    .pip_install("openai==3.35.1", "pydantic==2.14.1")
    .add_local_dir(REPO_ROOT, remote_path="/refi", ignore=_ignore_mount)
)


def _require_key(env: Any) -> tuple[str, str]:
    """Fail loud with the setup command when a key is missing.

    Runs first inside the container so a missing secret fails before any
    Meta call is spent — and gives a fresh clone the fix, not a 401.
    The Baseten key is checked here too: the judge runs inside the
    recording chain, so a run without it would burn calls then template.
    """
    meta = env.get("MODEL_API_KEY", "")
    baseten = env.get("BASETEN_API_KEY", "")
    if not meta or not baseten:
        raise RuntimeError(
            "Modal secret "
            f"{SECRET_NAME!r} is missing a key; create it with: "
            f"modal secret create {SECRET_NAME} "
            "MODEL_API_KEY=$MODEL_API_KEY BASETEN_API_KEY=$BASETEN_API_KEY"
        )
    return meta, baseten


@app.function(image=image,
              secrets=[modal.Secret.from_name(SECRET_NAME)],
              timeout=1800)
def record_remote(scenario: dict) -> dict:
    """Record one scenario in a Modal container. Returns the record dict."""
    sys.path.insert(0, "/refi")
    _require_key(os.environ)
    from llm import get_meta_client
    from eval.record import record_scenario

    with tempfile.TemporaryDirectory() as tmp:
        record, _ = record_scenario(scenario, get_meta_client(), tmp)
        return json.loads(Path(tmp, f"{scenario['id']}.json").read_text())


def _pending(data_dir: str | Path, run_dir: str | Path,
             overwrite: bool = False) -> tuple[list[dict], list[str]]:
    """Scenarios still needing a record, plus ids skipped as recorded.

    Resumable like record_all: a rerun only records what is missing.
    """
    from eval.record import load_scenarios

    run_path = Path(run_dir)
    to_record, skipped = [], []
    for scenario in load_scenarios(data_dir):
        target = run_path / f"{scenario['id']}.json"
        if target.exists() and not overwrite:
            skipped.append(scenario["id"])
        else:
            to_record.append(scenario)
    return to_record, skipped


@app.local_entrypoint()
def main(data: str, run_dir: str,
         limit: int | None = None, overwrite: bool = False) -> None:
    """Fan scenarios out to Modal, gather records, score offline.

    modal run eval/modal_batch.py --data <dir> --run-dir <dir>
        [--limit N] [--overwrite]

    No --cap: the call budget is per-scenario and unknown before running,
    so --limit bounds the spend instead.
    """
    from eval.score import score_run

    run_path = Path(run_dir)
    run_path.mkdir(parents=True, exist_ok=True)
    to_record, skipped = _pending(data, run_path, overwrite)
    if limit is not None:
        to_record = to_record[:limit]
    for record in record_remote.map(to_record):
        Path(run_path, f"{record['id']}.json").write_text(
            json.dumps(record, indent=2))
    print(json.dumps({"recorded": [s["id"] for s in to_record],
                      "skipped": skipped}, indent=2))
    score_run(data, run_path)
    print(f"REPORT.md written to {run_path}")
