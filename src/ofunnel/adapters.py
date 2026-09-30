"""Format adapters: each turns one format family into the universal ``Node`` tree. This is the ONLY
per-format code in the engine; everything after it is format-blind.

Two guarantee classes (see ``ofunnel.oracle``):
- Declared formats (xml, json, csv): the format states its own structure, so capture is lossless and
  the oracle is a reconstruction / canonical round-trip.
- Implicit formats (text_kv): the format gives lines, not a tree, so every line (with its newline) is a
  lossless leaf tiling the source, and any label -> value split is recorded as an INFERRED annotation on
  top of the raw line. The oracle is byte-perfect coverage.
"""
from __future__ import annotations

import csv as _csv
import io
import json as _json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from .model import GROUP, INDEXED, INFERRED, NAMED, SCALAR, Node

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

_KV = re.compile(r"^\s*(?P<key>[A-Za-z][\w .\-/&]*?)\s*[:=]\s*(?P<val>.*\S)?\s*$")


def from_xml(raw: bytes) -> Node:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))
    root = ET.fromstring(raw, parser=parser)

    def conv(el, key) -> Node:
        if el.tag is ET.PI:                                       # processing instruction
            return Node.scalar("#pi", el.text or "", role="pi")
        if not isinstance(el.tag, str):                          # comment
            return Node.scalar("#comment", el.text or "", role="comment")
        kids = list(el)
        if not kids and not el.attrib:                            # leaf element -> a scalar pair
            return Node.scalar(key, el.text or "")
        n = Node.group(key)
        for ak, av in el.attrib.items():
            n.add(Node.scalar(ak, av, role="attribute"))
        if el.text and el.text.strip():
            n.add(Node.scalar("#text", el.text, role="text"))
        for c in kids:
            n.add(conv(c, c.tag if isinstance(c.tag, str) else "#comment"))
            if c.tail and c.tail.strip():
                n.add(Node.scalar("#tail", c.tail, role="text"))
        return n

    return conv(root, root.tag)


def from_json(raw: bytes) -> Node:
    def conv(v, key, ksrc) -> Node:
        if isinstance(v, _Obj):                            # object: ordered pairs, keeps duplicate & empty keys
            n = Node.group(key, key_source=ksrc)
            n.container = "map"
            for k, val in v:
                n.add(conv(val, k, NAMED))
            return n
        if isinstance(v, list):
            n = Node.group(key, key_source=ksrc)
            n.container = "list"
            for i, val in enumerate(v):
                n.add(conv(val, i, INDEXED))
            return n
        n = Node.scalar(key, None if v is None else _jval(v), key_source=ksrc)
        n.vtype = "null" if v is None else "boolean" if isinstance(v, bool) else "number" if isinstance(v, (int, float)) else "string"
        return n

    return conv(_json.loads(raw, object_pairs_hook=_Obj), "$", NAMED)


