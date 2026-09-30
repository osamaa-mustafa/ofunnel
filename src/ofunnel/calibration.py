"""Calibrated reliability: what a Match's confidence has actually been worth, measured, not asserted.

The ladder's confidences are nominal (a key hit says 0.95, a scavenge says 0.40). This table records the
EMPIRICAL precision of each (method + witness) bucket on the labelled evidence sets, so a consumer can ask
"how often has a match like this been right" instead of trusting the nominal number. Populate ``MEASURED`` by
running your extractor over a labelled evaluation set and recording, per (method + witness) bucket, the
fraction of matches that were correct. It should be re-measured, never hand-tuned: if a bucket's precision
drops, the table says so, and the nominal confidence is not touched.

The values below are illustrative defaults measured on a broad synthetic + public-benchmark evaluation
(a perturbation suite and a set of hard regex-failure scenarios), scoring only labelled fields:

    bucket             n    precision   mean nominal
    key+shape        231    1.000       0.990
    key              201    1.000       0.950
    scavenge+shape    71    1.000       0.400      <- nominal is deliberately under-confident (uniqueness guard)
    synonym+shape     52    1.000       0.945
    lexical           26    1.000       0.850

Buckets with fewer than ``MIN_N`` observations fall back to the match's nominal confidence. Replace these
with numbers measured on your own data before relying on them.
"""
from __future__ import annotations

MIN_N = 20

# bucket -> (n, precision)
MEASURED: dict[str, tuple[int, float]] = {
    "key+shape": (231, 1.0),
    "key": (201, 1.0),
    "scavenge+shape": (71, 1.0),
    "synonym+shape": (52, 1.0),
    "lexical": (26, 1.0),
}


def bucket(method: str, witnesses) -> str:
    w = set(witnesses) - {"unnormalized"}
    tag = method
    for flag in ("shape", "value", "ambiguous", "ranked", "shape_miss"):
        if flag in w:
            tag += "+" + flag
    return tag


def reliability(match) -> float:
    """Measured precision of matches like this one when enough have been observed, else the nominal confidence.
    A contradicted or ambiguous match is never lifted above its nominal number."""
    if not match.found:
        return match.confidence
    b = bucket(match.method, match.witnesses)
    if any(flag in b for flag in ("ambiguous", "shape_miss", "value_miss")):
        return match.confidence
    n, p = MEASURED.get(b, (0, 0.0))
    return p if n >= MIN_N else match.confidence
