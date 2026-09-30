"""The stitched pipeline: one entry point that ties capture + completeness gate + the resolution ladder +
residue together for online extraction, plus the offline learn step (funnel -> promote -> grow the aliases).

Online, per document:
    capture (lossless, oracle-gated) -> resolve requirements (the ladder returns at the first rung that hits,
    so cheap rungs -- key/path/synonym -- carry pristine data at near tag-lookup speed and only a missed field
    pays for the expensive rungs) -> ExtractResult(fields, residue, complete).

Offline, over the accumulated corpus:
    Pipeline.learn() runs the O-through funnel on the residue, promotes the well-supported uncontested
    proposals, and folds them back into the requirements' keys, so the next online run resolves those keys on
    the cheap rung. The system gets more complete and faster as it learns; nothing is auto-trusted that the
    funnel flagged contested.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from .adapters import capture
from .funnel import funnel, promote
from .model import Node
from .oracle import check_complete
from .require import Match, Requirement, resolve_all


@dataclass
class ExtractResult:
    fields: dict[str, Match]              # requirement name -> best Match (a found one, or an 'absent' Match)
    residue: list[Node]
    complete: bool                        # the capture reconstructed its source
    fmt: str
    reasons: dict[str, str] = field(default_factory=dict)   # absent requirement -> why (from the ladder / scavenger)

    def value(self, name: str):
        m = self.fields.get(name)
        return m.value if m else None

    def found(self) -> dict[str, object]:
        return {n: m.value for n, m in self.fields.items() if m.found}


def extract(raw: bytes, requirements, *, fmt: str | None = None, synonyms: dict | None = None,
            scavenge: bool = False) -> ExtractResult:
    """Online single-document extraction: capture, gate, resolve. Never raises on a missing field -- an absent
    field is a reported Match, not an omission; a capture that fails the oracle is flagged in ``complete``.
    ``scavenge=True`` recovers an absent shape-bearing field from a unique residue value (opaque keys)."""
    tree, fmt = capture(raw, fmt=fmt)
    complete = check_complete(raw, tree, fmt)
    rep = resolve_all(tree, requirements, synonyms=synonyms, scavenge=scavenge)
    fields: dict[str, Match] = {}
    for r in requirements:
        ms = rep.matches.get(r.name)
        fields[r.name] = ms[0] if ms else Match(r.name, None, None, "absent", 1.0, (), None, reason=rep.reasons.get(r.name))
    return ExtractResult(fields=fields, residue=rep.residue, complete=complete, fmt=fmt, reasons=dict(rep.reasons))


@dataclass
class Pipeline:
    """A live extractor that accumulates residue and can learn aliases from it offline."""
    requirements: list[Requirement]
    synonyms: dict = field(default_factory=dict)
    _trees: list[Node] = field(default_factory=list)

    scavenge: bool = False
    auto_learn_every: int | None = None   # continuous mode: after this many kept trees, learn() runs and the buffer clears
    learned: list = field(default_factory=list)   # (report, promoted) of each automatic learn round

    def extract(self, raw: bytes, *, fmt: str | None = None, keep_for_learning: bool = True) -> ExtractResult:
        tree, fmt = capture(raw, fmt=fmt)
        complete = check_complete(raw, tree, fmt)
        rep = resolve_all(tree, self.requirements, synonyms=self.synonyms, scavenge=self.scavenge)
        fields = {}
        for r in self.requirements:
            ms = rep.matches.get(r.name)
            fields[r.name] = ms[0] if ms else Match(r.name, None, None, "absent", 1.0, (), None, reason=rep.reasons.get(r.name))
        if keep_for_learning:
            self._trees.append(tree)
            if self.auto_learn_every and len(self._trees) >= self.auto_learn_every:
                self.learned.append(self.learn())
                self._trees.clear()
        return ExtractResult(fields=fields, residue=rep.residue, complete=complete, fmt=fmt, reasons=dict(rep.reasons))

    def learn(self, *, min_support: int = 3, min_confidence: float = 0.7, max_contested_ratio: float = 0.25):
        """Offline: funnel the accumulated residue into alias proposals, promote the safe ones, and fold them
        into the requirements' keys (so they resolve on the cheap key rung next run). Returns (report, promoted)."""
        rep = funnel(self._trees, self.requirements, synonyms=self.synonyms, min_support=min_support)
        promoted = promote(rep, min_support=min_support, min_confidence=min_confidence, max_contested_ratio=max_contested_ratio)
        if promoted:
            by_group = {}
            for r in self.requirements:
                by_group.setdefault(r.concept or r.name, []).append(r)
            new_reqs = list(self.requirements)
            for group, aliases in promoted.items():
                if group in self.synonyms or any(r.concept for r in by_group.get(group, [])):
                    self.synonyms.setdefault(group, set())
                    self.synonyms[group] = set(self.synonyms[group]) | set(aliases)
                for r in by_group.get(group, []):
                    merged = tuple(dict.fromkeys(r.keys + tuple(aliases)))
                    new_reqs[new_reqs.index(r)] = replace(r, keys=merged)
            self.requirements = new_reqs
        return rep, promoted
