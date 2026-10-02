import hashlib

from weave import cli
from weave.cell import (Cell, compute_cell_id, find_node, node_id,
                        resolve_cell)
from weave.cone import apply_ops


def _intent(goal, agent, node, src, rationale, verified):
    return cli._mk_intent(goal, agent, node, src, rationale, verified)


def test_cell_id_is_content_addressed():
    ids = ["a" * 64, "b" * 64]
    c1 = compute_cell_id("payments.py", "charge", ids, "state1")
    c2 = compute_cell_id("payments.py", "charge", ids, "state1")
    assert c1 == c2 and len(c1) == 64
    # any component change -> different cell
    assert compute_cell_id("payments.py", "charge", ids, "state2") != c1
    assert compute_cell_id("payments.py", "charge", ["c" * 64], "state1") != c1
    assert compute_cell_id("payments.py", "refund", ids, "state1") != c1


def test_find_node_innermost():
    src = cli.DEMO_SOURCE
    assert find_node(src, 1) == "log"
    assert find_node(src, 5) == "charge"
    assert find_node(src, 6) == "charge"   # inside body
    assert find_node(src, 10) == "refund"
    assert find_node(src, 4) is None       # blank line between defs


def test_resolve_cell_slice_and_state():
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    a2 = _intent("b", "agent-2", "refund", cli.REFUND_AUDIT, "r2", True)
    merged = apply_ops(apply_ops(cli.DEMO_SOURCE, a1.operations),
                       a2.operations)
    cell = resolve_cell("payments.py", 6, {"payments.py": merged}, [a1, a2])
    assert isinstance(cell, Cell)
    assert cell.nid == "payments.py:charge"
    assert cell.intent_ids == [a1.id]              # slice: only intents that
    assert [i.id for i in cell.intents] == [a1.id]  # touched THIS node
    assert cell.span == (5, 7)
    from weave.cell import node_source as _ns
    expect_state = hashlib.sha256(
        _ns(merged, "charge").encode()).hexdigest()
    assert cell.state_hash == expect_state
    assert cell.cell_id == compute_cell_id(
        "payments.py", "charge", [a1.id], expect_state)


def test_resolve_cell_untouched_node_still_a_cell():
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    cell = resolve_cell("payments.py", 1, {"payments.py": cli.DEMO_SOURCE},
                        [a1])
    assert cell is not None
    assert cell.nid == "payments.py:log"
    assert cell.intent_ids == []          # nothing touched it: empty slice
    assert cell.intents == []


def test_resolve_cell_missing():
    a1 = _intent("a", "agent-1", "charge", cli.CHARGE_IDEMPOTENT, "r1", True)
    assert resolve_cell("nope.py", 1, {"payments.py": cli.DEMO_SOURCE},
                        [a1]) is None
    assert resolve_cell("payments.py", 4, {"payments.py": cli.DEMO_SOURCE},
                        [a1]) is None    # blank line: no node


def test_node_id_format():
    assert node_id("payments.py", "charge") == "payments.py:charge"
