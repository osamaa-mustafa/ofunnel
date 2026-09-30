# Concepts

This page explains the ideas behind O-Funnel in more depth than the README. The library has two halves: a
per-format **capture** layer that turns any document into one structural tree, and a format-blind **resolution**
layer that locates declared requirements in that tree.

## The two spaces

Brittle extraction usually comes from collapsing two different things into one pattern:

- The **document space** is open and not under your control: many formats, many schemas, drifting over time.
- The **requirement space** is small and under your control: the handful of fields you actually need.

A byte regex tries to be fluent in both at once, and is fluent in neither. It has only the byte neighborhood to
tell the target occurrence apart from other occurrences, so it hard-codes surroundings. O-Funnel gives the two
concerns separate machinery: value description (shape, value profile) lives in the requirement space, and
localization (key, path, neighborhood) lives in the transcribed document space.

## Capture and the unified vocabulary

An adapter builds a tree of `Node`s from one format. A `Node` has a `key`, a `key_source` (named, indexed, or
inferred), a `kind` (scalar or group), an optional scalar `value`, ordered `children`, a `role`, and a byte
`span` where the format provides one. A normalization pass then sets three fields on every node and removes
nothing:

- `construct`: one of VALUE, RECORD, COLLECTION, TEXT, ANNOTATION.
- `origin`: the source dialect, for example `xml.attribute`, `json.array`, `csv.cell`.
- `vtype`: for a VALUE, one of string, number, boolean, null.

Because the source dialect is preserved in `origin`, the transcription is lossless: the original is recoverable,
yet everything downstream reads only the five constructors.

Formally the result is a typed, labeled, ordered regular tree language. That is what lets the completeness
oracle be a decidable statement about two terms rather than a hope.

## The completeness oracle

Every capture is gated by `check_complete(raw, node, fmt)`:

- **Declared formats** (XML, JSON, CSV) are self-describing, so the oracle re-parses the source independently
  and checks the two trees reconstruct each other, up to cosmetic differences and honoring the declared
  encoding.
- **Implicit text** yields lines, so the oracle checks byte coverage: every source byte is accounted for.
- **HTML** is presentational, so the oracle checks that no visible text token is dropped.

If the oracle returns false, do not use the capture. In a pipeline this is a loud, catchable event, which is the
opposite of a silent null.

## The requirement language

A `Requirement` is declared in the tree's own terms. The important fields:

- `keys`: candidate key spellings, compared case- and separator-insensitively.
- `shape`: a regex matched against a single value's content (not the document).
- `exemplars`: a few example values, from which a value profile is derived.
- `concept` + a `synonyms` map: an ontology hook (see below).
- `neighbors`: sibling keys the field's record should contain.
- `path` / `within`: containment context.
- `prose`: a phrase allowed only inside prose nodes, as a last resort.
- `normalize`: read the value as bool, number, date, text, or via a callable.
- `vtype`, `many`, `fuzzy`, `required`: type filter, all-vs-best, lexical threshold, and required flag.

## The fused evidence ladder

`resolve(tree, req, synonyms=...)` walks the tree once and gathers every rung that fires for each candidate
node. A clean key or path hit is a fast path. Otherwise the rungs are fused: candidates the same node reaches by
several rungs merge, each extra agreeing witness adds a bounded amount, and a contradicted declaration (a value
failing the declared shape or profile) subtracts and is tagged (`shape_miss`, `value_miss`). The best-evidenced
node wins.

Every `Match` records:

- `value`, `raw`: the read value and the raw text it came from.
- `method`: key, path, shape, synonym, lexical, neighborhood, prose, scavenge, or absent.
- `confidence`, `witnesses`: how sure, and which signals agreed.
- `node`, `key_path`, `origin`: where it came from.
- `reason`: for an absence, why (`no_candidate`, `shape_rejected:n`, `ambiguous:c1,c2`, ...).

`resolve_all(tree, reqs, synonyms=..., scavenge=...)` runs a set together and returns matches, absences with
reasons, and the residue of unclaimed leaves.

## Value profiles

`profile(values)` builds a compact description of a value population: run-length character-class signatures, the
digit/alpha/space/punctuation mix, mean length, and the fraction that are numbers, dates, or booleans.
`similarity(p, q)` compares two populations; `value_witness(v, p)` scores one value against a profile. This is a
purely structural, domain-free signal: it separates fields that share a key but differ in values, and unites
fields that differ in key but share values.

## Synonyms and the ontology hook

The synonym rung is domain-agnostic: you pass a `{concept -> set of surface terms}` map to `synonyms=`, and a
requirement opts in with `concept="..."`. This is where you connect a controlled vocabulary or an alias list you
maintain elsewhere. The library never hard-codes any domain terms.

```python
synonyms = {"code": {"code", "record identifier", "recordIdentifier", "rec_id"}}
Requirement("code", concept="code", keys=("code",), shape=r"\d{4}-[A-Z]{2}\d{2}")
```

## The funnel

After resolving, the leaves no requirement claimed form the residue. `funnel(trees, reqs, synonyms=...)` scores
each residue leaf against each requirement using structure only (value shape, value profile, neighborhood, key
nearness to aliases), never the key that already failed. It returns ranked `Proposal`s, each with support (how
many leaves back it), confidence, and a contest count (how often it competes with another requirement).
`promote(report, ...)` keeps only well-supported, high-confidence, uncontested proposals and returns a
`{concept-or-requirement -> [alias keys]}` map. `Pipeline.learn()` folds those aliases into the requirements'
keys so the next run resolves them on the cheap key rung.

## The scavenger

`scavenge=True` is a last resort for a shape-bearing field the ladder left absent. It looks in the residue for
values matching the field's shape. A unique match is claimed at low confidence and tagged; several matches are
ranked only by evidence that can separate them (value profile, neighborhood) and claimed only when one is
clearly ahead, otherwise the field stays absent with an `ambiguous:` reason. Lexical nearness is deliberately
excluded, because a decoy is often the lexically closest key.

## Calibration

Nominal confidences are asserted. To know what a match is really worth, measure it: run your extractor over a
labelled set, record per (method + witness) bucket the fraction correct, and put those numbers in
`ofunnel.calibration.MEASURED`. `reliability(match)` then returns the measured precision for buckets with enough
observations and the nominal confidence otherwise, and never lifts a contradicted or ambiguous match.

## Determinism and performance

The library is deterministic and dependency-free. Capture and the oracle are linear in document size.
Resolution walks the tree once per requirement, so a document with N nodes and R requirements costs O(N x R)
node visits; key-similarity results are memoized, so across a feed whose keys repeat they are effectively free
after first sight. The funnel is linear in the total residue across the corpus.
