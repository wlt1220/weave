"""CLI-level tests: real commands against a throwaway repo (tmp_path).

Unit tests cover the engines; these cover the wiring: arg parsing, store
interaction, working-tree IO, and user-facing output of
`why` / `fold` / `rewind` / `log`.
"""
import pytest

from weave import cli
from weave.store import Store


def _intent(goal, agent, node, src, rationale, verified):
    return cli._mk_intent(goal, agent, node, src, rationale, verified)


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "payments.py").write_text(cli.DEMO_SOURCE)
    store = Store.init(str(tmp_path / ".weave"))
    return tmp_path, store


def _put(store, *intents):
    for it in intents:
        store.put(it)
    return intents


# ---------- weave why ----------

def test_why_line_shows_cell(repo, capsys):
    tmp_path, store = repo
    (a1,) = _put(store, _intent("add idem", "agent-1", "charge",
                               cli.CHARGE_IDEMPOTENT, "r1", True))
    cli.main(["why", "payments.py:6"])
    out = capsys.readouterr().out
    assert "cell payments.py:charge" in out
    assert "cell_id" in out
    assert "slice" in out
    assert "add idem" in out
    assert a1.id[:12] in out


def test_why_census_lists_all_cells(repo, capsys):
    tmp_path, store = repo
    _put(store, _intent("a", "agent-1", "charge",
                        cli.CHARGE_IDEMPOTENT, "r1", True))
    cli.main(["why", "payments.py"])
    out = capsys.readouterr().out
    for node in ("log", "charge", "refund"):
        assert f"cell payments.py:{node}" in out


def test_why_missing_file(repo, capsys):
    tmp_path, store = repo
    cli.main(["why", "nope.py:3"])
    assert "no such file" in capsys.readouterr().out


def test_why_line_outside_function(repo, capsys):
    tmp_path, store = repo
    _put(store, _intent("a", "agent-1", "charge",
                        cli.CHARGE_IDEMPOTENT, "r1", True))
    cli.main(["why", "payments.py:4"])
    assert "no cell" in capsys.readouterr().out


# ---------- weave fold ----------

def test_fold_build_then_incremental(repo, capsys):
    tmp_path, store = repo
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    a2 = _intent("b", "agent-2", "refund", cli.REFUND_AUDIT, "r2", True)
    _put(store, a1)
    cli.main(["fold"])
    out = capsys.readouterr().out
    assert "fold built" in out and "3 cells" in out

    _put(store, a2)
    cli.main(["fold"])
    out = capsys.readouterr().out
    assert "1 dirty cell" in out
    assert "payments.py:refund" in out

    src = (tmp_path / "payments.py").read_text()
    assert "idem_key" in src and "audit" in src


def test_fold_up_to_date(repo, capsys):
    tmp_path, store = repo
    _put(store, _intent("a", "agent-1", "charge",
                        cli.CHARGE_IDEMPOTENT, "r1", True))
    cli.main(["fold"])
    capsys.readouterr()
    cli.main(["fold"])
    assert "up to date" in capsys.readouterr().out


# ---------- weave rewind ----------

def test_rewind_e2e(repo, capsys):
    tmp_path, store = repo
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    a2 = _intent("b", "agent-2", "refund", cli.REFUND_AUDIT, "r2", True)
    bad = _intent("x", "agent-4", "log", cli.LOG_STRUCTURED, "rx", True)
    _put(store, a1, a2, bad)
    cli.main(["fold"])
    capsys.readouterr()

    cli.main(["rewind", bad.id[:8]])
    out = capsys.readouterr().out
    assert "rewound" in out and bad.id[:12] in out
    assert "payments.py:log" in out

    # working tree restored, bad change gone
    src = (tmp_path / "payments.py").read_text()
    assert "str(msg).upper()" not in src
    assert "idem_key" in src  # good work survives

    # log marks it reverted; why shows an empty slice
    cli.main(["log"])
    assert f"✗ {bad.id[:12]}" in capsys.readouterr().out
    cli.main(["why", "payments.py:1"])
    out = capsys.readouterr().out
    assert "0 intents" in out


def test_rewind_unknown_prefix(repo, capsys):
    tmp_path, store = repo
    cli.main(["rewind", "deadbeef"])
    assert "no intent matching" in capsys.readouterr().out


# ---------- weave log ----------

def test_log_flags(repo, capsys):
    tmp_path, store = repo
    _put(store,
         _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True),
         _intent("b", "agent-2", "charge", cli.CHARGE_FEE, "r2", False))
    cli.main(["log"])
    out = capsys.readouterr().out
    assert "✓" in out and "○" in out


# ---------- demo smoke ----------

def test_demo_runs(capsys):
    cli.main(["demo"])
    out = capsys.readouterr().out
    for marker in ("Spacetime cell", "Incremental fold", "Rewind: excise"):
        assert marker in out
