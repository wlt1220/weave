"""Git-bridge mirror tests: real git against a local bare repo.

The mirror logic is transport-agnostic (the token rides an http header that
local paths simply ignore), so a file:// bare repo exercises the exact same
clone/write/commit/push path the Artifacts remote will see.
"""
import json
import os
import subprocess

import pytest

from weave.mirror import mirror_intents

pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)


def _bare_repo(tmp_path):
    bare = str(tmp_path / "remote.git")
    subprocess.run(["git", "init", "--bare", "-b", "main", bare],
                   check=True, capture_output=True)
    return bare


def _clone_read(bare, path):
    work = os.path.join(os.path.dirname(bare), "readback")
    subprocess.run(["git", "clone", bare, work], check=True,
                   capture_output=True)
    with open(os.path.join(work, path)) as f:
        return json.load(f)


def test_mirror_push_and_readback(tmp_path):
    bare = _bare_repo(tmp_path)
    intents = [{"id": "a" * 64, "goal": "first"},
               {"id": "b" * 64, "goal": "second"}]
    s = mirror_intents(bare, "dummy-token", intents)
    assert s["wrote"] == 2 and s["committed"] and s["pushed"]

    doc = _clone_read(bare, f"intents/{'a' * 64}.json")
    assert doc["goal"] == "first"


def test_mirror_idempotent(tmp_path):
    bare = _bare_repo(tmp_path)
    intents = [{"id": "a" * 64, "goal": "first"}]
    mirror_intents(bare, "dummy-token", intents)
    s2 = mirror_intents(bare, "dummy-token", intents)
    assert s2["wrote"] == 0 and not s2["committed"] and not s2["pushed"]


def test_mirror_incremental_new_intent(tmp_path):
    bare = _bare_repo(tmp_path)
    mirror_intents(bare, "dummy-token", [{"id": "a" * 64, "goal": "first"}])
    s = mirror_intents(bare, "dummy-token",
                       [{"id": "a" * 64, "goal": "first"},
                        {"id": "b" * 64, "goal": "second"}])
    assert s["wrote"] == 1 and s["pushed"]
    doc = _clone_read(bare, f"intents/{'b' * 64}.json")
    assert doc["goal"] == "second"


def test_mirror_rejects_nonzero_git(tmp_path):
    bare = _bare_repo(tmp_path)
    with pytest.raises(RuntimeError, match="git"):
        # not a repo path at all: remote add succeeds, fetch/push fail
        mirror_intents(os.path.join(str(tmp_path), "nope.git"),
                       "dummy-token", [{"id": "a" * 64}])
