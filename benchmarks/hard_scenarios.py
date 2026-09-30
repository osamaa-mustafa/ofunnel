"""Hard scenarios: 15 records x 8 classes = 120 documents, each class isolating one way a byte regex fails
(free-text fields, several same-type values with the target not first, a same-shape decoy before the real
value, long and US date formats, a date-shaped token in a title, free text in JSON) plus fully opaque keys.
Deliberately constructed to probe those failure modes; not a sample of real-world difficulty.

    python benchmarks/hard_scenarios.py
"""
from __future__ import annotations

import json
import re

from ofunnel import Requirement, as_date, extract

CODE = r"\d{4}-[A-Z]{2}\d{2}"
ISO = r"\d{4}-\d{2}-\d{2}"
CAT = r"\d{1,2} [A-Z]{3} \d{1,4}"
ANYDATE = (r"(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|(?:January|February|March|April|May|June|July|August|"
           r"September|October|November|December)\s+\d{1,2},\s+\d{4})")
SYNONYMS = {"record_id": {"record_id", "record identifier"}, "category_ref": {"category_ref", "category reference"}}
REGEX = {"record_id": rf"\b{CODE}\b", "received_date": rf"\b{ISO}\b", "category_ref": rf"\b{CAT}\b",
         "decision": None, "priority": None}
_MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
        "November", "December"]
PAIRS = [("Approved with Changes", "High Impact"), ("Withdrawn", "Moderate Impact"),
         ("Approved without Changes", "Low Impact"), ("Returned", "Routine")]
CODES3 = ["ALP", "BRV", "CHR", "DLT"]


def requirements():
    return [
        Requirement("record_id", concept="record_id", keys=("record_id",), shape=rf"^{CODE}$"),
        Requirement("received_date", keys=("received_date",), shape=ANYDATE, normalize="date",
                    neighbors=("record_id", "status")),
        Requirement("category_ref", concept="category_ref", keys=("category_ref",), shape=CAT),
        Requirement("decision", keys=("decision",)),
        Requirement("priority", keys=("priority_category", "priority")),
    ]


RECORDS = [(f"{r:04d}-AA{r % 9}0", f"2026-{1 + r % 12:02d}-{1 + r % 27:02d}", f"{7 + r % 40} {CODES3[r % 4]} {10 + r}",
            *PAIRS[r % 4]) for r in range(15)]


def _long(iso):
    y, m, d = map(int, iso.split("-"))
    return f"{_MON[m - 1]} {d}, {y}"


def _us(iso):
    y, m, d = map(int, iso.split("-"))
    return f"{m:02d}/{d:02d}/{y}"


def scenarios(rec):
    code, date, cat, dec, pri = rec
    x = lambda body: ("xml", f"<RECORD>{body}</RECORD>".encode())
    return [
        ("free-text fields", *x(f"<RECORD_ID>{code}</RECORD_ID><STATUS>Final</STATUS><DECISION>{dec}</DECISION>"
                                f"<PRIORITY_CATEGORY>{pri}</PRIORITY_CATEGORY>"), {"decision": dec, "priority": pri}),
        ("multi-date attribution", *x(f"<RECORD_ID>{code}</RECORD_ID><STATUS>Final</STATUS><DATE_PUBLISHED>2099-12-31"
                                      f"</DATE_PUBLISHED><DATE_COMPLETED>2098-11-30</DATE_COMPLETED>"
                                      f"<DATE_RECEIVED>{date}</DATE_RECEIVED>"), {"received_date": date}),
        ("decoy identifier", *x(f"<RELATED_ID>9999-ZZ99</RELATED_ID><RECORD_ID>{code}</RECORD_ID><STATUS>Final</STATUS>"
                                f"<DATE_RECEIVED>{date}</DATE_RECEIVED>"), {"record_id": code}),
        ("date, long format", *x(f"<RECORD_ID>{code}</RECORD_ID><STATUS>Final</STATUS>"
                                 f"<DATE_RECEIVED>{_long(date)}</DATE_RECEIVED>"), {"received_date": date}),
        ("date, US format", *x(f"<RECORD_ID>{code}</RECORD_ID><STATUS>Final</STATUS>"
                               f"<DATE_RECEIVED>{_us(date)}</DATE_RECEIVED>"), {"received_date": date}),
        ("date decoy in a title", *x(f"<RECORD_ID>{code}</RECORD_ID><TITLE>Correction to notice filed 2020-01-01</TITLE>"
                                     f"<STATUS>Final</STATUS><DATE_RECEIVED>{date}</DATE_RECEIVED>"),
         {"received_date": date}),
        ("JSON free text", "json", json.dumps({"RECORD_ID": code, "STATUS": "Final", "DECISION": dec}).encode(),
         {"decision": dec}),
        ("fully opaque keys", *x(f"<c1>{code}</c1><c9>Final</c9><c2>{date}</c2><c3>{cat}</c3>"),
         {"record_id": code, "received_date": date, "category_ref": cat}),
    ]


def _norm(f, v):
    if v is None:
        return None
    if f == "received_date":
        d = as_date(v if isinstance(v, str) else str(v))
        return d.isoformat() if d else str(v).strip()
    return str(v).strip()


def regex_extract(fmt, raw):
    t = raw.decode("utf-8", "replace")
    return {f: re.search(rx, t).group(0) for f, rx in REGEX.items() if rx and re.search(rx, t)}


def f1(cases, system):
    tp = fp = fn = 0
    for _, fmt, raw, gold in cases:
        got = system(fmt, raw)
        for f in gold:
            g, p = _norm(f, gold[f]), _norm(f, got.get(f))
            if p is not None and p == g:
                tp += 1
            elif p is not None:
                fp += 1
            else:
                fn += 1
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def main():
    allc = [s for rec in RECORDS for s in scenarios(rec)]
    classes = list(dict.fromkeys(c[0] for c in allc))
    ofn = lambda fmt, raw: extract(raw, requirements(), fmt=fmt, synonyms=SYNONYMS).found()
    scav = lambda fmt, raw: extract(raw, requirements(), fmt=fmt, synonyms=SYNONYMS, scavenge=True).found()
    print(f"{len(allc)} documents ({len(RECORDS)} records x {len(classes)} classes)\n")
    print(f"{'class':24} {'regex F1':>9} {'O-Funnel F1':>12} {'+ scavenger F1':>15}")
    print("-" * 63)
    for cls in classes:
        cc = [c for c in allc if c[0] == cls]
        print(f"{cls:24} {f1(cc, regex_extract):9.2f} {f1(cc, ofn):12.2f} {f1(cc, scav):15.2f}")
    print("-" * 63)
    print(f"{'overall':24} {f1(allc, regex_extract):9.2f} {f1(allc, ofn):12.2f} {f1(allc, scav):15.2f}")


if __name__ == "__main__":
    main()
