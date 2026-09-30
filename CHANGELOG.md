# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-09-30

### Fixed
- Markup elements that carry their own text are now resolvable as values: XML/HTML *simple content*
  (attributes plus text, e.g. `<PMID Version="1">41605291</PMID>`, `<ISSN IssnType="Electronic">...`) and
  *mixed content* (text with inline markup, e.g. `<ArticleTitle>Effect of <i>X</i></ArticleTitle>`). Before,
  such elements were captured correctly but a value requirement could not reach them, so fields like a PubMed
  PMID, ISSN or DOI came back absent. Capture is unchanged and still lossless; the text is read through a view.
  The scavenger and the funnel see these elements too.

### Added
- `value_view(node)`: the scalar content a node carries (a value's own value, or an element's text).
- `benchmarks/`: scripts for every reported number (perturbation suite, hard scenarios, funnel gain, PubMed
  real-world corpus, throughput, Valentine schema matching, SWDE probe).

## [0.1.0] - 2026-09-30

Initial public release.

### Added
- Lossless structural **capture** for XML, JSON, CSV, HTML, and implicit key-value text into one typed,
  labeled, ordered tree over a closed five-constructor vocabulary (VALUE, RECORD, COLLECTION, TEXT, ANNOTATION).
- A **completeness oracle** that gates every capture (round-trip for declared formats, coverage for implicit
  ones) and fails loudly rather than dropping data silently.
- A declarative **requirement language** and a **fused evidence ladder** (key, path, shape, synonym, lexical,
  neighborhood, value profile, prose, absent) that returns matches with method, confidence, and provenance,
  plus provable absences with reasons.
- **Value profiles** derived from a few example values, used as a witness on every rung.
- The **O-Funnel**: turn the residue of unclaimed data into ranked alias proposals and promote the safe ones,
  a structure-based self-improvement loop.
- A **scavenger** that recovers fields under fully opaque keys while abstaining on ambiguity.
- A **calibration** table mapping (method + witness) buckets to measured precision.
- Zero third-party dependencies; typed (`py.typed`); deterministic.
