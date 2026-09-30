"""The O-through funnel: trace residue back to the required inputs through structure.

After ``resolve_all`` each document leaves a residue of captured leaves that no requirement claimed. The funnel
takes that residue across a whole corpus and, for each unclaimed leaf, asks which required input it most likely
represents, using only structural evidence (value shape, neighborhood, type, key nearness), never the keys that
already failed. A leaf that fits a requirement is *funnelled* to it as an alias proposal; a leaf that fits
nothing stays in the true residue, the honest measure of what is still unknown.

The output is proposals, not extractions: "the key K is probably an alias of requirement/concept R, backed by
N leaves, confidence C, evidence E". Confirmed proposals are promoted into the synonym map, closing the loop so
the next run resolves K by the synonym rung instead of dropping it: a structure-based, self-supervised way to
discover key aliases from the data an extractor could not otherwise claim."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable

from .model import RECORD, Node
from .profile import value_witness
from .require import VALUE_MISS, VALUE_OK, Requirement, _raw, _vtype, key_similarity, resolve_all


@dataclass
class Proposal:
    requirement: str                      # the required input this residue probably feeds
    concept: str | None                   # its concept id, if any (where a promoted alias would land)
    key: str                              # the residue key name (the candidate alias)
    support: int                          # how many residue leaves across the corpus back it
    confidence: float                     # mean per-leaf structural fit
    contested: int                        # of those, how many also fit another requirement about as well
    evidence: dict                        # tally: shape / neighborhood / vtype / lexical hits
    samples: list                         # a few (value, origin) examples

    def as_dict(self) -> dict:
        return {"requirement": self.requirement, "concept": self.concept, "key": self.key, "support": self.support,
                "confidence": round(self.confidence, 3), "contested": self.contested, "evidence": self.evidence,
                "samples": self.samples[:3]}


@dataclass
class FunnelReport:
    proposals: list[Proposal] = field(default_factory=list)
    unattributed: list[tuple[str, int]] = field(default_factory=list)   # (residue key, count) that fit no requirement
    docs: int = 0
    residue_leaves: int = 0
    funnelled: int = 0                    # residue leaves traced to some requirement

    @property
    def trace_rate(self) -> float:
        return self.funnelled / self.residue_leaves if self.residue_leaves else 0.0


def _record_parents(tree: Node) -> dict[int, Node | None]:
    parents: dict[int, Node | None] = {}

    def walk(n: Node, rec: Node | None):
        cur = n if n.construct == RECORD else rec      # the record that DIRECTLY contains n's children
        for c in n.children:
            parents[id(c)] = cur
            walk(c, cur)
    walk(tree, None)
    return parents


def _fit(leaf: Node, req: Requirement, record: Node | None, synonyms, is_absent: bool) -> tuple[float, dict]:
    """Structural fit of a residue leaf to a requirement, WITHOUT the keys that already failed. 0 if a declared
    shape or type is contradicted (a hard gate); otherwise the strongest of shape / neighborhood / key-nearness,
    with small bonuses when signals agree or the requirement was absent from this document."""
    value = _raw(leaf, req)                # a VALUE's value, or the text of a text-bearing element
    if value is None:
        return 0.0, {}
    shape_hit = bool(req._shape and value and req._shape.search(value))
    if req._shape and not shape_hit:
        return 0.0, {}
    if req.vtype and _vtype(leaf) not in req.vtype:
        return 0.0, {}
    shape_c = 0.55 if shape_hit else 0.0
    nb_hit = False
    if req._neighbors and record is not None:
        keyset = [c.key for c in record.children]
        thr = req.fuzzy if req.fuzzy is not None else 1.0
        nb_hit = all(any(key_similarity(k, nb) >= thr for k in keyset) for nb in req._neighbors)
    nb_c = 0.55 if nb_hit else 0.0
    aliases = list(req.keys) + (list(synonyms.get(req.concept, ())) if (synonyms and req.concept) else [])
    lex = max((key_similarity(leaf.key, a) for a in aliases), default=0.0)
    vw = value_witness(value, req._profile) if req._profile is not None else None
    if vw is not None and vw < VALUE_MISS:
        return 0.0, {}                     # the value population says this is a different field: hard gate
    val_c = 0.5 if (vw is not None and vw >= VALUE_OK) else 0.0
    base = max(shape_c, nb_c, val_c, 0.5 * lex)
    if base == 0.0:
        return 0.0, {}
    conf = base
    agreeing = sum(1 for x in (shape_hit, nb_hit, val_c > 0) if x)
    if agreeing >= 2:
        conf += 0.1                        # independent structural signals agree
    if lex >= 0.4 and agreeing >= 1:
        conf += 0.05
    if is_absent:
        conf += 0.1                        # the requirement had no other match here: stronger evidence this IS it
    ev = {"shape": shape_hit, "neighborhood": nb_hit, "value": val_c > 0, "vtype": bool(req.vtype), "lexical": round(lex, 2)}
    return min(0.95, conf), ev


def funnel(trees: Iterable[Node], requirements: list[Requirement], *, synonyms: dict | None = None,
           min_support: int = 2, min_confidence: float = 0.5, per_leaf: float = 0.5) -> FunnelReport:
    """Trace corpus residue back to required inputs. Returns ranked alias proposals + the untraceable residue."""
    agg: dict[tuple[str, str], dict] = {}
    unattributed: Counter = Counter()
    docs = residue_leaves = funnelled = 0
    for tree in trees:
        docs += 1
        rep = resolve_all(tree, requirements, synonyms=synonyms)
        absent = set(rep.absent)
        parents = _record_parents(tree)
        # which requirements were already satisfied IN EACH RECORD (a residue leaf competing with one is likely a
        # DIFFERENT field, not an alias); scoped per record so many records each holding the field is not ambiguity
        matched_in_record = {(id(parents.get(id(m.node))), name)
                             for name, ms in rep.matches.items() for m in ms if m.node is not None}
        attributions = []
        for leaf in rep.residue:
            residue_leaves += 1
            rec = parents.get(id(leaf))
            scored = []
            for req in requirements:
                f, ev = _fit(leaf, req, rec, synonyms, req.name in absent)
                if f >= per_leaf:
                    scored.append((f, req, ev))
            if not scored:
                unattributed[str(leaf.key)] += 1
                continue
            scored.sort(key=lambda t: -t[0])
            f, req, ev = scored[0]
            multi_req = len(scored) > 1 and scored[1][0] >= f - 0.1     # this leaf also fits another requirement
            attributions.append((leaf, rec, req, f, ev, multi_req))
        per_rec_req = Counter((id(rec), req.name) for _, rec, req, _, _, _ in attributions)  # >1 leaf in ONE record -> ambiguity
        for leaf, rec, req, f, ev, multi_req in attributions:
            funnelled += 1
            already = (id(rec), req.name) in matched_in_record          # this record already has the field elsewhere
            contested = 1 if (multi_req or per_rec_req[(id(rec), req.name)] > 1 or already) else 0
            slot = agg.setdefault((req.name, str(leaf.key)),
                                  {"concept": req.concept, "confs": [], "contested": 0, "ev": Counter(), "samples": []})
            slot["confs"].append(f)
            slot["contested"] += contested
            for k, v in ev.items():
                if v is True:
                    slot["ev"][k] += 1
            if ev.get("lexical", 0) >= 0.4:
                slot["ev"]["lexical>=.4"] += 1
            if len(slot["samples"]) < 5:
                slot["samples"].append((_raw(leaf, req), leaf.origin))
    proposals = []
    for (reqname, key), s in agg.items():
        support = len(s["confs"])
        conf = sum(s["confs"]) / support
        if support < min_support or conf < min_confidence:
            continue
        proposals.append(Proposal(reqname, s["concept"], key, support, conf, s["contested"], dict(s["ev"]), s["samples"]))
    proposals.sort(key=lambda p: (-p.support, -p.confidence))
    return FunnelReport(proposals=proposals, unattributed=unattributed.most_common(), docs=docs,
                        residue_leaves=residue_leaves, funnelled=funnelled)


def promote(report: FunnelReport, *, min_support: int = 3, min_confidence: float = 0.7, max_contested_ratio: float = 0.25) -> dict:
    """Confirmed proposals -> {concept or requirement -> [alias keys]} ready to add to the synonym map.
    Conservative by design: enough support, high confidence, and mostly uncontested (a wrong alias is corruption)."""
    out: dict[str, list[str]] = {}
    for p in report.proposals:
        if p.support >= min_support and p.confidence >= min_confidence and (p.contested / p.support) <= max_contested_ratio:
            out.setdefault(p.concept or p.requirement, []).append(p.key)
    return out
