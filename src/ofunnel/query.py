"""Format-blind query primitives over the universal tree: the seam the mapping layer (the second half)
builds on. Each returns nodes grounded in the captured tree, so every mapping cites a real item and is
verifiable. Nothing here interprets meaning; it only locates candidates by key, by value shape, or by path.
"""
from __future__ import annotations

import re
from typing import Iterable

from .model import SCALAR, Node


def _norm(k) -> str:
    return str(k).lower().replace("_", "").replace(" ", "").replace("-", "")


def by_key(node: Node, *names: str) -> list[Node]:
    """Every node whose key matches one of ``names`` (case- and separator-insensitive)."""
    want = {_norm(n) for n in names}
    return [n for n in node.walk() if _norm(n.key) in want]


def by_value_shape(node: Node, pattern: str | re.Pattern) -> list[Node]:
    """Every scalar whose value matches the pattern -- finds a field even under an unknown key."""
    rx = re.compile(pattern) if isinstance(pattern, str) else pattern
    return [n for n in node.leaves() if n.value and rx.search(n.value)]


def by_path(node: Node, *keys) -> list[Node]:
    """Descend a key path, e.g. by_path(root, 'AGENCY', 'CODE'); '*' matches any single level."""
    frontier = [node]
    for k in keys:
        nxt = []
        for f in frontier:
            for c in f.children:
                if k == "*" or _norm(c.key) == _norm(k):
                    nxt.append(c)
        frontier = nxt
    return frontier


def residue(node: Node, claimed: Iterable[Node]) -> list[Node]:
    """Every captured leaf that no mapper claimed -- the discovery signal. A leaf is either mapped or here;
    it can never silently vanish."""
    seen = {id(n) for n in claimed}
    return [n for n in node.leaves() if id(n) not in seen and n.role not in ("text",)]
