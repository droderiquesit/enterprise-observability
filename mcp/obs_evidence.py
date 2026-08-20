"""EVIDENCE — the citation type every Ask answer is built from.

An answer without a citation is an opinion, and an opinion delivered by a tool
is worse than no answer: it is indistinguishable from a measured fact at the
point somebody acts on it. So the Answer type below REFUSES to serialize an
answerable result that cites nothing, and `mcp/tests/test_ask_grounding.py`
walks every question in the catalog to prove the refusal never has to fire.

Two shapes, deliberately:

  Evidence   where a claim came from — a source locator, the object kind, the
             actual object ids (capped, with the true count kept), and a note.
             `source` is always resolvable by a human: a repo-relative path, a
             Datadog API route, or `fixture:<path>`.

  Answer     the envelope. `answerable=False` is a first-class outcome, not an
             error: several §43 questions cannot be answered from this org's
             data today (empty on-call rosters, no deployment metadata), and
             saying so with a reason is the correct result. Guessing is not.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Any

# Citing 40,000 resource ids helps nobody and blows up every transport in the
# chain. Cite a sample and keep the true count — the count is the claim, the
# sample is how a reader checks it.
MAX_CITED_IDS = 25


@dataclasses.dataclass
class Evidence:
    source: str
    kind: str
    ids: list[str] = dataclasses.field(default_factory=list)
    count: int | None = None
    note: str = ""

    def to_dict(self) -> dict:
        ids = [str(i) for i in self.ids]
        return {
            "source": self.source,
            "kind": self.kind,
            "ids": ids[:MAX_CITED_IDS],
            "ids_truncated": len(ids) > MAX_CITED_IDS,
            "count": self.count if self.count is not None else len(ids),
            "note": self.note,
        }


@dataclasses.dataclass
class Answer:
    question: str
    summary: str = ""
    data: dict[str, Any] = dataclasses.field(default_factory=dict)
    evidence: list[Evidence] = dataclasses.field(default_factory=list)
    caveats: list[str] = dataclasses.field(default_factory=list)
    answerable: bool = True
    unanswerable_reason: str = ""
    mode: str = "fixtures"
    as_of: str = ""

    def cite(self, source: str, kind: str, ids=None, count=None, note="") -> "Answer":
        self.evidence.append(Evidence(source=source, kind=kind,
                                      ids=list(ids or []), count=count, note=note))
        return self

    def caveat(self, text: str) -> "Answer":
        if text not in self.caveats:
            self.caveats.append(text)
        return self

    def unanswerable(self, reason: str) -> "Answer":
        """Record that the data needed does not exist, and why.

        The reason is the deliverable. "Unknown" tells a responder nothing;
        "the on-call rosters are empty, so no schedule resolves to a person"
        tells them exactly which gap to close.
        """
        self.answerable = False
        self.unanswerable_reason = reason
        return self

    def to_dict(self) -> dict:
        if self.answerable and not self.evidence:
            raise ValueError(
                f"question {self.question!r} produced an answerable result with no "
                "evidence — every Ask answer must cite its source"
            )
        return {
            "question": self.question,
            "answerable": self.answerable,
            "unanswerable_reason": self.unanswerable_reason,
            "summary": self.summary,
            "data": self.data,
            "evidence": [e.to_dict() for e in self.evidence],
            "caveats": self.caveats,
            "mode": self.mode,
            "as_of": self.as_of or dt.datetime.now(dt.timezone.utc).isoformat(),
        }
