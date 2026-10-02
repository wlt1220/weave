"""Client for the Weave coordination plane (Cloudflare Workers).

Bridges the local intent prototype and the Workers coordinator:
computes call graphs with the local AST analyzer and submits
intents (with graphs) for continuous integration.
"""
from __future__ import annotations

import json
import urllib.request

from .cone import FuncGraph


class WeaveRemote:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)

    def _get(self, path: str) -> dict:
        with urllib.request.urlopen(self.base + path, timeout=30) as r:
            return json.load(r)

    def ensure_stream(self, stream: str) -> dict:
        return self._post("/v1/streams", {"stream": stream})

    def submit(self, stream: str, intent, sources: dict[str, str]) -> dict:
        """Submit a local Intent; call graphs are computed from sources."""
        graph = {}
        for fname, src in sources.items():
            fg = FuncGraph(src)
            graph[fname] = {n: {"calls": sorted(info["calls"])}
                            for n, info in fg.nodes.items()}
        body = {
            "goal": intent.goal,
            "author": {"agent_id": intent.author.agent_id,
                       "model": intent.author.model},
            "plan": intent.plan,
            "operations": intent.operations,
            "verification": {"tests": intent.verification.tests,
                             "passed": intent.verification.passed,
                             "sandbox": intent.verification.sandbox}
            if intent.verification else None,
            "rationale": intent.rationale,
            "parents": intent.parents,
            "graph": graph,
        }
        return self._post(f"/v1/streams/{stream}/intents", body)

    def state(self, stream: str) -> dict:
        return self._get(f"/v1/streams/{stream}")

    def get_intent(self, stream: str, intent_id: str) -> dict:
        return self._get(f"/v1/streams/{stream}/intents/{intent_id}")

    def git_access(self, stream: str) -> dict:
        """Minted git remote + short-lived token (the git bridge)."""
        return self._get(f"/v1/streams/{stream}/git")

    def verify(self, stream: str, intent_id: str, passed: bool = True) -> dict:
        return self._post(f"/v1/streams/{stream}/intents/{intent_id}/verify",
                          {"tests": ["t"], "passed": passed, "sandbox": "sbx"})

    def retry(self, stream: str) -> dict:
        return self._post(f"/v1/streams/{stream}/retry", {})
