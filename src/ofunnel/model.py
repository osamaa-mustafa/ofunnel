"""The universal structural representation: a keyed node.

Everything the world presents as information reduces to a recursive key -> value: a node is either a
**scalar** (a value) or a **group** (ordered children), and every child edge carries a **key** whose
``key_source`` records how we know it:

- ``named``   the source stated the key (an XML tag, a JSON field, a CSV header)
- ``indexed`` the source gave no name, so the key is position (a list index, an unlabeled line)
- ``inferred`` we derived the key from the content (the label before a colon in free text)

Leaves keep their raw content, so the tree is lossless; an inferred key is an annotation laid on top of
the raw value, never a replacement for it. Every node may carry a provenance ``span`` back into the source.
This is the one shape the format adapters (``universal.adapters``) all produce and the mapping layer
(``universal.query``) all reads, so nothing downstream depends on the original format.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

NAMED, INDEXED, INFERRED = "named", "indexed", "inferred"
SCALAR, GROUP = "scalar", "group"

# The unified language: the closed set of sub-shapes every format's constructs normalize into. After
# normalization a consumer sees only these, never the source dialect (the source construct is kept in `origin`).
VALUE = "value"            # a typed atom (leaf); its type is in `vtype`
RECORD = "record"          # a group of named fields (an entity): XML element, JSON object, CSV row, labeled text block
COLLECTION = "collection"  # an ordered sequence of items: JSON array, CSV table, repeated siblings, text lines
TEXT = "text"              # human prose / mixed inline content: XML #text and #tail
ANNOTATION = "annotation"  # metadata, not payload: XML comment / processing instruction
CONSTRUCTS = (VALUE, RECORD, COLLECTION, TEXT, ANNOTATION)

# value types (the vocabulary VALUE.vtype draws from). XML/CSV/text values are untyped text = "string"
# until a schema says otherwise; JSON carries real types.
STRING, NUMBER, BOOLEAN, NULL = "string", "number", "boolean", "null"


@dataclass
class Node:
    key: object                       # str (a name) or int (a position)
    key_source: str                   # NAMED | INDEXED | INFERRED
    kind: str                         # SCALAR | GROUP
    value: str | None = None          # raw scalar content (lossless)
    children: list["Node"] = field(default_factory=list)
    role: str = "element"             # element | attribute | text | comment | pi | line  (source-side detail)
    span: tuple[int, int] | None = None
    note: str | None = None           # e.g. an inferred (key, value) split kept as an annotation
    container: str | None = None      # for a group: "map" | "list" | None -- distinguishes empty {} from []
    # ---- the unified language (set by language.normalize; the source dialect stays only in `origin`) ----
    construct: str | None = None      # VALUE | RECORD | COLLECTION | TEXT | ANNOTATION
    vtype: str | None = None          # for a VALUE: STRING | NUMBER | BOOLEAN | NULL
    origin: str | None = None         # provenance of the source construct, e.g. "xml.element", "json.object"

    # ---- construction helpers -------------------------------------------------------------
    @classmethod
    def scalar(cls, key, value, *, key_source=NAMED, role="element", span=None, note=None) -> "Node":
        return cls(key=key, key_source=key_source, kind=SCALAR, value=value, role=role, span=span, note=note)

    @classmethod
    def group(cls, key, *, key_source=NAMED, role="element") -> "Node":
        return cls(key=key, key_source=key_source, kind=GROUP, role=role)

    def add(self, child: "Node") -> "Node":
        self.children.append(child)
        return child

    # ---- traversal ------------------------------------------------------------------------
    def walk(self) -> Iterator["Node"]:
        """Every node in document order, self first."""
        yield self
        for c in self.children:
            yield from c.walk()

    def leaves(self) -> Iterator["Node"]:
        for n in self.walk():
            if n.kind == SCALAR:
                yield n

    def render(self, _indent: int = 0, _out: list | None = None) -> str:
        out = [] if _out is None else _out
        pad = "  " * _indent
        k = f"{self.key!r}[{self.key_source[:3]}]"
        if self.kind == SCALAR:
            v = (self.value or "").replace("\n", "\\n")
            v = v if len(v) <= 48 else v[:48] + "..."
            extra = f" ({self.role})" if self.role != "element" else ""
            note = f" ~{self.note}" if self.note else ""
            out.append(f"{pad}{k} = {v!r}{extra}{note}")
        else:
            out.append(f"{pad}{k}:")
            for c in self.children:
                c.render(_indent + 1, out)
        return "\n".join(out) if _indent == 0 else ""
