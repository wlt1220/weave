"""Negotiation protocol: structured agent-to-agent conflict resolution.

The protocol (transcript + outcome) is real; the arbiter is pluggable.
v1 ships a rule-based arbiter; the production design resumes the authoring
agents with a shared context snapshot (LLM arbiter).
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .intent import Intent


@dataclass
class DecisionRecord:
    intents: list[str]           # intent ids in contention
    transcript: list[dict]       # the negotiation, versioned
    outcome: str                 # "merged" | "escalated"
    winner: str | None = None
    ghost_genes: list[str] = field(default_factory=list)  # preserved losers
    human_context: str = ""      # attached when escalated
    id: str = ""

    def seal(self) -> "DecisionRecord":
        self.id = hashlib.sha256(
            json.dumps(self.transcript, sort_keys=True).encode()).hexdigest()[:16]
        return self


class NegotiationSession:
    def __init__(self, intent_a: Intent, intent_b: Intent, reason: str):
        self.intents = [intent_a, intent_b]
        self.reason = reason
        self.transcript: list[dict] = [
            {"speaker": "system",
             "message": f"negotiation opened: {reason}"},
            {"speaker": intent_a.author.agent_id,
             "message": intent_a.rationale or f"intends: {intent_a.goal}"},
            {"speaker": intent_b.author.agent_id,
             "message": intent_b.rationale or f"intends: {intent_b.goal}"},
        ]

    def run(self, arbiter) -> DecisionRecord:
        return arbiter.arbitrate(self)


class RuleArbiter:
    """v1 arbiter. Priority: verified beats unverified; ties escalate."""

    def arbitrate(self, session: NegotiationSession) -> DecisionRecord:
        a, b = session.intents
        va, vb = a.verified, b.verified
        if va and not vb:
            winner, loser = a, b
        elif vb and not va:
            winner, loser = b, a
        else:
            session.transcript.append({
                "speaker": "arbiter",
                "message": (f"both intents verified={va}: no safe automatic "
                            f"resolution — escalating to human with full context"),
            })
            return DecisionRecord(
                intents=[a.id, b.id],
                transcript=session.transcript,
                outcome="escalated",
                human_context=(f"contested: {a.goal!r} vs {b.goal!r}; "
                               f"overlap: {session.reason}"),
            ).seal()

        session.transcript.append({
            "speaker": "arbiter",
            "message": (f"exactly one verified intent: "
                        f"{winner.author.agent_id} wins; "
                        f"{loser.author.agent_id}'s change parked as ghost gene "
                        f"for follow-up"),
        })
        ghost = {"intent": loser.id, "goal": loser.goal,
                 "superseded_by": winner.id}
        return DecisionRecord(
            intents=[a.id, b.id],
            transcript=session.transcript,
            outcome="merged",
            winner=winner.id,
            ghost_genes=[ghost],
        ).seal()
