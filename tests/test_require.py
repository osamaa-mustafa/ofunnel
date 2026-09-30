"""The requirement ladder: each rung, fusion, value profile, absence with a reason."""
from datetime import date

from ofunnel import Requirement, capture, extract, resolve

DATE = r"\b\d{4}-\d{2}-\d{2}\b"
CODE = r"^\d{4}-[A-Z]{2}\d{2}$"


def _t(raw):
    return capture(raw, fmt="xml")[0]


def test_key_rung():
    m = resolve(_t(b"<r><code>4021-KP73</code></r>"), Requirement("code", keys=("code",)))[0]
    assert m.found and m.method == "key" and m.value == "4021-KP73" and m.confidence == 0.95


def test_key_and_shape_agree_boosts():
    m = resolve(_t(b"<r><code>4021-KP73</code></r>"),
                Requirement("code", keys=("code",), shape=CODE))[0]
    assert m.method == "key" and set(m.witnesses) >= {"key", "shape"} and m.confidence == 0.99


def test_contradicted_shape_is_flagged_not_hidden():
    m = resolve(_t(b"<r><code>see notes</code></r>"),
                Requirement("code", keys=("code",), shape=CODE))[0]
    assert m.found and m.method == "key" and "shape_miss" in m.witnesses and m.confidence < 0.95


def test_shape_only_locator_when_nothing_structural_declared():
    ms = resolve(_t(b"<r><a>4021-KP73</a><b>zzz</b></r>"),
                 Requirement("code", shape=CODE, many=True))
    assert [m.method for m in ms] == ["shape"] and ms[0].value == "4021-KP73"


def test_absent_carries_a_reason():
    m = resolve(_t(b"<r><code>4021-KP73</code></r>"),
                Requirement("x", keys=("nothing",), fuzzy=None))[0]
    assert not m.found and m.method == "absent" and m.value is None and m.reason == "no_candidate"


def test_normalize_date_formats():
    for frag in (b"2026-06-17", b"June 17, 2026", b"06/17/2026"):
        m = resolve(_t(b"<r><received>%s</received></r>" % frag),
                    Requirement("received", keys=("received",), normalize="date"))[0]
        assert m.value == date(2026, 6, 17), frag


def test_path_and_within():
    raw = b"<L><good><code>4021-KP73</code></good><bad><code>9999-ZZ99</code></bad></L>"
    m = resolve(_t(raw), Requirement("code", keys=("code",), within="good"))[0]
    assert m.value == "4021-KP73"


def test_synonym_rung():
    syn = {"code": {"code", "record identifier", "recordIdentifier"}}
    m = resolve(_t(b"<r><recordIdentifier>4021-KP73</recordIdentifier></r>"),
                Requirement("code", concept="code", keys=("code",), shape=CODE), synonyms=syn)[0]
    assert m.found and m.method == "synonym" and m.value == "4021-KP73"


def test_lexical_rung_abbreviations():
    m = resolve(_t(b"<r><RECEIVED_DT>2026-06-17</RECEIVED_DT></r>"),
                Requirement("received", keys=("received_date",), normalize="date"))[0]
    assert m.found and m.method == "lexical" and m.value == date(2026, 6, 17)


def test_neighborhood_rung_scoped_to_record():
    raw = (b"<L><rec><code>0001-AA00</code><stage>p</stage><zz>2020-01-01</zz></rec>"
           b"<rec><code>4021-KP73</code><stage>f</stage><zz>2026-06-17</zz></rec></L>")
    ms = resolve(_t(raw), Requirement("received", neighbors=("code", "stage"), shape=DATE,
                                      normalize="date", many=True))
    assert sorted(m.value for m in ms) == [date(2020, 1, 1), date(2026, 6, 17)]


def test_fusion_value_profile_agrees():
    raw = b"<r><code>4021-KP73</code></r>"
    good = resolve(_t(raw), Requirement("code", keys=("code",), exemplars=("0503-AA90", "1235-BQ12")))[0]
    assert "value" in good.witnesses


def test_fusion_value_profile_contradicts():
    raw = b"<r><code>Withdrawn</code></r>"
    m = resolve(_t(raw), Requirement("code", keys=("code",), exemplars=("0503-AA90", "1235-BQ12")))[0]
    assert m.found and "value_miss" in m.witnesses and m.confidence < 0.95


def test_extract_surfaces_reasons_dict():
    r = extract(b"<r><code>4021-KP73</code></r>",
                [Requirement("x", keys=("date",), fuzzy=None)], fmt="xml")
    assert r.fields["x"].reason == "no_candidate" and r.reasons == {"x": "no_candidate"}
