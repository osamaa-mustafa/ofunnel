# Benchmarks

Scripts that produce every number reported for O-Funnel. They run against the installed library
(`pip install ofunnel`) or the source tree (`PYTHONPATH=src`). All synthetic suites are deterministic.

| script | what it shows | data | extra deps |
|---|---|---|---|
| `perturbation.py` | 117 documents: 13 records x 9 drift categories (renames, camelCase, JSON, CSV, date formats, a decoy, opaque keys); regex vs O-Funnel vs O-Funnel after learning | synthetic | none |
| `hard_scenarios.py` | 120 documents: 15 records x 8 classes, each isolating one way a byte regex fails, plus opaque keys | synthetic | none |
| `funnel_gain.py` | self-improvement: keys drift to opaque tokens, the funnel traces residue back and promotes aliases; with and without value exemplars | synthetic | none |
| `pubmed.py` | real-world corpus: PubMed citation records, six fields vs an exact-path parser, pristine and after a five-element schema drift; completeness and throughput | PubMed baseline files | none |
| `perf.py` | throughput, latency, time split, drift cost | synthetic | none |
| `valentine_matching.py` | schema matching on a held-out Valentine subset vs COMA, Cupid, Similarity Flooding, distribution-based | Valentine datasets | `valentine`, `pandas` |
| `swde.py` | out-of-scope probe on SWDE-derived web pages (negative result) | Hugging Face `hazyresearch/based-swde-old` | none |

## Run

```bash
pip install ofunnel            # or: pip install -e . from the repo root
python benchmarks/perturbation.py
python benchmarks/hard_scenarios.py
python benchmarks/funnel_gain.py
python benchmarks/perf.py
```

PubMed (public, U.S. National Library of Medicine):

```bash
curl -O https://ftp.ncbi.nlm.nih.gov/pubmed/baseline/pubmed26n0001.xml.gz
curl -O https://ftp.ncbi.nlm.nih.gov/pubmed/baseline/pubmed26n1334.xml.gz
python benchmarks/pubmed.py pubmed26n0001.xml.gz pubmed26n1334.xml.gz
```

The baseline is republished every year; any file works, and `--limit N` caps the record count.

SWDE-derived rows (first 500 rows of the validation split):

```bash
python benchmarks/swde.py --fetch swde_rows.json
python benchmarks/swde.py swde_rows.json
```

Valentine (datasets from https://zenodo.org/records/5084605):

```bash
pip install valentine pandas
python benchmarks/valentine_matching.py path/to/Valentine-datasets 12 1
```

## Notes

- The synthetic suites are constructed on purpose to exercise the failure modes of byte-level extraction.
  They demonstrate behavior; they are not a sample of real-world difficulty. `pubmed.py` is the real-world check.
- Throughput depends on the machine; compare systems within one run, not across machines.
