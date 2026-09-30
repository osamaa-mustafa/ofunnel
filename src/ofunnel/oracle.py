"""Completeness oracles: prove a capture kept everything, the way appropriate to the format.

The oracle is the whole point of the engine. Generic capture without a completeness check is just a bigger
version of the silent-drop trap. Every capture is gated: if it cannot reconstruct its source, the run fails
loudly instead of quietly losing data.

- xml:  compare the pre-order atom sequence of the captured tree to an independent parse of the source
        (element tags and attributes by namespace URI + local name, text, comments, PIs). Prefix strings and
        inter-tag indentation are cosmetic and ignored on both sides; nothing is re-serialized.
- json: rebuild the Python value (using the container tag, so empty {} != []) and compare to the source.
- csv:  rebuild the rows and compare to the parsed source rows.
- text: byte-perfect coverage -- concatenating every leaf span in order reconstructs the source exactly.
"""
from __future__ import annotations

import csv as _csv
import io
import json as _json
import re
import xml.etree.ElementTree as ET
from collections import Counter

from .model import GROUP, INDEXED, SCALAR, Node
from .adapters import _Obj


def _atoms_et(el, depth: int, out: list) -> None:
    if el.tag is ET.Comment:
        out.append((depth, "co", el.text or "")); return
    if el.tag is ET.PI:
        out.append((depth, "pi", el.text or "")); return
    out.append((depth, "el", el.tag))
    for k in sorted(el.attrib):
        out.append((depth, "at", k, el.attrib[k]))
    if el.text and el.text.strip():
        out.append((depth, "tx", el.text))
    for c in el:
        _atoms_et(c, depth + 1, out)
        if c.tail and c.tail.strip():
            out.append((depth, "tx", c.tail))


def _atoms_ukt(n: Node, depth: int, out: list) -> None:
    if n.role == "comment":
        out.append((depth, "co", n.value or "")); return
    if n.role == "pi":
        out.append((depth, "pi", n.value or "")); return
    out.append((depth, "el", n.key))
    if n.kind == SCALAR:
        if n.value and n.value.strip():
            out.append((depth, "tx", n.value))
        return
    for c in sorted([c for c in n.children if c.role == "attribute"], key=lambda c: str(c.key)):
        out.append((depth, "at", c.key, c.value))
    for c in n.children:
        if c.role == "attribute":
            continue
        if c.role == "text":
            if c.value and c.value.strip():
                out.append((depth, "tx", c.value))
        else:
            _atoms_ukt(c, depth + 1, out)


def check_xml(raw: bytes, node: Node) -> bool:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    src, cap = [], []
    _atoms_et(ET.fromstring(raw, parser=parser), 0, src)
    _atoms_ukt(node, 0, cap)
    return src == cap


def _typed(n: Node):
    """Reconstruct the real JSON value from a captured VALUE, using its type (so 1 != "1", true != "true")."""
    if n.vtype == "null" or n.value is None:
        return None
    if n.vtype == "boolean":
        return n.value == "true"
    if n.vtype == "number":
        v = n.value
        return float(v) if any(c in v for c in ".eE") else int(v)
    return n.value


def check_json(raw: bytes, node: Node) -> bool:
    def build(n):
        if n.kind == SCALAR:
            return _typed(n)
        if n.container == "list":
            return [build(c) for c in n.children]
        return {str(c.key): build(c) for c in n.children}

    def norm(v):
        if isinstance(v, _Obj):
            return {str(k): norm(x) for k, x in v}
        if isinstance(v, list):
            return [norm(x) for x in v]
        return v

    return build(node) == norm(_json.loads(raw, object_pairs_hook=_Obj))


def check_csv(raw: bytes, node: Node, *, encoding: str = "utf-8") -> bool:
    rows = list(_csv.reader(io.StringIO(raw.decode(encoding))))
    rebuilt = [[c.value for c in rn.children] for rn in node.children]
    return rebuilt == rows[1:]


def check_coverage(raw: bytes, node: Node, *, encoding: str = "utf-8") -> bool:
    text = raw.decode(encoding)
    spans = sorted(n.span for n in node.leaves() if n.span is not None)
    return "".join(text[s:e] for s, e in spans) == text


_TAG = re.compile(r"<!--.*?-->|<[^>]+>", re.S)


def check_html(raw: bytes, node: Node, *, encoding: str = "utf-8") -> bool:
    """Content-coverage: every visible-text token in the source survives into the tree (HTML is an implicit-
    structure format, so the honest guarantee is content-lossless, not canonical round-trip). No source text
    token is dropped; entities are decoded on both sides."""
    import html as _html
    src = Counter(_html.unescape(_TAG.sub(" ", raw.decode(encoding, "replace"))).split())
    tree = Counter(tok for n in node.leaves() if n.role == "text" and n.value for tok in n.value.split())
    tree += Counter(tok for n in node.leaves() if n.role != "text" and n.value for tok in str(n.value).split())
    return all(tree.get(t, 0) >= c for t, c in src.items())


_CHECKS = {"xml": check_xml, "json": check_json, "csv": check_csv, "text": check_coverage, "html": check_html}


def check_complete(raw: bytes, node: Node, fmt: str) -> bool:
    """True iff the capture provably reconstructs its source. Callers should fail the run on False."""
    fn = _CHECKS.get(fmt)
    if fn is None:
        raise ValueError(f"no oracle for format {fmt!r}")
    return fn(raw, node)
