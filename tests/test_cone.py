from weave.cone import FuncGraph, apply_ops, find_conflict
from weave import cli

SRC = cli.DEMO_SOURCE


def test_call_graph():
    g = FuncGraph(SRC)
    assert g.nodes["charge"]["calls"] == {"log"}
    assert g.nodes["refund"]["calls"] == {"log"}
    assert g.nodes["log"]["calls"] == set()


def test_depends_on():
    g = FuncGraph(SRC)
    assert g.depends_on("charge", "log")
    assert not g.depends_on("charge", "refund")
    assert not g.depends_on("log", "charge")


def test_disjoint_nodes_no_conflict():
    g = FuncGraph(SRC)
    hit, _ = find_conflict(g, ["charge"], ["refund"])
    assert not hit  # share a dependency, but neither affects the other


def test_same_node_conflicts():
    g = FuncGraph(SRC)
    hit, (a, b, why) = find_conflict(g, ["charge"], ["charge"])
    assert hit and "same node" in why


def test_dependency_conflicts():
    g = FuncGraph(SRC)
    hit, (a, b, why) = find_conflict(g, ["log"], ["refund"])
    assert hit and "depends on" in why


def test_apply_ops_disjoint():
    ops = [
        {"op": "replace_function", "file": "p.py", "node": "charge",
         "new_source": cli.CHARGE_IDEMPOTENT},
        {"op": "replace_function", "file": "p.py", "node": "refund",
         "new_source": cli.REFUND_AUDIT},
    ]
    out = apply_ops(SRC, ops)
    import ast
    ast.parse(out)  # still valid python
    assert "idem_key" in out and "audit" in out
    assert "def log(msg):" in out  # untouched
