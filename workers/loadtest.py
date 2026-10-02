#!/usr/bin/env python3
"""Concurrency proof: N agents submit intents concurrently to the coordinator.

Each agent works on random functions of a synthetic service. Disjoint cones
fold lock-free; overlaps open negotiations. Run against local wrangler dev:
    python3 loadtest.py --agents 20 --intents 5
"""
import argparse
import json
import random
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

GRAPH = {
    "svc.py": {
        "log": {"calls": []},
        "metrics": {"calls": []},
        "auth": {"calls": ["log"]},
        "db": {"calls": ["log"]},
        **{f"f{i}": {"calls": ["db", "log"]} for i in range(1, 41)},
        "report": {"calls": ["f1", "f2"]},
    }
}
NODES = list(GRAPH["svc.py"])
FEATURES = [f"f{i}" for i in range(1, 41)]


def post(base, path, body):
    req = urllib.request.Request(
        base + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def get(base, path):
    with urllib.request.urlopen(base + path, timeout=30) as r:
        return json.load(r)


FEATURES = [f"f{i}" for i in range(1, 17)]
SHARED = ["db", "log", "auth"]


def agent_job(args):
    base, stream, agent_id, n, seed, p_shared = args
    rnd = random.Random(seed)
    # each agent owns a dedicated pair of features, like a real service owner;
    # 15% of writes touch shared infra (where contention is genuine)
    shard = [f"f{2 * (seed % 100) + 1}", f"f{2 * (seed % 100) + 2}"]
    results = []
    try:
        state = get(base, f"/v1/streams/{stream}")
        parent = [state["trunk"]["head"]] if state["trunk"]["head"] else []
    except Exception:
        parent = []
    for i in range(n):
        node = rnd.choice(SHARED) if rnd.random() < p_shared else rnd.choice(shard)
        verified = rnd.random() < 0.7
        body = {
            "goal": f"{agent_id}: tune {node} #{i}",
            "author": {"agent_id": agent_id, "model": "synthetic"},
            "operations": [{"op": "replace", "file": "svc.py", "node": node}],
            "verification": {"tests": ["t"], "passed": verified, "sandbox": "sbx"},
            "rationale": f"agent {agent_id} optimizing {node}",
            "parents": parent,
            "graph": GRAPH,
        }
        try:
            r = post(base, f"/v1/streams/{stream}/intents", body)
            results.append(r)
            if r.get("id"):
                parent = [r["id"]]  # chain: next intent sees this one
        except Exception as e:
            results.append({"error": str(e)})
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8787")
    ap.add_argument("--agents", type=int, default=20)
    ap.add_argument("--intents", type=int, default=5)
    ap.add_argument("--stream", default="loadtest")
    ap.add_argument("--shared", type=float, default=0.15,
                    help="probability a write touches shared infra")
    a = ap.parse_args()

    post(a.base, "/v1/streams", {"stream": a.stream})
    total = a.agents * a.intents
    print(f"firing {total} intents from {a.agents} concurrent agents…")
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=a.agents) as ex:
        allres = list(ex.map(agent_job, [
            (a.base, a.stream, f"agent-{i}", a.intents, 1000 + i, a.shared)
            for i in range(a.agents)
        ]))
    dt = time.perf_counter() - t0

    flat = [r for rs in allres for r in rs]
    ok = [r for r in flat if r.get("ok")]
    folded = [r for r in ok if r.get("integrated")]
    nego = [r for r in ok if r.get("negotiation")]
    errs = [r for r in flat if r.get("error")]

    state = get(a.base, f"/v1/streams/{a.stream}")
    print(f"\n{total} intents in {dt:.1f}s → {total/dt:.0f} intents/s")
    print(f"folded lock-free : {len(folded)}")
    print(f"negotiations     : {len(nego)}")
    print(f"errors           : {len(errs)}")
    print(f"trunk folds      : {state['trunk']['folds']}")
    print(f"pending          : {len(state['pending'])}")
    outcomes = {}
    for n in state["negotiations"]:
        outcomes[n["outcome"]] = outcomes.get(n["outcome"], 0) + 1
    print(f"negotiation outcomes: {outcomes}")
    # full lifecycle: verify the unverified, then rebase-retry everything
    state = get(a.base, f"/v1/streams/{a.stream}")
    verified_now = 0
    for pid in state["pending"]:
        it = get(a.base, f"/v1/streams/{a.stream}/intents/{pid}")
        if not (it.get("verification") or {}).get("passed"):
            post(a.base, f"/v1/streams/{a.stream}/intents/{pid}/verify",
                 {"tests": ["t"], "passed": True, "sandbox": "sbx-late"})
            verified_now += 1
    print(f"late verifications : {verified_now}")
    retry = post(a.base, f"/v1/streams/{a.stream}/retry", {})
    state = get(a.base, f"/v1/streams/{a.stream}")
    print(f"after rebase-retry : +{retry['retried']} folded, "
          f"{retry['still_pending']} still pending, "
          f"trunk folds={state['trunk']['folds']}")
    if errs:
        print("sample error:", errs[0]["error"][:200])
        sys.exit(1)


if __name__ == "__main__":
    main()
