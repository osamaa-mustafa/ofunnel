"""Throughput and latency (standard library only): a byte regex vs O-Funnel on pristine documents (fast path),
fully drifted documents (every field resolved by the non-key rungs), and with the scavenger on. Also the split
of O-Funnel's time between capture, the completeness oracle, and resolution. Median of repeated runs.

    python benchmarks/perf.py
"""
from __future__ import annotations

import re
import statistics
import time

from ofunnel import Requirement, capture, check_complete, extract, resolve_all

CODE, ISO, CAT = r"\d{4}-[A-Z]{2}\d{2}", r"\d{4}-\d{2}-\d{2}", r"\d{1,2} [A-Z]{3} \d{1,4}"
SYNONYMS = {"record_id": {"record_id", "record identifier"}, "category_ref": {"category_ref", "category reference"}}
REGEX = [re.compile(rf"\b{CODE}\b"), re.compile(rf"\b{ISO}\b"), re.compile(rf"\b{CAT}\b")]
REQS = [Requirement("record_id", concept="record_id", keys=("record_id",), shape=rf"^{CODE}$"),
        Requirement("received_date", keys=("received_date",), shape=ISO, normalize="date", neighbors=("record_id", "status")),
        Requirement("category_ref", concept="category_ref", keys=("category_ref",), shape=CAT),
        Requirement("decision", keys=("decision",))]


def doc(i, drifted=False):
    code, date, cat = f"{1000 + i % 9000:04d}-AA{i % 9}0", f"2026-{1 + i % 12:02d}-{1 + i % 27:02d}", f"{7 + i % 40} ALP {10 + i % 900}"
    if drifted:
        return (f"<RECORD><recordIdentifier>{code}</recordIdentifier><STATUS>Final</STATUS><receivedDate>{date}"
                f"</receivedDate><categoryReference>{cat}</categoryReference><disposition>Approved</disposition></RECORD>").encode()
    return (f"<RECORD><RECORD_ID>{code}</RECORD_ID><STATUS>Final</STATUS><DATE_RECEIVED>{date}</DATE_RECEIVED>"
            f"<CATEGORY_REF>{cat}</CATEGORY_REF><DECISION>Approved</DECISION></RECORD>").encode()


def timed(fn, items, repeat=3):
    runs = []
    for _ in range(repeat):
        t = time.perf_counter()
        for x in items:
            fn(x)
        runs.append(time.perf_counter() - t)
    med = statistics.median(runs)
    return med / len(items) * 1000, len(items) / med


def main(n=2000):
    pristine = [doc(i) for i in range(n)]
    drifted = [doc(i, True) for i in range(n)]
    print(f"{'system':42} {'ms/doc':>8} {'docs/s':>9}")
    print("-" * 61)
    for name, fn, corpus in [
        ("byte regex", lambda r: [rx.search(r.decode()) for rx in REGEX], pristine),
        ("O-Funnel, pristine (fast path)", lambda r: extract(r, REQS, fmt="xml", synonyms=SYNONYMS), pristine),
        ("O-Funnel, every field drifted", lambda r: extract(r, REQS, fmt="xml", synonyms=SYNONYMS), drifted),
        ("O-Funnel, pristine + scavenger", lambda r: extract(r, REQS, fmt="xml", synonyms=SYNONYMS, scavenge=True), pristine),
    ]:
        ms, dps = timed(fn, corpus)
        print(f"{name:42} {ms:8.3f} {dps:9,.0f}")
    trees = [capture(r, fmt="xml")[0] for r in pristine]
    ms_cap, _ = timed(lambda r: capture(r, fmt="xml"), pristine)
    ms_orc, _ = timed(lambda i: check_complete(pristine[i], trees[i], "xml"), list(range(n)))
    ms_res, _ = timed(lambda t: resolve_all(t, REQS, synonyms=SYNONYMS), trees)
    tot = ms_cap + ms_orc + ms_res
    print(f"\ntime split (pristine): capture {ms_cap / tot:.0%}, oracle {ms_orc / tot:.0%}, resolve {ms_res / tot:.0%}")
    dtrees = [capture(r, fmt="xml")[0] for r in drifted]
    ms_d, _ = timed(lambda t: resolve_all(t, REQS, synonyms=SYNONYMS), dtrees)
    print(f"resolution cost, drifted vs pristine: {ms_d / ms_res:.1f}x")


if __name__ == "__main__":
    main()
