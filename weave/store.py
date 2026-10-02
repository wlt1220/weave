"""Content-addressed object store + the intent log (the source of truth)."""
from __future__ import annotations

import json
import os

from .fold import Fold
from .intent import Intent


class Store:
    """Filesystem-backed store. Layout: <root>/objects/<sha256> and <root>/log (jsonl)."""

    def __init__(self, root: str):
        self.root = root
        self.objdir = os.path.join(root, "objects")
        self.logpath = os.path.join(root, "log")
        self.foldpath = os.path.join(root, "fold.json")

    @classmethod
    def init(cls, root: str) -> "Store":
        s = cls(root)
        os.makedirs(s.objdir, exist_ok=True)
        if not os.path.exists(s.logpath):
            open(s.logpath, "w").close()
        return s

    @classmethod
    def open(cls, root: str) -> "Store":
        s = cls(root)
        if not os.path.isdir(s.objdir):
            raise FileNotFoundError(f"not a weave repo: {root}")
        return s

    def put(self, intent: Intent) -> str:
        if not intent.id:
            intent.seal()
        with open(os.path.join(self.objdir, intent.id), "w") as f:
            f.write(intent.to_json())
        with open(self.logpath, "a") as f:
            f.write(json.dumps({"id": intent.id, "stream": intent.stream,
                                "goal": intent.goal}) + "\n")
        return intent.id

    def get(self, intent_id: str) -> Intent:
        with open(os.path.join(self.objdir, intent_id)) as f:
            return Intent.from_json(f.read())

    def log(self, stream: str | None = None) -> list[dict]:
        out = []
        with open(self.logpath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                e = json.loads(line)
                if stream is None or e["stream"] == stream:
                    out.append(e)
        return out

    def head(self, stream: str = "main") -> str | None:
        entries = self.log(stream)
        return entries[-1]["id"] if entries else None

    def save_fold(self, fold: Fold) -> None:
        with open(self.foldpath, "w") as f:
            json.dump(fold.to_dict(), f)

    def load_fold(self) -> Fold | None:
        if not os.path.exists(self.foldpath):
            return None
        with open(self.foldpath) as f:
            return Fold.from_dict(json.load(f))

    def reverted_ids(self) -> set[str]:
        """Intent ids excised by `weave rewind` (append-only; log untouched)."""
        fold = self.load_fold()
        return set(fold.reverted) if fold else set()
