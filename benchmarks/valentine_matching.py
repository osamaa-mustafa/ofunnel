"""Schema matching on the public Valentine benchmark, O-Funnel's key-similarity and value-profile machinery
side by side with classical matchers (COMA schema/instance, Cupid, Similarity Flooding, distribution-based),
all run through the Valentine framework with default settings. Metric: recall at ground truth (rank predicted
column pairs, take the top |gold|, count gold pairs recovered), micro-averaged per category.

The instance subset is held out: a seeded sample disjoint from the seed-0 sample used during development.

Requires the optional packages `valentine` and `pandas` and the Valentine datasets
(https://zenodo.org/records/5084605), unpacked so that <root>/<category>/.../*_mapping.json exist.

    pip install valentine pandas
    python benchmarks/valentine_matching.py <datasets-root> [per_category=12] [seed=1]
"""
from __future__ import annotations

import glob
import json
import os
import random
import sys
import time

import pandas as pd
from valentine import valentine_match
from valentine.algorithms import Coma, Cupid, DistributionBased, SimilarityFlooding

from ofunnel import key_similarity, profile, similarity

ROOT = sys.argv[1] if len(sys.argv) > 1 else "Valentine-datasets"
PER_CAT = int(sys.argv[2]) if len(sys.argv) > 2 else 12
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1
MATCHERS = ["O-Funnel names", "O-Funnel fused", "COMA schema", "COMA instance", "Cupid", "DistBased", "SimFlood"]


def instances():
    out = []
    for m in glob.glob(os.path.join(ROOT, "**", "*_mapping.json"), recursive=True):
        if "MACOSX" in m:
            continue
        base = m[:-len("_mapping.json")]
        if os.path.exists(base + "_source.csv") and os.path.exists(base + "_target.csv"):
            out.append((os.path.relpath(m, ROOT).split(os.sep)[0], m))
    return out


def held_out_sample():
    by = {}
    for cat, m in instances():
        by.setdefault(cat, []).append(m)
    dev = set()
    random.seed(0)
    for ms in by.values():
        ms = sorted(ms)
        random.shuffle(ms)
        dev |= set(ms[:12])                           # the development sample: excluded
    random.seed(SEED)
    out = []
    for cat, ms in by.items():
        ms = sorted(m for m in ms if m not in dev)
        random.shuffle(ms)
        out += [(cat, m) for m in ms[:PER_CAT]]
    return out


def load(m):
    base = m[:-len("_mapping.json")]
    kw = dict(nrows=500, dtype=str, keep_default_na=False, on_bad_lines="skip")
    s, t = pd.read_csv(base + "_source.csv", **kw), pd.read_csv(base + "_target.csv", **kw)
    gold = {(x["source_column"], x["target_column"]) for x in json.load(open(m))["matches"]}
    return s, t, gold


def recall_at_gt(scores, gold):
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:len(gold)]
    return sum(1 for pair, _ in ranked if pair in gold), len(gold)


def ofunnel_names(s, t):
    return {(a, b): v for a in s.columns for b in t.columns if (v := key_similarity(a, b)) > 0}


def ofunnel_fused(s, t):
    ps = {c: profile(s[c].tolist()) for c in s.columns}
    pt = {c: profile(t[c].tolist()) for c in t.columns}
    out = {}
    for a in s.columns:
        for b in t.columns:
            name = key_similarity(a, b)
            v = name if name >= 0.9 else 0.6 * name + 0.4 * similarity(ps[a], pt[b])
            if v > 0:
                out[(a, b)] = v
    return out


def main():
    subset = held_out_sample()
    print(f"held-out subset: {len(subset)} instances (seed {SEED}, up to {PER_CAT} per category)\n")
    agg, t0 = {}, time.time()
    for cat, m in subset:
        try:
            s, t, gold = load(m)
        except Exception:
            continue
        if not gold:
            continue
        agg.setdefault(cat, {k: [0, 0] for k in MATCHERS})
        scores = {"O-Funnel names": ofunnel_names(s, t), "O-Funnel fused": ofunnel_fused(s, t)}
        for name, matcher in [("COMA schema", Coma(use_instances=False)), ("COMA instance", Coma(use_instances=True)),
                              ("Cupid", Cupid()), ("DistBased", DistributionBased()), ("SimFlood", SimilarityFlooding())]:
            try:
                res = valentine_match([s, t], matcher, ["source", "target"])
                scores[name] = {(p.source_column, p.target_column): v for p, v in res.items()}
            except Exception:
                scores[name] = {}
        for name in MATCHERS:
            f, n = recall_at_gt(scores[name], gold)
            agg[cat][name][0] += f
            agg[cat][name][1] += n
    print(f"{'category':10} " + " ".join(f"{k:>15}" for k in MATCHERS))
    tot = {k: [0, 0] for k in MATCHERS}
    for cat in sorted(agg):
        cells = []
        for k in MATCHERS:
            f, n = agg[cat][k]
            tot[k] = [tot[k][0] + f, tot[k][1] + n]
            cells.append(f"{f / n if n else 0:15.2f}")
        print(f"{cat:10} " + " ".join(cells))
    print(f"{'overall':10} " + " ".join(f"{tot[k][0] / tot[k][1] if tot[k][1] else 0:15.2f}" for k in MATCHERS))
    print(f"\n{len(subset)} instances in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