def _jval(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"                 # JSON spelling, not Python's True/False
    return str(v)


class _Obj(list):
    """Marks a value that came from a JSON object (vs an array), so an empty {} stays distinct from []."""


def from_csv(raw: bytes, *, encoding: str = "utf-8") -> Node:
    rows = list(_csv.reader(io.StringIO(raw.decode(encoding))))
    header = rows[0] if rows else []
    table = Node.group("$table")
    for ri, row in enumerate(rows[1:], start=1):
        rn = table.add(Node.group(ri, key_source=INDEXED))
        for ci, cell in enumerate(row):
            named = ci < len(header)
            rn.add(Node.scalar(header[ci] if named else ci, cell, key_source=NAMED if named else INDEXED))
    return table


def from_text_kv(raw: bytes, *, encoding: str = "utf-8") -> Node:
    text = raw.decode(encoding)
    root = Node.group("$doc")
    pos = 0
    block = None
    bi = 0
    for line in text.splitlines(keepends=True):
        start = pos
        pos += len(line)
        if not line.strip():
            block = None
            root.add(Node.scalar("#blank", line, role="text", span=(start, pos)))
            continue
        if block is None:
            bi += 1
            block = root.add(Node.group(bi, key_source=INDEXED, role="line"))
        m = _KV.match(line)
        if m and m.group("key"):
            block.add(Node.scalar(m.group("key").strip(), line, key_source=INFERRED, role="line",
                                  span=(start, pos), note=f"value={m.group('val')!r}"))
        else:
            block.add(Node.scalar(len(block.children), line, key_source=INDEXED, role="line", span=(start, pos)))
    return root


class _DOM(HTMLParser):
    """Tolerant HTML -> Node tree. Real HTML has unclosed tags, void elements and tag soup, so end tags pop up
    to the matching open tag (browser-like) and never fail. A leaf element with only text and no attributes
    becomes a scalar (like from_xml); everything else is a group with attribute + #text + child nodes."""
    def __init__(self):
        super().__init__(convert_charrefs=True)         # decode entities in text (content-lossless at char level)
        self.root = Node.group("#document")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = Node.group(tag)
        for k, v in attrs:
            n.add(Node.scalar(k, v if v is not None else "", role="attribute"))
        self.stack[-1].add(n)
        if tag not in _VOID:
            self.stack.append(n)

    def handle_startendtag(self, tag, attrs):
        n = Node.group(tag)
        for k, v in attrs:
            n.add(Node.scalar(k, v if v is not None else "", role="attribute"))
        self.stack[-1].add(n)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):     # pop up to the matching open tag; ignore stray closers
            if self.stack[i].key == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip():
            self.stack[-1].add(Node.scalar("#text", data, role="text"))


_SEMANTIC_ATTRS = ("itemprop", "id", "class", "name", "data-field")   # HTML's de-facto field names, in priority order


def from_html(raw: bytes, *, encoding: str = "utf-8") -> Node:
    p = _DOM()
    p.feed(raw.decode(encoding, "replace"))
    p.close()

    def collapse(n: Node) -> Node:
        if n.kind == GROUP and n.key != "#document":
            attrs = [c for c in n.children if c.role == "attribute"]
            texts = [c for c in n.children if c.role == "text"]
            elems = [c for c in n.children if c.role not in ("attribute", "text")]
            if not elems and len(texts) == 1:
                functional = [a for a in attrs if a.key not in _SEMANTIC_ATTRS]
                if not functional:
                    # a pure value element: key it by its semantic attribute (class/id/itemprop = the field name),
                    # else by tag; the tag is kept in note so nothing about provenance is lost
                    key, ks = n.key, NAMED
                    for name in _SEMANTIC_ATTRS:
                        a = next((x for x in attrs if x.key == name and x.value), None)
                        if a:
                            key, ks = a.value.split()[0], INFERRED
                            break
                    return Node.scalar(key, texts[0].value, key_source=ks, note=f"tag={n.key}")
        n.children = [collapse(c) for c in n.children]
        return n

    return collapse(p.root)


ADAPTERS = {"xml": from_xml, "json": from_json, "csv": from_csv, "text": from_text_kv, "html": from_html}


def sniff(raw: bytes) -> str:
    """Best-effort format guess from the leading bytes. csv is not sniffed (pass fmt='csv')."""
    head = raw.lstrip()[:200].lower()
    if head[:1] == b"<":
        if head.startswith(b"<!doctype html") or b"<html" in head or b"<head" in head or b"<body" in head:
            return "html"
        return "xml"
    if head[:1] in (b"{", b"["):
        return "json"
    return "text"


def capture(raw: bytes, fmt: str | None = None) -> tuple[Node, str]:
    """Turn any supported document into the unified tree, normalized into the sub-shape language. Returns
    (node, fmt). The returned tree speaks only VALUE / RECORD / COLLECTION / TEXT / ANNOTATION; the source
    construct of each node is kept in ``node.origin``."""
    from .language import normalize
    fmt = fmt or sniff(raw)
    if fmt not in ADAPTERS:
        raise ValueError(f"no adapter for format {fmt!r}")
    return normalize(ADAPTERS[fmt](raw), fmt), fmt
