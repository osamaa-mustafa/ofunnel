"""Real-world corpus: PubMed citation records (public; U.S. National Library of Medicine annual baseline).

Each <PubmedArticle> is one document. Six fields are extracted and scored against an exact-path parser
written for this schema with ElementTree (the incumbent approach, used as gold):

    pmid       <MedlineCitation>/<PMID Version="1">       simple content (attribute + text)
    title      <ArticleTitle>                              sometimes mixed content (<i>, <sup>, ...)
    issn       <Journal>/<ISSN IssnType="...">             simple content
    language   <Article>/<Language>
    pub_year   <PubDate>/<Year> or <MedlineDate>           year extracted from free text when needed
    doi        <ELocationID EIdType="doi"> / <ArticleId IdType="doi">   identified by value shape only

Then every record goes through a realistic schema drift (five element renames) and both O-Funnel and a
tag-regex extractor are scored again, with the requirements unchanged.

Data: download baseline files from https://ftp.ncbi.nlm.nih.gov/pubmed/baseline/ and pass their paths.

    python benchmarks/pubmed.py pubmed26n0001.xml.gz pubmed26n1334.xml.gz [--limit N] [--no-synonyms]
"""
from __future__ import annotations

import gzip
import html
import re
import sys
import time
import xml.etree.ElementTree as ET

from ofunnel import Requirement, capture, check_complete, resolve_all

YEAR = r"\b(?:18|19|20)\d{2}\b"
FIELDS = ["pmid", "title", "issn", "language", "pub_year", "doi"]
SYNONYMS = {"pmid": {"pmid", "pubmed id", "pubmed identifier"},
            "issn": {"issn", "journal issn", "international standard serial number"}}
REQS = [
    Requirement("pmid", concept="pmid", keys=("pmid",), path=("MedlineCitation", "PMID"), shape=r"^\d{1,9}$"),
    Requirement("title", keys=("article_title",)),
    Requirement("issn", concept="issn", keys=("issn",), shape=r"^\d{4}-\d{3}[\dXx]$"),
    Requirement("language", keys=("language",)),
    Requirement("pub_year", keys=("year", "medline_date"), within="PubDate", shape=YEAR, extract=True),
    Requirement("doi", shape=r"^10\.\d{4,9}/\S+$"),
]
DRIFT = {"PMID": "PubMedIdentifier", "ArticleTitle": "TitleOfArticle", "ISSN": "JournalISSN",
         "Language": "Lang", "PubDate": "PublicationDate"}


# ---- data -------------------------------------------------------------------------------------------------
def records(paths, limit=None):
    out = []
    for p in paths:
        data = gzip.open(p, "rb").read() if p.endswith(".gz") else open(p, "rb").read()
        out += re.findall(rb"<PubmedArticle>.*?</PubmedArticle>", data, re.S)
        if limit and len(out) >= limit:
            return out[:limit]
    return out


def drift(raw: bytes) -> bytes:
    for old, new in DRIFT.items():
        raw = re.sub(rb"<(/?)" + old.encode() + rb"([\s>])", rb"<\1" + new.encode() + rb"\2", raw)
    return raw


def _clean(v):
    return " ".join(str(v).split()) if v is not None else None


# ---- gold: an exact-path parser written for PubMed's schema -----------------------------------------------
def gold(raw: bytes) -> dict:
    el = ET.fromstring(raw)
    g = {}
    mc = el.find("MedlineCitation")
    art = mc.find("Article") if mc is not None else None
    pm = mc.find("PMID") if mc is not None else None
    if pm is not None and pm.text:
        g["pmid"] = pm.text.strip()
    if art is not None:
        t = art.find("ArticleTitle")
        if t is not None and "".join(t.itertext()).strip():
            g["title"] = _clean("".join(t.itertext()))
        issn = art.find("Journal/ISSN")
        if issn is not None and issn.text:
            g["issn"] = issn.text.strip()
        lang = art.find("Language")
        if lang is not None and lang.text:
            g["language"] = lang.text.strip()
        pd = art.find("Journal/JournalIssue/PubDate")
        if pd is not None:
            y, md = pd.find("Year"), pd.find("MedlineDate")
            if y is not None and y.text:
                g["pub_year"] = y.text.strip()
            elif md is not None and md.text and re.search(YEAR, md.text):
                g["pub_year"] = re.search(YEAR, md.text).group(0)
        for e in art.findall("ELocationID"):
            if e.get("EIdType") == "doi" and e.text:
                g["doi"] = e.text.strip()
                break
    if "doi" not in g:
        for a in el.findall("PubmedData/ArticleIdList/ArticleId"):
            if a.get("IdType") == "doi" and a.text:
                g["doi"] = a.text.strip()
                break
    return g


