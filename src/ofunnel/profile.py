"""Value profiles: a witness that comes from the VALUES themselves, not from keys, paths or hand-written shapes.

A requirement may carry a few example values (``exemplars``). From them the engine derives a profile: the
character-class signatures the values take ("dddd-AAdd" for a code like 4021-KP73, "dddd-dd-dd" for an ISO
date, "Aa a Aa"
for a short capitalised phrase), the class mix, and length. A candidate node's value is then scored against
that profile. This is the evidence the benchmarks kept asking for (opaque keys, decoys, column matching):
two fields with the same key spelling but different value populations are different fields, and two fields
with different spellings but the same value population are probably the same one.

It is generic (no domain vocabulary), stdlib only, and deterministic. Signatures are run-length collapsed so a
value's profile is stable across lengths ("fine" keeps run lengths, "coarse" drops them).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher

_NUM = re.compile(r"^\s*[-+]?\$?\s*\d[\d,]*(\.\d+)?\s*%?\s*$")
_DATE = re.compile(r"(\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.? +\d{1,2},? +\d{4}\b)", re.I)
_BOOL = {"yes", "no", "true", "false", "y", "n"}


def _cls(ch: str) -> str:
    if ch.isdigit():
        return "d"
    if ch.isalpha():
        return "A" if ch.isupper() else "a"
    if ch.isspace():
        return " "
    return ch                                                   # punctuation kept literally: it is structure


def signature(value: str | None, *, fine: bool = True) -> str:
    """Run-length-collapsed character-class signature. fine=True keeps run lengths (capped at 9 -> '+'),
    fine=False keeps only the class sequence."""
    s = (value or "").strip()
    if not s:
        return ""
    out = []
    prev, run = None, 0
    for ch in s:
        c = _cls(ch)
        if c == prev:
            run += 1
            continue
        if prev is not None:
            out.append(prev + (str(run) if run < 9 else "+") if (fine and prev in "dAa") else prev)
        prev, run = c, 1
    out.append(prev + (str(run) if run < 9 else "+") if (fine and prev in "dAa") else prev)
    return "".join(out)


@dataclass
class Profile:
    n: int = 0
    fine: Counter = field(default_factory=Counter)             # fine signature -> count
    coarse: Counter = field(default_factory=Counter)           # coarse signature -> count
    mix: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)   # digit / alpha / space / punct char fractions
    avg_len: float = 0.0
    numeric: float = 0.0                                       # fraction of values that are numbers
    datelike: float = 0.0                                      # fraction that contain a date
    boolean: float = 0.0
    distinct: float = 0.0                                      # distinct / n

    def top_coarse(self, k: int = 5) -> list[str]:
        return [s for s, _ in self.coarse.most_common(k)]


def profile(values) -> Profile:
    vals = [str(v).strip() for v in values if v is not None and str(v).strip()]
    p = Profile(n=len(vals))
    if not vals:
        return p
    d = a = s = o = 0
    tl = 0
    for v in vals:
        p.fine[signature(v)] += 1
        p.coarse[signature(v, fine=False)] += 1
        tl += len(v)
        for ch in v:
            if ch.isdigit():
                d += 1
            elif ch.isalpha():
                a += 1
            elif ch.isspace():
                s += 1
            else:
                o += 1
        if _NUM.match(v):
            p.numeric += 1
        if _DATE.search(v):
            p.datelike += 1
        if v.lower() in _BOOL:
            p.boolean += 1
    tot = max(1, d + a + s + o)
    p.mix = (d / tot, a / tot, s / tot, o / tot)
    p.avg_len = tl / len(vals)
    p.numeric /= len(vals)
    p.datelike /= len(vals)
    p.boolean /= len(vals)
    p.distinct = len(set(vals)) / len(vals)
    return p


def _cosine(c1: Counter, c2: Counter) -> float:
    if not c1 or not c2:
        return 0.0
    dot = sum(v * c2.get(k, 0) for k, v in c1.items())
    n1 = sum(v * v for v in c1.values()) ** 0.5
    n2 = sum(v * v for v in c2.values()) ** 0.5
    return dot / (n1 * n2) if n1 and n2 else 0.0


def similarity(p: Profile, q: Profile) -> float:
    """0..1 similarity of two value populations: signature-distribution overlap (dominant), class mix, length,
    and the numeric / date / boolean fractions. Two empty profiles are unknown (0.0), not similar."""
    if not p.n or not q.n:
        return 0.0
    sig = max(_cosine(p.coarse, q.coarse), 0.8 * _cosine(p.fine, q.fine))
    if sig == 0.0:                                              # no shared signature: soft-compare the dominant ones
        best = 0.0
        for s1 in p.top_coarse(3):
            for s2 in q.top_coarse(3):
                best = max(best, SequenceMatcher(None, s1, s2).ratio())
        sig = 0.6 * best
    mix = 1.0 - sum(abs(x - y) for x, y in zip(p.mix, q.mix)) / 2.0
    ln = min(p.avg_len, q.avg_len) / max(p.avg_len, q.avg_len) if max(p.avg_len, q.avg_len) else 1.0
    kinds = 1.0 - (abs(p.numeric - q.numeric) + abs(p.datelike - q.datelike) + abs(p.boolean - q.boolean)) / 3.0
    return round(0.55 * sig + 0.2 * mix + 0.1 * ln + 0.15 * kinds, 3)


def value_witness(value: str | None, p: Profile | None) -> float | None:
    """How well ONE value fits a requirement's profile: 1.0 fine-signature seen, 0.85 coarse seen, else a
    scaled soft similarity of the coarse signature to the profile's dominant ones. None when no profile."""
    if p is None or not p.n:
        return None
    if value is None or not str(value).strip():
        return 0.0
    f, c = signature(value), signature(value, fine=False)
    if f in p.fine:
        return 1.0
    if c in p.coarse:
        return 0.85
    best = max((SequenceMatcher(None, c, s).ratio() for s in p.top_coarse(5)), default=0.0)
    return round(0.7 * best, 3)
