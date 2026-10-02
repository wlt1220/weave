import json

from weave.intent import Author, Intent, Verification
from weave.store import Store


def test_intent_is_content_addressed():
    a = Intent(goal="fix race", author=Author(agent_id="a1")).seal()
    b = Intent(goal="fix race", author=Author(agent_id="a1"),
               created_at=a.created_at).seal()
    assert a.id == b.id and len(a.id) == 64


def test_same_goal_different_author_different_id():
    a = Intent(goal="fix race", author=Author(agent_id="a1")).seal()
    b = Intent(goal="fix race", author=Author(agent_id="a2"),
               created_at=a.created_at).seal()
    assert a.id != b.id


def test_store_roundtrip_and_log(tmp_path):
    s = Store.init(str(tmp_path / ".weave"))
    it = Intent(goal="add cache", author=Author(agent_id="a1"),
                verification=Verification(passed=True, sandbox="sbx-1")).seal()
    iid = s.put(it)
    assert s.get(iid).goal == "add cache"
    assert s.get(iid).verified
    assert s.head() == iid
    assert s.log()[0]["goal"] == "add cache"


def test_unverified_intent_flagged(tmp_path):
    s = Store.init(str(tmp_path / ".weave"))
    it = Intent(goal="wip", author=Author(agent_id="a1")).seal()
    s.put(it)
    assert not s.get(it.id).verified