# ---- the two systems ----------------------------------------------------------------------------------------
_TAG = re.compile(r"<[^>]+>")
RX = {
    "pmid": re.compile(rb"<PMID[^>]*>(\d+)</PMID>"),
    "title": re.compile(rb"<ArticleTitle[^>]*>(.*?)</ArticleTitle>", re.S),
    "issn": re.compile(rb"<ISSN[^>]*>([\dXx-]+)</ISSN>"),
    "language": re.compile(rb"<Language>(\w+)</Language>"),
    "pub_year": re.compile(rb"<PubDate>(.*?)</PubDate>", re.S),
    "doi_eloc": re.compile(rb'<ELocationID EIdType="doi"[^>]*>([^<]+)</ELocationID>'),
    "doi_aid": re.compile(rb'<ArticleId IdType="doi">([^<]+)</ArticleId>'),
}


def regex_extract(raw: bytes) -> dict:
    out = {}
    for f in ("pmid", "title", "issn", "language"):
        m = RX[f].search(raw)
        if m:
            out[f] = _clean(html.unescape(_TAG.sub("", m.group(1).decode("utf-8", "replace"))))
    m = RX["pub_year"].search(raw)
    if m:
        y = re.search(YEAR, m.group(1).decode("utf-8", "replace"))
        if y:
            out["pub_year"] = y.group(0)
    m = RX["doi_eloc"].search(raw) or RX["doi_aid"].search(raw)
    if m:
        out["doi"] = html.unescape(m.group(1).decode("utf-8", "replace")).strip()
    return out


ACTIVE_SYNONYMS = SYNONYMS                      # --no-synonyms sets this to {} (ablation)


def ofunnel_extract(raw: bytes, stats=None) -> dict:
    tree, fmt = capture(raw, fmt="xml")
    if stats is not None:
        stats["complete"] += int(check_complete(raw, tree, fmt))
    rep = resolve_all(tree, REQS, synonyms=ACTIVE_SYNONYMS)
    return {n: _clean(ms[0].value) for n, ms in rep.matches.items()}


# ---- scoring -------------------------------------------------------------------------------------------------
def score(golds, preds):
    acc = {f: [0, 0, 0] for f in FIELDS}            # tp, fp, fn
    for g, p in zip(golds, preds):
        for f in FIELDS:
            gv, pv = g.get(f), p.get(f)
            if gv is not None and pv == gv:
                acc[f][0] += 1
            elif pv is not None:
                acc[f][1] += 1
            elif gv is not None:
                acc[f][2] += 1
    return acc


def f1(a):
    tp, fp, fn = a
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def main(argv):
    global ACTIVE_SYNONYMS
    if "--no-synonyms" in argv:
        ACTIVE_SYNONYMS = {}
        argv = [a for a in argv if a != "--no-synonyms"]
        print("ablation: synonym rung disabled")
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
        argv = [a for i, a in enumerate(argv) if a != "--limit" and (i == 0 or argv[i - 1] != "--limit")]
    paths = [a for a in argv if not a.startswith("--")]
    recs = records(paths, limit)
    golds = [gold(r) for r in recs]
    mixed = sum(1 for r in recs if re.search(rb"<ArticleTitle[^>]*>[^<]*<[a-z]", r))
    print(f"PubMed records: {len(recs):,} from {len(paths)} baseline file(s); "
          f"{mixed:,} titles contain inline markup (mixed content)")
    present = {f: sum(1 for g in golds if f in g) for f in FIELDS}
    print("gold fields present: " + ", ".join(f"{f} {present[f] / len(recs):.1%}" for f in FIELDS))

    stats = {"complete": 0}
    t0 = time.perf_counter()
    ofn = [ofunnel_extract(r, stats) for r in recs]
    dt = time.perf_counter() - t0
    reg = [regex_extract(r) for r in recs]
    drifted = [drift(r) for r in recs]
    dstats = {"complete": 0}
    ofn_d = [ofunnel_extract(r, dstats) for r in drifted]
    reg_d = [regex_extract(r) for r in drifted]

    print(f"completeness (oracle): pristine {stats['complete'] / len(recs):.2%}, drifted {dstats['complete'] / len(recs):.2%}")
    print(f"throughput (capture + oracle + 6 requirements): {len(recs) / dt:,.0f} records/s\n")
    s = {k: score(golds, v) for k, v in (("reg", reg), ("ofn", ofn), ("reg_d", reg_d), ("ofn_d", ofn_d))}
    print(f"{'field':10} {'regex':>7} {'O-Funnel':>9}   | drifted: {'regex':>6} {'O-Funnel':>9}   (F1)")
    print("-" * 64)
    tot = {k: [0, 0, 0] for k in s}
    for f in FIELDS:
        for k in s:
            tot[k] = [a + b for a, b in zip(tot[k], s[k][f])]
        print(f"{f:10} {f1(s['reg'][f]):7.3f} {f1(s['ofn'][f]):9.3f}   |          "
              f"{f1(s['reg_d'][f]):6.3f} {f1(s['ofn_d'][f]):9.3f}")
    print("-" * 64)
    print(f"{'overall':10} {f1(tot['reg']):7.3f} {f1(tot['ofn']):9.3f}   |          "
          f"{f1(tot['reg_d']):6.3f} {f1(tot['ofn_d']):9.3f}")
    print(f"\ndrift applied: {DRIFT}")


if __name__ == "__main__":
    main(sys.argv[1:])
