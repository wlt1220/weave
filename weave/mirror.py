"""Git-bridge mirror: push intents/<id>.json to the stream's Artifacts repo.

The Worker never touches git — it only mints tokens via the Artifacts
binding. Any git client holding a token from GET /v1/streams/:stream/git can
mirror: init, fetch existing history if any, write one JSON file per intent,
commit, push. Intent filenames are content hashes, so mirrors never conflict.

The token travels in an `http.extraHeader` Authorization header (base64),
never in the remote URL and never in error messages.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile


def _run_git(cwd: str, argv: list[str], label: str) -> str:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    p = subprocess.run(["git", *argv], cwd=cwd, env=env,
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            f"git {label} failed: {p.stderr.strip()[:200]}")
    return p.stdout.strip()


def _auth_args(token: str) -> list[str]:
    cred = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.extraHeader=Authorization: Basic {cred}"]


def mirror_intents(remote: str, token: str, intents: list[dict],
                   branch: str = "main",
                   workdir: str | None = None) -> dict:
    """Mirror intent dicts (each with an 'id') as intents/<id>.json.

    Returns {"wrote": n_new_files, "committed": bool, "pushed": bool}.
    Idempotent: re-running with the same intents writes nothing.
    """
    auth = _auth_args(token)
    d = workdir or tempfile.mkdtemp(prefix="weave-mirror-")
    _run_git(d, ["init", "-b", branch], "init")
    _run_git(d, ["remote", "add", "origin", remote], "remote add")
    _run_git(d, ["config", "user.name", "weave-mirror"], "config")
    _run_git(d, ["config", "user.email", "weave@local"], "config")
    # pick up existing history when the repo is non-empty
    fetched = subprocess.run(
        ["git", *auth, "fetch", "origin", branch], cwd=d,
        capture_output=True, env=dict(os.environ, GIT_TERMINAL_PROMPT="0"),
    ).returncode == 0
    if fetched:
        _run_git(d, ["checkout", "-B", branch, f"origin/{branch}"], "checkout")

    idir = os.path.join(d, "intents")
    os.makedirs(idir, exist_ok=True)
    wrote = 0
    for it in intents:
        body = json.dumps(it, indent=2, sort_keys=True) + "\n"
        path = os.path.join(idir, f"{it['id']}.json")
        if os.path.exists(path):
            with open(path) as f:
                if f.read() == body:
                    continue
        with open(path, "w") as f:
            f.write(body)
        wrote += 1

    _run_git(d, ["add", "intents"], "add")
    committed = False
    if _run_git(d, ["status", "--porcelain"], "status"):
        _run_git(d, ["commit", "-m", f"weave mirror: {wrote} intent(s)"],
                 "commit")
        committed = True
    pushed = False
    if committed:
        _run_git(d, [*auth, "push", "-u", "origin", branch], "push")
        pushed = True
    return {"dir": d, "wrote": wrote, "committed": committed, "pushed": pushed}
