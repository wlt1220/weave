from weave import cli
from weave.cell import canonical_source, resolve_cell
from weave.cone import apply_ops
from weave.fold import Fold
from weave.store import Store


def _intent(goal, agent, node, src, rationale, verified):
    return cli._mk_intent(goal, agent, node, src, rationale, verified)


def test_build_cells_and_materialize():
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    a2 = _intent("b", "agent-2", "refund", cli.REFUND_AUDIT, "r2", True)
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1, a2])
    assert set(fold.cells) == {
        "payments.py:log", "payments.py:charge", "payments.py:refund"}
    assert fold.cells["payments.py:charge"].intent_ids == [a1.id]
    assert fold.cells["payments.py:refund"].intent_ids == [a2.id]
    assert fold.cells["payments.py:log"].intent_ids == []  # untouched
    assert fold.log_pos == 2
    mat = fold.materialize()
    expect = apply_ops(apply_ops(cli.DEMO_SOURCE, a1.operations),
                       a2.operations)
    assert mat["payments.py"] == expect


def test_advance_only_dirties_touched_cells():
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    a2 = _intent("b", "agent-2", "refund", cli.REFUND_AUDIT, "r2", True)
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1])
    before = {k: c.cell_id for k, c in fold.cells.items()}
    dirty = fold.advance([a2])
    assert dirty == ["payments.py:refund"]
    for k in ("payments.py:log", "payments.py:charge"):
        assert fold.cells[k].cell_id == before[k]  # byte-identical
    assert fold.cells["payments.py:refund"].intent_ids == [a2.id]
    assert fold.log_pos == 2
    # incremental == full rebuild
    full = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1, a2])
    assert fold.materialize() == full.materialize()
    for k in fold.cells:
        assert fold.cells[k].cell_id == full.cells[k].cell_id


def test_advance_same_node_appends_slice():
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    a3 = _intent("c", "agent-3", "charge", cli.CHARGE_FEE, "r3", True)
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1])
    dirty = fold.advance([a3])
    assert dirty == ["payments.py:charge"]
    cell = fold.cells["payments.py:charge"]
    assert cell.intent_ids == [a1.id, a3.id]
    assert cell.source == canonical_source(cli.CHARGE_FEE)


def test_why_and_fold_agree_on_cell_id():
    """The cross-module invariant: one cell, one id, everywhere."""
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1])
    mat = fold.materialize()
    why_cell = resolve_cell("payments.py", "charge", mat, [a1])
    fold_cell = fold.cells["payments.py:charge"]
    assert why_cell is not None
    assert why_cell.cell_id == fold_cell.cell_id
    assert why_cell.state_hash == fold_cell.state_hash
    assert why_cell.intent_ids == fold_cell.intent_ids


def test_fold_persistence_roundtrip(tmp_path):
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    store = Store.init(str(tmp_path / ".weave"))
    assert store.load_fold() is None
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1])
    store.save_fold(fold)
    f2 = store.load_fold()
    assert f2 is not None
    assert f2.log_pos == fold.log_pos
    assert set(f2.cells) == set(fold.cells)
    for k in fold.cells:
        assert f2.cells[k].cell_id == fold.cells[k].cell_id
        assert f2.cells[k].source == fold.cells[k].source


def test_materialize_brand_new_node_appended():
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    new_src = 'def metrics():\n    return {"ok": True}\n'
    a9 = _intent("n", "agent-9", "metrics", new_src, "r9", True)
    fold = Fold.build({"payments.py": cli.DEMO_SOURCE}, [a1, a9])
    mat = fold.materialize()["payments.py"]
    import ast as _ast
    _ast.parse(mat)  # still compiles
    assert "def metrics():" in mat
    assert fold.cells["payments.py:metrics"].intent_ids == [a9.id]
