"""Perturbation suite: 13 base records rendered under 9 drift categories = 117 documents, 4 fields each
(468 field checks). Compares a plain byte-regex baseline, O-Funnel, and O-Funnel after the funnel has learned
aliases from the corpus residue. Fully synthetic and deterministic.

    python benchmarks/perturbation.py
"""
from __future__ import annotations

import csv as csvmod
import io
import json
import re

from ofunnel import Pipeline, Requirement, as_date, extract

CODE = r"\d{4}-[A-Z]{2}\d{2}"
ISO = r"\d{4}-\d{2}-\d{2}"
CAT = r"\d{1,2} [A-Z]{3} \d{1,4}"
SYNONYMS = {"record_id": {"record_id", "record identifier"},
            "category_ref": {"category_ref", "category reference"}}
FIELDS = ["record_id", "received_date", "category_ref", "decision"]
REGEX = {"record_id": rf"\b{CODE}\b", "received_date": rf"\b{ISO}\b", "category_ref": rf"\b{CAT}\b", "decision": None}


def requirements():
    return [
        Requirement("record_id", concept="record_id", keys=("record_id",), shape=rf"^{CODE}$"),
        Requirement("received_date", keys=("received_date",), normalize="date", neighbors=("record_id", "status")),
        Requirement("category_ref", concept="category_ref", keys=("category_ref",), shape=CAT),
        Requirement("decision", keys=("decision",)),
    ]


BASE = [
    ("0503-AA90", "2026-06-17", "7 ALP 16", "Approved with Changes"),
    ("0938-AV45", "2026-05-14", "42 BRV 405", "Approved without Changes"),
    ("1018-BH58", "2026-08-24", "50 CHR 17", "Withdrawn"),
    ("2900-AR75", "2026-01-05", "38 DLT 3", "Approved with Changes"),
    ("1235-AA55", "2026-03-11", "29 ALP 552", "Returned"),
    ("0694-AK13", "2026-07-02", "15 BRV 744", "Approved with Changes"),
    ("1545-BQ12", "2026-09-01", "26 CHR 1", "Approved without Changes"),
    ("3235-AN00", "2026-04-20", "17 DLT 240", "Approved with Changes"),
    ("2127-AM10", "2026-02-28", "49 ALP 571", "Withdrawn"),
    ("0648-BK86", "2026-10-01", "50 BRV 648", "Approved with Changes"),
    ("2050-AH12", "2026-11-15", "40 CHR 60", "Approved with Changes"),
    ("1210-AC05", "2026-06-30", "29 DLT 2550", "Returned"),
    ("0790-AL85", "2026-12-05", "32 ALP 199", "Approved with Changes"),
]
TAGS = {"record_id": "RECORD_ID", "received_date": "DATE_RECEIVED", "category_ref": "CATEGORY_REF", "decision": "DECISION"}
SYNONYM_RENAME = {"RECORD_ID": "recordIdentifier", "DATE_RECEIVED": "receivedDate",
                  "CATEGORY_REF": "categoryReference", "DECISION": "finalDisposition"}
CAMEL_RENAME = {"RECORD_ID": "recordId", "DATE_RECEIVED": "dateReceived", "CATEGORY_REF": "categoryRef", "DECISION": "decision"}
OPAQUE_RENAME = {"RECORD_ID": "c1", "DATE_RECEIVED": "c2", "CATEGORY_REF": "c3", "DECISION": "c4"}
_MON = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
        "November", "December"]


def _long(iso):
    y, m, d = map(int, iso.split("-"))
    return f"{_MON[m - 1]} {d}, {y}"


def _xml(v, rename=None, longdate=False, decoy=False):
    rn = rename or {}
    t = {k: rn.get(t, t) for k, t in TAGS.items()}
    date = _long(v["received_date"]) if longdate else v["received_date"]
    parts = ['<RELATED_ID>9999-ZZ99</RELATED_ID><PRIOR_DATE>2020-01-01</PRIOR_DATE>'] if decoy else []
    parts += [f'<{t["record_id"]}>{v["record_id"]}</{t["record_id"]}>', "<STATUS>Final</STATUS>",
              f'<{t["received_date"]}>{date}</{t["received_date"]}>',
              f'<{t["category_ref"]}>{v["category_ref"]}</{t["category_ref"]}>',
              f'<{t["decision"]}>{v["decision"]}</{t["decision"]}>']
    return "xml", ("<RECORD>" + "".join(parts) + "</RECORD>").encode()


