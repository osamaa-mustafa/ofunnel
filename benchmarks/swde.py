"""Web extraction on a SWDE-derived set: the first 500 rows of the validation split of
hazyresearch/based-swde-old on Hugging Face (movie vertical; each row is an HTML slice, an attribute name,
and the gold value). A requirement is built from the attribute name alone and resolved against the HTML.

This is a deliberate out-of-scope probe: in SWDE pages the field name usually sits in a separate label element
next to the value (<td>Director</td><td>Sam Raimi</td>), a relation O-Funnel's rungs do not model. It is
reported as a negative result.

Get the rows (needs network):
    python benchmarks/swde.py --fetch swde_rows.json
Run:
    python benchmarks/swde.py swde_rows.json
"""
from __future__ import annotations

import collections
import json
import re
import sys
import time
import urllib.request

from ofunnel import Requirement, extract

DATASET = "hazyresearch/based-swde-old"
SHAPES = {"year": r"\b(?:19|20)\d{2}\b", "mpaa rating": r"\b(?:G|PG|PG-13|R|NC-17|NR|Unrated)\b"}


def fetch(path, n=500):
    rows, base = [], "https://datasets-server.huggingface.co/rows"
    while len(rows) < n:
        url = f"{base}?dataset={DATASET}&config=default&split=validation&offset={len(rows)}&length={min(100, n - len(rows))}"
        batch = json.load(urllib.request.urlopen(url, timeout=60))["rows"]
        if not batch:
            break
        rows += [{k: r["row"][k] for k in ("key", "value", "text")} for r in batch]
    json.dump(rows, open(path, "w", encoding="utf-8"))
    print(f"wrote {len(rows)} rows to {path}")


def norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def main(path):
    rows = json.load(open(path, encoding="utf-8"))
    per, hit, rx = collections.Counter(), collections.Counter(), collections.Counter()
    t0 = time.perf_counter()
    for r in rows:
        attr, gold, page = r["key"], r["value"], r["text"]
        per[attr] += 1
        aliases = tuple({attr, attr.replace(" ", "_"), attr.replace(" ", ""), attr.replace("/", " ")})
        req = Requirement(attr, keys=aliases, shape=SHAPES.get(attr), fuzzy=0.5)
        try:
            v = extract(page.encode("utf-8", "replace"), [req], fmt="html", scavenge=True).value(attr)
        except Exception:
            v = None
        hit[attr] += int(v is not None and norm(v) == norm(gold))
        if attr in SHAPES:
            m = re.search(SHAPES[attr], page)
            rx[attr] += int(bool(m) and norm(m.group(0)) == norm(gold))
    n = sum(per.values())
    print(f"{n} rows, {len(per)} attributes, {time.perf_counter() - t0:.1f}s\n")
    print(f"{'attribute':18} {'n':>4} {'O-Funnel':>9} {'value regex':>12}")
    for a in sorted(per):
        rxs = f"{rx[a] / per[a]:12.1%}" if a in SHAPES else f"{'n/a':>12}"
        print(f"{a:18} {per[a]:4d} {hit[a] / per[a]:9.1%} {rxs}")
    print(f"{'overall':18} {n:4d} {sum(hit.values()) / n:9.1%}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--fetch"]:
        fetch(sys.argv[2] if len(sys.argv) > 2 else "swde_rows.json")
    else:
        main(sys.argv[1] if len(sys.argv) > 1 else "swde_rows.json")
