"""The Intent: atomic unit of change. Content-addressed, like a git object."""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone


@dataclass
class Author:
    agent_id: str
    model: str = ""
    session: str = ""


@dataclass
class Verification:
    tests: list = field(default_factory=list)
    passed: bool = False
    sandbox: str = ""  # sandbox attestation id


@dataclass
class Intent:
    goal: str
    author: Author
    plan: list = field(default_factory=list)
    operations: list = field(default_factory=list)  # AST-level edit ops (prototype: file ops)
    verification: Verification | None = None
    rationale: str = ""
    parents: list = field(default_factory=list)
    stream: str = "main"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    id: str = ""  # content hash, computed on seal()

    def canonical(self) -> str:
        d = asdict(self)
        d.pop("id", None)
        return json.dumps(d, sort_keys=True, ensure_ascii=False)

    def seal(self) -> "Intent":
        """Compute the content-addressed id. An intent is immutable once sealed."""
        self.id = hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()
        return self

    @property
    def verified(self) -> bool:
        return bool(self.verification and self.verification.passed)

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)

    @staticmethod
    def from_json(s: str) -> "Intent":
        d = json.loads(s)
        d["author"] = Author(**d["author"])
        if d.get("verification"):
            d["verification"] = Verification(**d["verification"])
        return Intent(**d)
