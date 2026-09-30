"""The unified language layer: the universal sub-shapes every format passes through.

An adapter produces a tree still shaped like its source. ``normalize`` runs each node through the closed set
of sub-shapes so the tree afterwards speaks one language: every node is a VALUE, RECORD, COLLECTION, TEXT, or
ANNOTATION, and nothing downstream needs the source dialect. The source construct is not thrown away, it is
recorded in ``origin`` (e.g. "xml.attribute", "json.array", "csv.row"), so the normalization is lossless: it
adds a canonical classification, it never drops a node.

Mapping (the series of sub-shapes):

    XML element with fields  -> RECORD        JSON object -> RECORD        CSV row   -> RECORD
    XML repeated siblings    -> RECORD*       JSON array  -> COLLECTION    CSV table -> COLLECTION
    XML leaf element / attr  -> VALUE         JSON scalar -> VALUE (typed) CSV cell  -> VALUE
    XML #text / #tail        -> TEXT          text "k: v" -> RECORD/VALUE  text line -> VALUE / TEXT
    XML comment / PI         -> ANNOTATION

    * XML cannot say whether repeated <b> siblings are a list or a record; the honest first-half choice is a
      RECORD with repeated keys. Re-reading that as a COLLECTION is a step-two (semantic) decision.
"""
from __future__ import annotations

from .model import (ANNOTATION, COLLECTION, GROUP, INDEXED, RECORD, SCALAR, STRING, TEXT, VALUE, Node)

_ORIGIN = {
    ("xml", "element"): "xml.element", ("xml", "attribute"): "xml.attribute", ("xml", "text"): "xml.text",
    ("xml", "comment"): "xml.comment", ("xml", "pi"): "xml.pi",
    ("csv", "element"): "csv.cell", ("text", "line"): "text.line", ("text", "text"): "text.blank",
}


def _origin(node: Node, fmt: str) -> str:
    if fmt == "json":
        if node.kind == SCALAR:
            return "json.scalar"
        return "json.array" if node.container == "list" else "json.object"
    if fmt == "csv":
        if node.kind == SCALAR:
            return "csv.cell"
        return "csv.table" if node.container == "list" or all(c.key_source == INDEXED for c in node.children) else "csv.row"
    if fmt == "text":
        if node.kind == GROUP:
            return "text.doc" if node.key == "$doc" else "text.block"
        return _ORIGIN.get(("text", node.role), "text.line")
    if fmt == "html":
        if node.role == "attribute":
            return "html.attribute"
        if node.role == "text":
            return "html.text"
        return "html.element"
    return _ORIGIN.get((fmt, node.role), f"{fmt}.{node.role}")


def _construct(node: Node) -> str:
    if node.role in ("comment", "pi"):
        return ANNOTATION
    if node.role == "text":
        return TEXT
    if node.kind == SCALAR:
        return VALUE
    if node.container == "list":
        return COLLECTION
    if node.container == "map":
        return RECORD
    # undeclared group (XML, CSV, text): indexed children -> a sequence, named children -> an entity
    kids = [c for c in node.children if c.role not in ("text",)]
    return COLLECTION if kids and all(c.key_source == INDEXED for c in kids) else RECORD


def normalize(node: Node, fmt: str) -> Node:
    """Classify every node into the unified sub-shape vocabulary, in place. Lossless: only sets construct /
    origin / vtype, never removes anything. Returns the same node for convenience."""
    node.construct = _construct(node)
    node.origin = _origin(node, fmt)
    if node.construct == VALUE and node.vtype is None:
        node.vtype = STRING                       # XML / CSV / text values are untyped text until a schema types them
    for c in node.children:
        normalize(c, fmt)
    return node


# ---- queries in the unified language (format-blind) --------------------------------------------
def by_construct(node: Node, *constructs: str) -> list[Node]:
    want = set(constructs)
    return [n for n in node.walk() if n.construct in want]


def records(node: Node) -> list[Node]:
    return by_construct(node, RECORD)


def collections(node: Node) -> list[Node]:
    return by_construct(node, COLLECTION)


def fields(record: Node) -> list[Node]:
    """The named fields of a record: its children that carry data (attributes and elements), not prose or
    annotations -- the (key -> value/subtree) pairs."""
    return [c for c in record.children if c.construct not in (ANNOTATION, TEXT)]
