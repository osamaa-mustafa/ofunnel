"""The requirement language: how a needed data item is declared, written in the unified space's own terms.

Two spaces, two languages. The unified space speaks VALUE / RECORD / COLLECTION / TEXT / ANNOTATION with keys,
types and origins. The input language is the one we control, so it is written in those same terms instead of
as a regex over bytes. A ``Requirement`` says WHAT sub-shape the item is, WHICH keys it may be under, what
TYPE it has, WHERE it sits (containment), what its VALUES look like (shape and/or exemplars), and, as a last
resort confined to prose, what PHRASE announces it.

Resolution is a ladder of rungs, each grounded in a captured node and tagged with how it matched and how sure:

    key           a VALUE whose key is one of the aliases                        0.75 - 0.95 by key_source
    path          a node whose key path ends with the declared containment path  0.90
    shape         a VALUE whose content matches the value shape (name-agnostic)  0.70
    synonym       a key that is a registered surface form of the concept         0.90 exact / <= 0.85 fuzzy
    lexical       a key that is the same words spelled differently               0.55 + 0.30 * similarity
    neighborhood  the sibling that fits, in a RECORD holding the declared peers  0.65 (partial peers lower)
    prose         the phrase, searched ONLY inside prose-bearing nodes           0.50
    absent        nothing matched: a provable, reported outcome, with a reason   1.00 (value None)

Rungs are FUSED, not first-wins: a key / path hit is a fast path (it is the cheap, pristine case), but below
it every rung is gathered and candidates that the same node reaches by several independent rungs merge, each
extra agreeing witness (shape, value profile, neighborhood, ...) adding a bounded amount; a contradicted
declaration (a declared shape or value profile the candidate's value fails) subtracts. So the best-evidenced
node wins, not the first rung that happened to fire.

``resolve_all`` resolves a set of requirements together and returns the matches, the absent list, and the
residue (every captured leaf no requirement claimed) -- so an item is mapped, reported absent, or held.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from functools import lru_cache
from typing import Any, Callable, Iterable

from .model import ANNOTATION, GROUP, INFERRED, NAMED, RECORD, SCALAR, STRING, TEXT, VALUE, Node
from .profile import Profile, profile as _profile_of, value_witness

_PROSE_ORIGINS = ("xml.text", "text.line", "text.block", "html.text")
_MARKUP_TEXT = ("xml.text", "html.text")         # element text in markup formats (not free text-file lines)

# a fused candidate: (confidence, document order, Match)
_Cand = tuple[float, int, "Match"]

# fusion constants (bounded, documented): an extra independent agreeing witness adds AGREE; a contradicted
# declaration multiplies by CONTRA; non-key rungs never exceed FUSE_CAP so a key hit still outranks them
AGREE = 0.04
CONTRA = 0.8
FUSE_CAP = 0.95
VALUE_OK = 0.8                                   # value-profile witness at/above this = agreement
VALUE_MISS = 0.3                                 # below this = contradiction


@lru_cache(maxsize=65536)
def _norm(k) -> str:
    return str(k).lower().replace("_", "").replace(" ", "").replace("-", "")


# ---------------------------------------------------------------------------------------------
# value normalizers (the "read the value" part of a requirement)
# ---------------------------------------------------------------------------------------------
_BOOL = {"yes": True, "no": False, "true": True, "false": False, "y": True, "n": False, "1": True, "0": False}
_MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                        "september", "october", "november", "december"], start=1)}
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_US = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_LONG = re.compile(r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(\d{4})\b", re.I)


def as_bool(s: str | None):
    return _BOOL.get((s or "").strip().lower())


def as_number(s: str | None):
    t = (s or "").strip().replace(",", "")
    try:
        return float(t) if any(c in t for c in ".eE") else int(t)
    except ValueError:
        return None


def as_date(s: str | None):
    t = s or ""
    m = _ISO.search(t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    m = _LONG.search(t)
    if m:
        try:
            return date(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
        except ValueError:
            return None
    m = _US.search(t)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
    return None


def as_text(s: str | None):
    return (s or "").strip() or None


NORMALIZERS = {"bool": as_bool, "number": as_number, "date": as_date, "text": as_text}


# ---------------------------------------------------------------------------------------------
# the requirement and its result
# ---------------------------------------------------------------------------------------------
@dataclass
class Requirement:
    name: str
    construct: str = VALUE                               # which sub-shape the item is
    keys: tuple[str, ...] = ()                            # key aliases (case / separator insensitive)
    vtype: tuple[str, ...] | None = None                  # allowed value types, None = any
    path: tuple[str, ...] | None = None                   # containment: the key path must END with these keys
    within: str | None = None                             # must sit under an ancestor with this key (exact or lexical)
    shape: str | re.Pattern | None = None                 # value-shape regex over VALUE content (name-agnostic)
    prose: str | re.Pattern | None = None                 # phrase allowed ONLY in prose-bearing nodes
    prose_value: Any = None                               # value to assign on a prose hit (default: matched text)
    normalize: str | Callable[[str | None], Any] | None = None   # "bool" | "number" | "date" | "text" | callable
    extract: bool = False                                 # value = the shape's matched span (group 1 or 0), not the whole node value
    concept: str | None = None                           # synonym rung: a concept id whose surface terms are supplied via `synonyms`
    fuzzy: float | None = 0.6                             # lexical rung: min key similarity (None disables)
    neighbors: tuple[str, ...] = ()                       # neighborhood rung: sibling keys that share the RECORD
    exemplars: tuple[str, ...] = ()                       # example values: derives a value profile (a witness, not a locator)
    many: bool = False                                    # return every match instead of the best one
    required: bool = True

    def __post_init__(self):
        self._keys = {_norm(k) for k in self.keys}
        self._neighbors = tuple(_norm(k) for k in self.neighbors)
        self._path = tuple(_norm(p) for p in self.path) if self.path else None
        self._within = _norm(self.within) if self.within else None
        self._shape = re.compile(self.shape) if isinstance(self.shape, str) else self.shape
        self._prose = re.compile(self.prose, re.I) if isinstance(self.prose, str) else self.prose
        self._norm = NORMALIZERS[self.normalize] if isinstance(self.normalize, str) else self.normalize
        self._profile: Profile | None = _profile_of(self.exemplars) if self.exemplars else None


@dataclass
class Match:
    requirement: str
    value: Any
    raw: str | None
    method: str                                           # key | path | shape | synonym | lexical | neighborhood | prose | scavenge | absent
    confidence: float
    witnesses: tuple[str, ...]
    node: Node | None
    key_path: tuple = ()
    origin: str | None = None
    reason: str | None = None                             # for absent: WHY (no_candidate | shape_rejected:n | ambiguous:k1,k2 | ...)

    @property
    def found(self) -> bool:
        return self.method != "absent"


@dataclass
class ResolveReport:
    matches: dict[str, list[Match]] = field(default_factory=dict)
    absent: list[str] = field(default_factory=list)
    residue: list[Node] = field(default_factory=list)     # captured leaves no requirement claimed
    reasons: dict[str, str] = field(default_factory=dict)  # absent requirement -> reason

    def one(self, name: str) -> Match | None:
        ms = self.matches.get(name) or []
        return ms[0] if ms else None


# ---------------------------------------------------------------------------------------------
# lexical similarity of keys (domain-free): tokens, abbreviations, stems, initialisms
# ---------------------------------------------------------------------------------------------
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_STOP = {"of", "the", "a", "an", "and", "or"}
_VOWELS = str.maketrans("", "", "aeiou")

# generic token equivalences no spelling method can derive (abbreviation conventions, not domain vocabulary)
_TOKEN_GROUPS = [
    {"id", "identifier", "ident"}, {"num", "number", "no", "nbr", "nr"}, {"dt", "date"}, {"desc", "description"},
    {"amt", "amount"}, {"qty", "quantity"}, {"nm", "name"}, {"addr", "address"}, {"tel", "phone", "telephone"},
    {"yr", "year"}, {"cnt", "count"}, {"pct", "percent", "percentage"}, {"ref", "reference"}, {"cat", "category"},
    {"rcvd", "received", "recvd"}, {"pub", "published", "publication"}, {"eff", "effective"}, {"org", "organization", "organisation"},
    {"dept", "department"}, {"govt", "government"}, {"msg", "message"}, {"src", "source"}, {"dest", "destination"},
    {"max", "maximum"}, {"min", "minimum"}, {"avg", "average", "mean"}, {"tot", "total"}, {"val", "value"},
    {"txt", "text"}, {"lang", "language"}, {"co", "company"}, {"st", "state", "street"}, {"zip", "postal", "postcode"},
    {"seq", "sequence"}, {"ver", "version"}, {"len", "length"}, {"lat", "latitude"}, {"lon", "lng", "longitude"},
]
_TOKEN_GROUP = {t: i for i, g in enumerate(_TOKEN_GROUPS) for t in g}


def key_tokens(k) -> frozenset:
    s = _CAMEL.sub(" ", str(k))
    return frozenset(t.lower() for t in _SPLIT.split(s) if t and t.lower() not in _STOP)


def _stem(t: str) -> str:
    for suf in ("ies", "ing", "ed", "es", "s"):
        if t.endswith(suf) and len(t) - len(suf) >= 3:
            return t[:-len(suf)] + ("y" if suf == "ies" else "")
    return t


@lru_cache(maxsize=65536)
def _tok_eq(a: str, b: str) -> float:
    """1.0 identical; 0.9 an abbreviation / stem / prefix / registered equivalent; 0.0 otherwise."""
    if a == b:
        return 1.0
    ga, gb = _TOKEN_GROUP.get(a), _TOKEN_GROUP.get(b)
    if ga is not None and ga == gb:
        return 0.9
    if _stem(a) == _stem(b):
        return 0.9
    s, l = (a, b) if len(a) <= len(b) else (b, a)
    if len(s) >= 3 and l.startswith(s):
        return 0.9
    ds, dl = s.translate(_VOWELS), l.translate(_VOWELS)
    if len(ds) >= 3 and s == ds and ds == dl and s != l:
        return 0.9                                             # the short side is itself a consonant abbreviation (rcvd ~ received)
    return 0.0


def _soft_jaccard(ta: frozenset, tb: frozenset) -> float:
    if not ta or not tb:
        return 0.0
    used = set()
    score = 0.0
    for x in ta:
        best, pick = 0.0, None
        for y in tb:
            if y in used:
                continue
            e = _tok_eq(x, y)
            if e > best:
                best, pick = e, y
                if e == 1.0:
                    break
        if pick is not None and best > 0:
            used.add(pick)
            score += best
    return score / (len(ta) + len(tb) - len(used))


def _initialism(a: str, ta: frozenset, tb: frozenset) -> float:
    """'pin' vs 'personal identification number': one side is a single token equal to the initials of the other."""
    if len(ta) == 1 and len(tb) >= 3:
        (tok,) = tuple(ta)
        if len(tok) == len(tb) and len(tok) >= 3:
            ordered = [t.lower() for t in _SPLIT.split(_CAMEL.sub(" ", str(a))) if t and t.lower() not in _STOP]
            if "".join(t[0] for t in ordered) == tok:
                return 0.8
    return 0.0


@lru_cache(maxsize=65536)
def _key_similarity(a: str, b: str) -> float:
    if _norm(a) == _norm(b):
        return 1.0
    ta, tb = key_tokens(a), key_tokens(b)
    jac = _soft_jaccard(ta, tb)
    chr_ = SequenceMatcher(None, _norm(a), _norm(b)).ratio()
    ini = max(_initialism(b, ta, tb), _initialism(a, tb, ta))
    return round(max(jac, chr_ * 0.9, ini), 3)


def key_similarity(a, b) -> float:
    """0..1: soft token-set overlap (order-free, abbreviation / stem / prefix aware: RECEIVED_DATE ~ date_received,
    RECEIVED_DT ~ date_received, cfr_ref ~ cfrReference) blended with character similarity (small typos), plus
    initialism detection (pin ~ personal identification number). Exact normalized equality is 1.0. Memoized."""
    return _key_similarity(str(a), str(b))


def _best_alias_sim(key, aliases: Iterable[str]) -> float:
    return max((key_similarity(key, a) for a in aliases), default=0.0)


def _key_conf(n: Node) -> float:
    if n.key_source == NAMED:
        return 0.9 if n.role == "attribute" else 0.95
    if n.key_source == INFERRED:
        return 0.75
    return 0.6


# ---------------------------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------------------------
def _walk_with_path(node: Node, path=()):
    yield node, path + (node.key,)
    for c in node.children:
        yield from _walk_with_path(c, path + (node.key,))


# ---- value-bearing elements -----------------------------------------------------------------------------
# A VALUE leaf carries its value directly. Markup formats also have elements that carry their own text while
# not being leaves: XML/HTML *simple content* (attributes + text, e.g. <id type="doi">10.1/x</id>) and *mixed
# content* (text with inline markup, e.g. <title>Effect of <i>X</i> on Y</title>). Capture keeps these as a
# RECORD with attribute and text children (lossless); resolution reads them as values through this view.
def _own_text(n: Node) -> str | None:
    """The text an element carries itself (simple or mixed content), concatenated in document order and
    skipping attributes and annotations; None when the node is not a markup element with its own text."""
    if n.kind != GROUP or n.construct != RECORD:
        return None
    if not any(c.construct == TEXT and c.origin in _MARKUP_TEXT for c in n.children):
        return None
    parts: list[str] = []

    def collect(x: Node) -> None:
        for c in x.children:
            if c.role == "attribute" or c.construct == ANNOTATION:
                continue
            if c.kind == SCALAR:
                parts.append(c.value or "")
            else:
                collect(c)

    collect(n)
    text = "".join(parts)
    return text if text.strip() else None


def value_view(n: Node) -> str | None:
    """The scalar content a node carries: a VALUE's own value, or the text of a simple- or mixed-content
    element. None for records and collections that carry no text of their own."""
    return n.value if n.kind == SCALAR else _own_text(n)


def _fits(n: Node, req: "Requirement") -> bool:
    """Does node n have the sub-shape the requirement asks for? A text-bearing element counts as a VALUE."""
    if n.construct == req.construct:
        return True
    return req.construct == VALUE and _own_text(n) is not None


def _vtype(n: Node) -> str | None:
    if n.kind == SCALAR:
        return n.vtype
    return STRING if _own_text(n) is not None else None


def _raw(n: Node, req: "Requirement") -> str | None:
    """The raw value a node offers to this requirement (text-bearing elements only when a VALUE is asked for)."""
    if n.kind == SCALAR:
        return n.value
    return _own_text(n) if req.construct == VALUE else None


def _value_nodes(tree: Node) -> list[Node]:
    """Every value-bearing node in document order: VALUE leaves (not prose or annotations) and text-bearing
    elements. This is what the residue is made of."""
    out: list[Node] = []

    def walk(n: Node) -> None:
        if n.kind == SCALAR:
            if n.construct not in (ANNOTATION, TEXT) and n.role != "text":
                out.append(n)
            return
        if _own_text(n) is not None:
            out.append(n)
        for c in n.children:
            walk(c)

    walk(tree)
    return out


def _within_ok(req: Requirement, kp: tuple) -> bool:
    if not req._within:
        return True
    anc = kp[:-1]
    if req._within in (_norm(k) for k in anc):
        return True
    thr = max(req.fuzzy or 1.0, 0.8)                           # a lexically-equivalent ancestor key also counts
    return any(key_similarity(k, req.within) >= thr for k in anc)


def _value_of(req: Requirement, n: Node):
    raw = _raw(n, req)
    shape_m = req._shape.search(raw) if (req._shape and raw) else None
    if req.extract and shape_m is not None:
        raw = shape_m.group(1) if shape_m.lastindex else shape_m.group(0)
    value = req._norm(raw) if (req._norm and raw is not None) else raw
    return raw, value, shape_m is not None


def _finish(req: Requirement, n: Node, conf: float, witnesses: tuple, raw, value, *, cap: float = FUSE_CAP) -> tuple[float, tuple]:
    """Apply the witnesses every rung shares: value profile (agree / contradict) and normalization failure."""
    vw = value_witness(raw, req._profile) if (req._profile is not None and raw is not None) else None
    if vw is not None:
        if vw >= VALUE_OK:
            conf, witnesses = min(cap, conf + AGREE), witnesses + ("value",)
        elif vw < VALUE_MISS:
            conf, witnesses = conf * CONTRA, witnesses + ("value_miss",)
    if req._norm and value is None and raw:
        conf, witnesses = conf * 0.6, witnesses + ("unnormalized",)
    return round(conf, 3), witnesses


def _structural(tree: Node, req: Requirement, rej: Counter) -> list[_Cand]:
    """The key / path / shape rung. keys and path LOCATE; shape only locates on its own when nothing structural
    was declared, otherwise it CONFIRMS a located node (so a docket line never matches a document-number
    requirement by shape alone) and a located node whose value FAILS a declared shape is marked contradicted."""
    cands: list[_Cand] = []
    order = 0
    shape_locates = not req._keys and not req._path and not req._neighbors and not req.concept
    for n, kp in _walk_with_path(tree):
        order += 1
        if n.construct == ANNOTATION or not _fits(n, req):
            continue
        if req.vtype and _vtype(n) not in req.vtype:
            rej["vtype"] += 1
            continue
        if not _within_ok(req, kp):
            rej["within"] += 1
            continue
        key_ok = bool(req._keys) and _norm(kp[-1]) in req._keys
        path_ok = bool(req._path) and len(kp) >= len(req._path) and tuple(_norm(k) for k in kp[-len(req._path):]) == req._path
        text = _raw(n, req)
        shape_m = req._shape.search(text) if (req._shape and text) else None
        shape_ok = shape_m is not None
        located = key_ok or path_ok or (shape_ok and shape_locates)
        if not located:
            continue
        witnesses = tuple(w for w, ok in (("key", key_ok), ("path", path_ok), ("shape", shape_ok)) if ok)
        if key_ok:
            method, conf = "key", _key_conf(n)
        elif path_ok:
            method, conf = "path", 0.9
        else:
            method, conf = "shape", 0.7
        if len(witnesses) > 1:
            conf = min(0.99, conf + AGREE * (len(witnesses) - 1))
        if req._shape and text and not shape_ok:
            conf, witnesses = conf * CONTRA, witnesses + ("shape_miss",)          # located, but the declared shape disagrees
        raw = text
        if req.extract and shape_m is not None:
            raw = shape_m.group(1) if shape_m.lastindex else shape_m.group(0)
        value = req._norm(raw) if (req._norm and raw is not None) else raw
        conf, witnesses = _finish(req, n, conf, witnesses, raw, value, cap=0.99)
        cands.append((conf, order, Match(req.name, value, raw, method, conf, witnesses, n, kp, n.origin)))
    cands.sort(key=lambda t: (-t[0], t[1]))
    return cands


def _fuse(groups: list[list[_Cand]]) -> list[_Cand]:
    """Merge candidates that reach the SAME node by different rungs: keep the strongest rung as the method,
    union the witnesses, add AGREE per extra independent rung (bounded by FUSE_CAP)."""
    pool: dict[int, list] = {}
    for g in groups:
        for conf, order, m in g:
            slot = pool.get(id(m.node))
            if slot is None:
                pool[id(m.node)] = [conf, order, m, {m.method}]
                continue
            slot[3].add(m.method)
            if conf > slot[0]:
                slot[0], slot[2] = conf, Match(m.requirement, m.value, m.raw, m.method, conf,
                                               tuple(dict.fromkeys(m.witnesses + slot[2].witnesses)), m.node, m.key_path, m.origin)
            else:
                slot[2] = Match(slot[2].requirement, slot[2].value, slot[2].raw, slot[2].method, slot[0],
                                tuple(dict.fromkeys(slot[2].witnesses + m.witnesses)), slot[2].node, slot[2].key_path, slot[2].origin)
    out: list[_Cand] = []
    for conf, order, m, methods in pool.values():
        extra = len(methods) - 1
        if extra:
            conf = round(min(FUSE_CAP, conf + AGREE * extra), 3)
            m = Match(m.requirement, m.value, m.raw, m.method, conf, m.witnesses, m.node, m.key_path, m.origin)
        out.append((conf, order, m))
    out.sort(key=lambda t: (-t[0], t[1]))
    return out


def resolve(tree: Node, req: Requirement, *, synonyms: dict | None = None) -> list[Match]:
    """Resolve one requirement against a captured tree. Returns matches best-first (all if req.many), or a
    single 'absent' Match (with a reason) when nothing in the document represents the item. ``synonyms``
    supplies the synonym rung with {concept -> surface terms}."""
    rej: Counter = Counter()
    top = _structural(tree, req, rej)
    if top and top[0][2].method in ("key", "path") and top[0][0] >= 0.9:
        ms = [m for _, _, m in top if m.method in ("key", "path")] if req.many else [top[0][2]]
        return ms                                                  # fast path: a clean structural hit
    groups = [top]
    if req.concept and synonyms and req.concept in synonyms:
        groups.append(_synonym(tree, req, synonyms[req.concept], rej))
    if req._keys and req.fuzzy is not None:
        groups.append(_lexical(tree, req, rej))
    if req._neighbors:
        groups.append(_neighborhood(tree, req, rej))
    fused = _fuse(groups)
    if fused:
        ms = [m for _, _, m in fused]
        return ms if req.many else ms[:1]
    if req._prose:
        hits = _prose(tree, req)
        if hits:
            return hits
    return [Match(req.name, None, None, "absent", 1.0, (), None, (), None, reason=_reason(rej))]


def _reason(rej: Counter) -> str:
    if not rej:
        return "no_candidate"
    return ";".join(f"{k}_rejected:{v}" for k, v in sorted(rej.items()))


def _prose(tree: Node, req: Requirement) -> list[Match]:
    hits = []
    for n, kp in _walk_with_path(tree):
        if n.kind != SCALAR or not n.value or n.origin not in _PROSE_ORIGINS:
            continue
        if n.construct not in (TEXT, VALUE):
            continue
        m = req._prose.search(n.value)
        if m:
            value = req.prose_value if req.prose_value is not None else (req._norm(m.group(0)) if req._norm else m.group(0))
            hits.append(Match(req.name, value, n.value, "prose", 0.5, ("prose",), n, kp, n.origin))
            if not req.many:
                break
    return hits


def _synonym(tree: Node, req: Requirement, surface_terms, rej: Counter) -> list[_Cand]:
    """A key that matches a registered surface term of the concept. Exact-normalized hit is high trust (0.9);
    a lexical near-hit against a surface term is allowed when req.fuzzy is set, at lower confidence. A declared
    shape must confirm."""
    exact = {_norm(t) for t in surface_terms}
    out: list[_Cand] = []
    order = 0
    for n, kp in _walk_with_path(tree):
        order += 1
        if not _fits(n, req) or (req.vtype and _vtype(n) not in req.vtype):
            continue
        if not _within_ok(req, kp):
            continue
        nk = _norm(n.key)
        if nk in exact:
            sim, conf = 1.0, 0.9
        elif req.fuzzy is not None:
            sim = _best_alias_sim(n.key, surface_terms)
            if sim < req.fuzzy:
                continue
            conf = min(0.85, 0.5 + 0.35 * sim)
        else:
            continue
        raw, value, shape_ok = _value_of(req, n)
        if req._shape and not shape_ok:
            rej["shape"] += 1
            continue
        witnesses = (("synonym",) if sim >= 1.0 else ("synonym", "lexical")) + (("shape",) if shape_ok else ())
        if shape_ok:
            conf = min(FUSE_CAP, conf + AGREE)
        conf, witnesses = _finish(req, n, conf, witnesses, raw, value)
        out.append((conf, order, Match(req.name, value, raw, "synonym", conf, witnesses, n, kp, n.origin)))
    out.sort(key=lambda t: (-t[0], t[1]))
    return out


def _lexical(tree: Node, req: Requirement, rej: Counter) -> list[_Cand]:
    out: list[_Cand] = []
    order = 0
    for n, kp in _walk_with_path(tree):
        order += 1
        if not _fits(n, req) or (req.vtype and _vtype(n) not in req.vtype):
            continue
        if not _within_ok(req, kp):
            continue
        if _norm(n.key) in req._keys:
            continue                                        # exact keys belong to the structural rung
        sim = _best_alias_sim(n.key, req.keys)
        if sim < req.fuzzy:
            continue
        raw, value, shape_ok = _value_of(req, n)
        if req._shape and not shape_ok:
            rej["shape"] += 1
            continue                                        # a declared shape must confirm a fuzzy key
        conf = min(0.85, 0.55 + 0.3 * sim)
        witnesses = ("lexical",) + (("shape",) if shape_ok else ())
        if shape_ok:
            conf = min(0.89, conf + AGREE)
        conf, witnesses = _finish(req, n, conf, witnesses, raw, value)
        out.append((conf, order, Match(req.name, value, raw, "lexical", conf, witnesses, n, kp, n.origin)))
    out.sort(key=lambda t: (-t[0], t[1]))
    return out


def _neighborhood(tree: Node, req: Requirement, rej: Counter) -> list[_Cand]:
    """Find RECORDs that contain the declared neighbor keys (exactly or lexically), then pick the sibling that
    fits the requirement's type and shape and is not itself a neighbor. All neighbors present = 0.65; a partial
    neighborhood (at least two peers, or all but one when three or more are declared) earns partial credit.
    More than one fitting sibling in the same record is ambiguity: reported, ranked lower, never chosen."""
    out: list[_Cand] = []
    order = 0
    thr = req.fuzzy if req.fuzzy is not None else 1.0
    need = len(req._neighbors)
    min_present = need if need <= 2 else need - 1
    for rec, kp in _walk_with_path(tree):
        order += 1
        if rec.construct != RECORD:
            continue
        kids = [c for c in rec.children if c.construct not in (ANNOTATION, TEXT)]
        keyset = [c.key for c in kids]
        present = [nb for nb in req._neighbors if any(key_similarity(k, nb) >= thr for k in keyset)]
        if len(present) < max(1, min_present):
            continue
        neighbor_nodes = {id(c) for c in kids for nb in req._neighbors if key_similarity(c.key, nb) >= thr}
        fits = []
        for c in kids:
            if id(c) in neighbor_nodes or not _fits(c, req):
                continue
            if req.vtype and _vtype(c) not in req.vtype:
                continue
            raw, value, shape_ok = _value_of(req, c)
            if req._shape and not shape_ok:
                continue
            fits.append((c, raw, value, shape_ok))
        if not fits:
            rej["neighborhood_no_fit"] += 1
            continue
        ambiguous = len(fits) > 1
        frac = len(present) / need
        for c, raw, value, shape_ok in fits:
            conf = (0.65 if frac == 1.0 else 0.5 + 0.15 * frac) + (AGREE if shape_ok else 0.0)
            witnesses = (("neighborhood",) if frac == 1.0 else ("neighborhood", f"peers:{len(present)}/{need}")) + (("shape",) if shape_ok else ())
            if ambiguous:
                conf, witnesses = conf * 0.75, witnesses + ("ambiguous",)
            conf, witnesses = _finish(req, c, conf, witnesses, raw, value)
            out.append((conf, order, Match(req.name, value, raw, "neighborhood", conf, witnesses, c, kp + (c.key,), c.origin)))
    out.sort(key=lambda t: (-t[0], t[1]))
    return out


def resolve_all(tree: Node, requirements: Iterable[Requirement], *, synonyms: dict | None = None,
                scavenge: bool = False) -> ResolveReport:
    """Resolve a set of requirements together: matches, provable absences (with reasons), and the residue of
    unclaimed leaves. With ``scavenge=True``, a last-resort pass tries to recover an absent, shape-bearing
    field from residue values that match its shape: a unique candidate is claimed (0.4); several candidates
    are ranked by the witnesses that can tell them apart (value profile, neighborhood) and claimed only when
    one is clearly ahead -- otherwise the field stays absent with an 'ambiguous' reason naming the candidates."""
    requirements = list(requirements)
    rep = ResolveReport()
    claimed: set[int] = set()
    for req in requirements:
        ms = resolve(tree, req, synonyms=synonyms)
        if ms and ms[0].found:
            rep.matches[req.name] = ms
            for m in ms:
                if m.node is not None:
                    claimed.add(id(m.node))
        else:
            rep.absent.append(req.name)
            rep.reasons[req.name] = ms[0].reason or "no_candidate"
    rep.residue = [n for n in _value_nodes(tree) if id(n) not in claimed]
    if scavenge:
        _scavenge(tree, rep, requirements)
    return rep


def _record_of(tree: Node) -> dict[int, Node | None]:
    parents: dict[int, Node | None] = {}

    def walk(n: Node, rec: Node | None):
        cur = n if n.construct == RECORD else rec
        for c in n.children:
            parents[id(c)] = cur
            walk(c, cur)
    walk(tree, None)
    return parents


def _scavenge(tree: Node, rep: ResolveReport, requirements: list[Requirement]) -> None:
    by_name = {r.name: r for r in requirements}
    parents = None
    for name in list(rep.absent):
        req = by_name.get(name)
        if req is None or req._shape is None:
            continue                                 # only shape-bearing fields can be scavenged by value
        cands = [n for n in rep.residue if _raw(n, req) and req._shape.search(_raw(n, req))
                 and (not req.vtype or _vtype(n) in req.vtype)]
        if not cands:
            continue
        if len(cands) == 1:
            n, conf, witnesses = cands[0], 0.4, ("scavenge", "shape")
        else:
            # several shaped values: rank by the witnesses that can separate them (value profile, neighborhood);
            # lexical nearness is deliberately NOT used here -- a decoy like RELATED_ID is lexically closest
            if parents is None:
                parents = _record_of(tree)
            thr = req.fuzzy if req.fuzzy is not None else 1.0
            scored = []
            for c in cands:
                s = 0.0
                vw = value_witness(_raw(c, req), req._profile) if req._profile is not None else None
                if vw is not None:
                    s += vw
                rec = parents.get(id(c))
                if req._neighbors and rec is not None:
                    keyset = [k.key for k in rec.children]
                    present = sum(1 for nb in req._neighbors if any(key_similarity(k, nb) >= thr for k in keyset))
                    s += present / len(req._neighbors)
                scored.append((s, c))
            scored.sort(key=lambda t: -t[0])
            if scored[0][0] - scored[1][0] < 0.15:
                rep.reasons[name] = "ambiguous:" + ",".join(str(c.key) for c in cands[:6])
                continue                             # nothing separates them: stay honestly absent
            n, conf, witnesses = scored[0][1], 0.35, ("scavenge", "shape", "ranked")
        raw, value, _ = _value_of(req, n)
        if req._norm and value is None and raw:
            conf, witnesses = round(conf * 0.6, 3), witnesses + ("unnormalized",)
        rep.matches[name] = [Match(name, value, raw, "scavenge", conf, witnesses, n, (), n.origin)]
        rep.absent.remove(name)
        rep.reasons.pop(name, None)
        rep.residue = [x for x in rep.residue if x is not n]