def _json(v, rename=None):
    rn = rename or {}
    d = {rn.get(TAGS["record_id"], TAGS["record_id"]): v["record_id"], "STATUS": "Final"}
    for f in ("received_date", "category_ref", "decision"):
        d[rn.get(TAGS[f], TAGS[f])] = v[f]
    return "json", json.dumps(d).encode()


def _csv(v):
    buf = io.StringIO()
    w = csvmod.writer(buf)
    w.writerow(["RECORD_ID", "STATUS", "DATE_RECEIVED", "CATEGORY_REF", "DECISION"])
    w.writerow([v["record_id"], "Final", v["received_date"], v["category_ref"], v["decision"]])
    return "csv", buf.getvalue().encode()


CATEGORIES = {
    "pristine XML": lambda v: _xml(v),
    "renamed (synonym)": lambda v: _xml(v, SYNONYM_RENAME),
    "camelCase": lambda v: _xml(v, CAMEL_RENAME),
    "JSON": lambda v: _json(v),
    "JSON renamed": lambda v: _json(v, SYNONYM_RENAME),
    "CSV": lambda v: _csv(v),
    "long-form date": lambda v: _xml(v, longdate=True),
    "decoy first": lambda v: _xml(v, decoy=True),
    "opaque keys": lambda v: _xml(v, OPAQUE_RENAME),
}


def cases():
    out = []
    for b in BASE:
        v = dict(zip(FIELDS, b))
        for cat, fn in CATEGORIES.items():
            fmt, raw = fn(v)
            out.append((cat, fmt, raw, v))
    return out


def _norm(field, x):
    if x is None:
        return None
    if field == "received_date":
        d = as_date(x if isinstance(x, str) else str(x))
        return d.isoformat() if d else str(x).strip()
    return str(x).strip()


def regex_extract(fmt, raw):
    text = raw.decode("utf-8", "replace")
    return {f: re.search(rx, text).group(0) for f, rx in REGEX.items() if rx and re.search(rx, text)}


def score(system, all_cases):
    per = {}
    for cat, fmt, raw, gold in all_cases:
        got = system(fmt, raw)
        acc = per.setdefault(cat, [0, 0, 0])            # tp, fp, fn
        for f in FIELDS:
            g, p = _norm(f, gold.get(f)), _norm(f, got.get(f))
            if g is not None and p == g:
                acc[0] += 1
            elif p is not None:
                acc[1] += 1
            elif g is not None:
                acc[2] += 1
    return per


def f1(acc):
    tp, fp, fn = acc
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def main():
    all_cases = cases()
    print(f"{len(all_cases)} documents ({len(BASE)} records x {len(CATEGORIES)} categories), "
          f"{len(all_cases) * len(FIELDS)} field checks\n")
    reg = score(regex_extract, all_cases)
    ofn = score(lambda fmt, raw: extract(raw, requirements(), fmt=fmt, synonyms=SYNONYMS).found(), all_cases)
    pipe = Pipeline(requirements(), synonyms={k: set(v) for k, v in SYNONYMS.items()})
    for _, fmt, raw, _ in all_cases:
        pipe.extract(raw, fmt=fmt)
    _, promoted = pipe.learn(min_support=3, min_confidence=0.6)
    learned = score(lambda fmt, raw: pipe.extract(raw, fmt=fmt, keep_for_learning=False).found(), all_cases)

    print(f"{'category':20} {'regex F1':>9} {'O-Funnel F1':>12} {'+ learned F1':>13}")
    print("-" * 57)
    tot = [[0, 0, 0] for _ in range(3)]
    for cat in CATEGORIES:
        for i, d in enumerate((reg, ofn, learned)):
            tot[i] = [a + b for a, b in zip(tot[i], d[cat])]
        print(f"{cat:20} {f1(reg[cat]):9.2f} {f1(ofn[cat]):12.2f} {f1(learned[cat]):13.2f}")
    print("-" * 57)
    print(f"{'overall':20} {f1(tot[0]):9.2f} {f1(tot[1]):12.2f} {f1(tot[2]):13.2f}")
    print(f"\npromoted by the funnel: {promoted}")


if __name__ == "__main__":
    main()
