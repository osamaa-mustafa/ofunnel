"""Self-improvement from residue. A corpus whose identifier and decision keys drifted to opaque tokens
('f7', 'disp') is resolved, the funnel traces the residue back to the requirements, the safe proposals are
promoted, and the corpus is resolved again. Run twice: without exemplars (the free-text decision has no
structural signal, so nothing can be traced) and with a handful of exemplars (its value population alone
identifies it).

    python benchmarks/funnel_gain.py
"""
from __future__ import annotations

from dataclasses import replace

from ofunnel import Requirement, capture, funnel, promote, resolve_all

CODE = r"^\d{4}-[A-Z]{2}\d{2}$"
DECISIONS = ["Approved with Changes", "Approved without Changes", "Withdrawn by Sponsor", "Returned for Revision"]
EXEMPLARS = ("Approved with Changes", "Returned for Revision")


LOOKALIKE = ["Withdrawn", "Returned", "Approved", "Deferred"]   # single words, like the neighboring STATUS value


def corpus(n=24, decisions=DECISIONS):
    trees, golds = [], []
    for i in range(n):
        code, dec = f"{1000 + i * 37:04d}-A{chr(65 + i % 26)}{i % 90 + 10:02d}", decisions[i % 4]
        date = f"2026-{1 + i % 12:02d}-{1 + i % 27:02d}"
        raw = (f"<RECORD><f7>{code}</f7><STATUS>Final</STATUS><DATE_RECEIVED>{date}</DATE_RECEIVED>"
               f"<disp>{dec}</disp></RECORD>").encode()
        trees.append(capture(raw, fmt="xml")[0])
        golds.append({"record_id": code, "decision": dec})
    return trees, golds


def recall(trees, golds, reqs, field=None):
    tp = tot = 0
    for tree, gold in zip(trees, golds):
        rep = resolve_all(tree, reqs)
        for name, gv in gold.items():
            if field and name != field:
                continue
            tot += 1
            m = rep.one(name)
            tp += int(bool(m and m.found and (m.raw or "").strip() == gv))
    return tp / tot if tot else 0.0


def run(with_exemplars: bool, lookalike: bool = False):
    exemplars = ("Withdrawn", "Returned") if lookalike else EXEMPLARS
    reqs = [Requirement("record_id", keys=("record_id",), shape=CODE, fuzzy=None),
            Requirement("decision", keys=("decision",), fuzzy=None,
                        exemplars=exemplars if with_exemplars else ())]
    trees, golds = corpus(decisions=LOOKALIKE if lookalike else DECISIONS)
    before = {f: recall(trees, golds, reqs, f) for f in ("record_id", "decision")}
    rep = funnel(trees, reqs, min_support=3)
    promoted = promote(rep, min_support=3, min_confidence=0.6)
    reqs2 = [replace(r, keys=r.keys + tuple(promoted.get(r.name, []))) for r in reqs]
    after = {f: recall(trees, golds, reqs2, f) for f in ("record_id", "decision")}
    label = "with exemplars" if with_exemplars else "no exemplars"
    if lookalike:
        label += ", decision values look like the STATUS value"
        contested = {p.key: f"{p.contested}/{p.support}" for p in rep.proposals if p.requirement == "decision"}
        print(f"[{label}] decision proposals contested: {contested}")
    print(f"[{label}] promoted {promoted}")
    for f in ("record_id", "decision"):
        print(f"   {f:10} recall {before[f]:.2f} -> {after[f]:.2f}")
    print(f"   overall    recall {sum(before.values()) / 2:.2f} -> {sum(after.values()) / 2:.2f}")


if __name__ == "__main__":
    run(with_exemplars=False)
    print()
    run(with_exemplars=True)
    print()
    run(with_exemplars=True, lookalike=True)        # the contest check: nothing unsafe is promoted
