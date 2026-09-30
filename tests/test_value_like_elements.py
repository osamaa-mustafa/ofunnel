"""Text-bearing markup elements are values: XML/HTML simple content (attributes + text) and mixed content
(text with inline markup). Capture stays lossless (the element is kept as a record with attribute and text
children); resolution reads its text through value_view."""
from ofunnel import Requirement, capture, check_complete, extract, funnel, promote, value_view, by_key

CODE = r"^\d{4}-[A-Z]{2}\d{2}$"


def test_simple_content_resolves_by_key():
    raw = b'<A><PMID Version="1">41605291</PMID></A>'
    node, fmt = capture(raw)
    assert check_complete(raw, node, fmt)                       # capture unchanged and still lossless
    assert value_view(by_key(node, "PMID")[0]) == "41605291"
    r = extract(raw, [Requirement("pmid", keys=("pmid",), shape=r"^\d+$")])
    m = r.fields["pmid"]
    assert m.found and m.method == "key" and m.value == "41605291" and "shape" in m.witnesses


def test_simple_content_shape_confirms_or_contradicts():
    ok = extract(b'<J><ISSN IssnType="Electronic">1873-2763</ISSN></J>',
                 [Requirement("issn", keys=("issn",), shape=r"^\d{4}-\d{3}[\dX]$")]).fields["issn"]
    bad = extract(b'<J><ISSN IssnType="Electronic">n/a</ISSN></J>',
                  [Requirement("issn", keys=("issn",), shape=r"^\d{4}-\d{3}[\dX]$")]).fields["issn"]
    assert ok.value == "1873-2763" and ok.confidence == 0.99
    assert bad.found and "shape_miss" in bad.witnesses


def test_mixed_content_reads_full_text():
    raw = b"<A><ArticleTitle>Effect of <i>X</i> on <b>Y</b> cells.</ArticleTitle></A>"
    node, fmt = capture(raw)
    assert check_complete(raw, node, fmt)
    r = extract(raw, [Requirement("title", keys=("article_title",))])
    assert r.value("title") == "Effect of X on Y cells."


def test_value_identified_by_shape_under_generic_attributed_key():
    raw = (b'<Article><ELocationID EIdType="pii">S0000-0000(26)00031-1</ELocationID>'
           b'<ELocationID EIdType="doi">10.1016/j.bone.2026.117805</ELocationID></Article>')
    r = extract(raw, [Requirement("doi", shape=r"^10\.\d{4,9}/\S+$")])
    assert r.value("doi") == "10.1016/j.bone.2026.117805" and r.fields["doi"].method == "shape"


def test_scavenger_reaches_attributed_opaque_key():
    r = extract(b'<r><c1 v="2">4021-KP73</c1><c9>x</c9></r>',
                [Requirement("code", keys=("code",), shape=CODE)], scavenge=True)
    assert r.fields["code"].method == "scavenge" and r.value("code") == "4021-KP73"


def test_funnel_proposes_alias_for_attributed_element():
    trees = [capture(b'<r><f7 v="1">%04d-AA90</f7></r>' % i)[0] for i in range(5)]
    req = [Requirement("code", keys=("code",), shape=CODE, exemplars=("0503-AA90",), fuzzy=None)]
    rep = funnel(trees, req, min_support=3)
    assert "f7" in promote(rep, min_support=3, min_confidence=0.6).get("code", [])


def test_residue_includes_text_bearing_element_once():
    r = extract(b'<A><PMID Version="1">41605291</PMID></A>', [Requirement("x", keys=("nothing",), fuzzy=None)])
    keys = [n.key for n in r.residue]
    assert keys.count("PMID") == 1 and "#text" not in keys and "Version" in keys


def test_plain_text_file_is_not_one_big_value():
    raw = b"code: 4021-KP73\n\nother: hello\n"
    r = extract(raw, [Requirement("code", shape=r"\d{4}-[A-Z]{2}\d{2}", extract=True)], fmt="text")
    m = r.fields["code"]
    assert m.value == "4021-KP73" and m.node.key != "$doc"
