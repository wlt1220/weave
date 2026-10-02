import pytest

from weave import cli
from weave.cell import canonical_source, node_source
from weave.fold import Fold
from weave.rewind import compute_affected_nodes, rewind_fold


REFUND_V2 = '''\
def refund(tx_id, audit=True):
    log(f"REFUNDING {tx_id}")
    return {"status": "refunded", "tx": tx_id, "v": 2}
'''


def _intent(goal, agent, node, src, rationale, verified):
    return cli._mk_intent(goal, agent, node, src, rationale, verified)


def _scenario():
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    a2 = _intent("b", "agent-2", "refund", cli.REFUND_AUDIT, "r2", True)
    bad = _intent("x", "agent-4", "log", cli.LOG_STRUCTURED, "rx", True)
    a4 = _intent("c", "agent-5", "refund", REFUND_V2, "r4", True)
    return a1, a2, bad, a4


def test_affected_cone_is_bad_plus_dependents():
    a1, a2, bad, a4 = _scenario()
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1, a2, bad, a4])
    affected = compute_affected_nodes(
        fold.materialize(), {"payments.py:log"})
    # log itself + its transitive callers; nothing else
    assert affected == {
        "payments.py:log", "payments.py:charge", "payments.py:refund"}


def test_rewind_excises_bad_and_restores_cells():
    a1, a2, bad, a4 = _scenario()
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1, a2, bad, a4])
    charge_before = fold.cells["payments.py:charge"].cell_id

    report = rewind_fold(fold, [a1, a2, bad, a4], bad.id)

    assert report.bad_id == bad.id
    assert set(report.affected) == {
        "payments.py:log", "payments.py:charge", "payments.py:refund"}
    assert bad.id in fold.reverted

    # log cell restored to genesis: empty slice, base source
    log_cell = fold.cells["payments.py:log"]
    assert log_cell.intent_ids == []
    assert log_cell.source == canonical_source(
        node_source(cli.DEMO_SOURCE, "log"))

    # charge never touched by bad: byte-identical
    assert fold.cells["payments.py:charge"].cell_id == charge_before

    # downstream: a4 was built on the polluted log
    assert [i.id for i in report.downstream] == [a4.id]
    assert report.untouched_cells == 0  # all 3 cells in the cone here

    # materialized file has no trace of the bad log
    mat = fold.materialize()["payments.py"]
    assert "str(msg).upper()" not in mat
    assert "REFUNDING" in mat  # a4's good work survives


def test_rewind_equivalent_to_clean_fold():
    """The core invariant: rewind(bad) == fold(log minus bad), cell for cell."""
    a1, a2, bad, a4 = _scenario()
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1, a2, bad, a4])
    rewind_fold(fold, [a1, a2, bad, a4], bad.id)

    clean = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1, a2, a4])
    assert set(fold.cells) == set(clean.cells)
    for k in clean.cells:
        assert fold.cells[k].cell_id == clean.cells[k].cell_id, k
        assert fold.cells[k].intent_ids == clean.cells[k].intent_ids, k
    assert fold.materialize() == clean.materialize()


def test_rewind_twice_raises_and_unknown_raises():
    a1, a2, bad, a4 = _scenario()
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1, a2, bad, a4])
    rewind_fold(fold, [a1, a2, bad, a4], bad.id)
    with pytest.raises(ValueError):
        rewind_fold(fold, [a1, a2, bad, a4], bad.id)
    with pytest.raises(KeyError):
        rewind_fold(fold, [a1, a2, bad, a4], "0" * 64)


def test_reverted_intent_skipped_on_advance():
    a1, a2, bad, a4 = _scenario()
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1, a2, bad])
    rewind_fold(fold, [a1, a2, bad], bad.id)
    assert fold.reverted == {bad.id}
    # new intent after rewind folds normally; reverted stays excised
    dirty = fold.advance([a4])
    assert dirty == ["payments.py:refund"]
    assert fold.log_pos == 4
    assert "str(msg).upper()" not in fold.materialize()["payments.py"]
    # persistence keeps the reverted set
    d = fold.to_dict()
    assert d["reverted"] == [bad.id]
    f2 = Fold.from_dict(d)
    assert f2.reverted == {bad.id}


def test_rewind_last_intent_no_downstream():
    a1, a2, bad, _ = _scenario()
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1, a2, bad])
    report = rewind_fold(fold, [a1, a2, bad], bad.id)
    assert report.downstream == []
    assert [r["node_id"] for r in report.restored] == sorted(report.affected)
